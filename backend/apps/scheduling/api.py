"""Planning API (spec §6.8, ADR 0012).

Reading (filters: see each view):
    GET /rooms/                              admin, staff, teachers
    GET /school-breaks/                      members
    GET /schedules/                          timetable (recurring slots)
    GET /sessions/  /sessions/{id}/          dated sessions
    GET /teacher/sessions/                   the calling teacher's sessions (taught or planned)
    GET /planning/changes/                   history / notification feed
    GET /students/{id}/timetable/            a child's class timetable
    GET /students/{id}/sessions/             a child's class sessions

Visibility: ADMIN/SUPER_ADMIN everything; STAFF read the whole timetable and
sessions; TEACHER their own slots / sessions (planned or substituting) and the
changes concerning them; PARENT the slots, sessions and *notified* changes of
their VERIFIED children's classes, without internal data (reasons, authors,
planned teacher ids).

Teacher self-service (or admin on behalf):
    GET/POST /teachers/{id}/availability/                 recurring availability
    POST     /teachers/{id}/availability/{av}/withdraw/
    GET/POST /teachers/{id}/availability/exceptions/      dated unavailability requests
    POST     /teachers/{id}/availability/exceptions/{ex}/cancel/

Administration (PySide6):
    POST  /admin/rooms/   PATCH /admin/rooms/{id}/   POST /admin/rooms/{id}/deactivate|reactivate/
    POST  /admin/classes/{id}/main-room/             {room|null}
    POST  /admin/courses/                            POST /admin/courses/{id}/deactivate|reactivate/
    POST  /admin/schedules/                          POST /admin/schedules/check/ (dry run, conflicts)
    POST  /admin/schedules/{id}/end/ | /reschedule/
    POST  /admin/sessions/generate/                  POST /admin/sessions/ (exceptional session)
    POST  /admin/sessions/{id}/cancel/ | /move/ | /room/ | /substitute/ | /restore-teacher/
    POST  /admin/sessions/swap/
    GET   /admin/unavailability/                     POST /admin/unavailability/{id}/decide/
    GET   /admin/unavailability/{id}/impacted-sessions/
    POST  /admin/school-breaks/
    GET   /admin/planning/changes/?notification_status=PENDING   (future notification dispatcher)

All writes go through services; ids are resolved in the current school (404
otherwise); conflicts answer 409 with details.context.conflicts.
"""

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.urls import path
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.academics.models import AcademicYear, Room, RoomType, SchoolClass, Subject
from apps.gradebook import services as gradebook
from apps.gradebook.api import CourseSerializer
from apps.gradebook.models import Course
from apps.people.api import StudentVisibilityMixin
from apps.people.models import EnrollmentStatus, Student, StudentEnrollment, TeacherProfile
from common.permissions import HasSchoolRole, membership_has_role
from common.tenancy import scope_to_current_school
from common.views import SchoolScopedMixin

from . import services
from .models import (
    ExceptionStatus,
    ScheduleChange,
    ScheduleSlot,
    SchoolBreak,
    SessionStatus,
    SlotStatus,
    TeacherAvailability,
    TeacherAvailabilityException,
    TeachingSession,
)

ADMIN = {"ADMIN", "SUPER_ADMIN"}


def scoped(model, pk, request):
    return get_object_or_404(scope_to_current_school(model.objects.all(), request), pk=pk)


def optional_scoped(model, pk, request):
    return scoped(model, pk, request) if pk else None


class AdminMixin(SchoolScopedMixin):
    permission_classes = [HasSchoolRole]
    required_roles = ADMIN


class PlanningVisibility(SchoolScopedMixin):
    """Who sees which classes / teachers in the planning."""

    def my_teacher(self):
        return TeacherProfile.objects.filter(employee__membership=self.membership()).first()

    def is_staff_member(self):
        return membership_has_role(self.membership(), {"STAFF"})

    def children_class_ids(self):
        return (
            StudentEnrollment.objects.filter(
                student__parent_links__parent__membership=self.membership(),
                student__parent_links__active=True,
                student__parent_links__identity_verified=True,
            )
            .exclude(status=EnrollmentStatus.WITHDRAWN)
            .values("school_class_id")
        )

    def is_parent_view(self):
        return not (self.is_admin() or self.is_staff_member()) and self.my_teacher() is None

    def date_param(self, name):
        raw = self.request.query_params.get(name)
        if not raw:
            return None
        try:
            return serializers.DateField().to_internal_value(raw)
        except serializers.ValidationError:
            raise serializers.ValidationError({name: ["Must be a date (YYYY-MM-DD)."]}) from None


# =============================================================================
# Serializers
# =============================================================================


def _ref(obj, *fields):
    return {f: (str(getattr(obj, f)) if f == "id" else getattr(obj, f)) for f in fields} if obj else None


class RoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Room
        fields = ["id", "code", "name", "room_type", "capacity", "bench_count", "active"]


class SlotSerializer(serializers.ModelSerializer):
    subject = serializers.SerializerMethodField()
    school_class = serializers.SerializerMethodField()
    teacher = serializers.SerializerMethodField()
    room = serializers.SerializerMethodField()

    class Meta:
        model = ScheduleSlot
        fields = [
            "id",
            "course",
            "subject",
            "school_class",
            "teacher",
            "room",
            "weekday",
            "start_time",
            "end_time",
            "effective_from",
            "effective_to",
            "status",
        ]

    def get_subject(self, obj):
        return _ref(obj.course.subject, "id", "code", "name")

    def get_school_class(self, obj):
        return _ref(obj.school_class, "id", "name")

    def get_teacher(self, obj):
        return {"id": str(obj.teacher_id), "name": obj.teacher.employee.membership.user.full_name}

    def get_room(self, obj):
        return _ref(obj.room, "id", "code", "name")


class SessionSerializer(serializers.ModelSerializer):
    subject = serializers.SerializerMethodField()
    school_class = serializers.SerializerMethodField()
    teacher = serializers.SerializerMethodField()
    planned_teacher = serializers.SerializerMethodField()
    room = serializers.SerializerMethodField()
    is_substituted = serializers.BooleanField(read_only=True)
    is_moved = serializers.BooleanField(read_only=True)

    class Meta:
        model = TeachingSession
        fields = [
            "id",
            "schedule_slot",
            "course",
            "subject",
            "school_class",
            "academic_period",
            "planned_teacher",
            "teacher",
            "room",
            "date",
            "scheduled_start",
            "scheduled_end",
            "original_start",
            "original_end",
            "status",
            "is_substituted",
            "is_moved",
        ]

    def get_subject(self, obj):
        return _ref(obj.subject, "id", "code", "name")

    def get_school_class(self, obj):
        return _ref(obj.school_class, "id", "name")

    def get_teacher(self, obj):
        return {"id": str(obj.teacher_id), "name": obj.teacher.employee.membership.user.full_name}

    def get_planned_teacher(self, obj):
        return {"id": str(obj.planned_teacher_id), "name": obj.planned_teacher.employee.membership.user.full_name}

    def get_room(self, obj):
        return _ref(obj.room, "id", "code", "name")


class ParentSessionSerializer(SessionSerializer):
    """Families: what, when, where, who teaches — no internal data."""

    class Meta(SessionSerializer.Meta):
        fields = [
            "id",
            "subject",
            "school_class",
            "teacher",
            "room",
            "date",
            "scheduled_start",
            "scheduled_end",
            "original_start",
            "original_end",
            "status",
            "is_substituted",
            "is_moved",
        ]


class ChangeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScheduleChange
        fields = [
            "id",
            "change_type",
            "schedule_slot",
            "session",
            "school_class",
            "teacher_ids",
            "old_data",
            "new_data",
            "reason",
            "changed_by",
            "changed_at",
            "notification_status",
            "notified_at",
        ]


class ParentChangeSerializer(serializers.ModelSerializer):
    new = serializers.SerializerMethodField()

    class Meta:
        model = ScheduleChange
        fields = ["id", "change_type", "session", "school_class", "changed_at", "new"]

    def get_new(self, obj):
        keep = ("date", "scheduled_start", "scheduled_end", "status")
        return {k: v for k, v in obj.new_data.items() if k in keep}


class AvailabilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = TeacherAvailability
        fields = ["id", "teacher", "weekday", "start_time", "end_time", "available", "reason", "active"]
        read_only_fields = ["id", "teacher", "active"]


class ExceptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeacherAvailabilityException
        fields = [
            "id",
            "teacher",
            "date",
            "start_time",
            "end_time",
            "reason",
            "status",
            "requested_by",
            "decided_by",
            "decided_at",
            "decision_comment",
        ]
        read_only_fields = ["id", "teacher", "status", "requested_by", "decided_by", "decided_at", "decision_comment"]


class BreakSerializer(serializers.ModelSerializer):
    class Meta:
        model = SchoolBreak
        fields = ["id", "academic_year", "name", "start_datetime", "end_datetime", "break_type", "affects_scheduling"]


# =============================================================================
# Reading
# =============================================================================


class RoomList(PlanningVisibility, generics.ListAPIView):
    """?active= ?room_type= ?search="""

    queryset = Room.objects.order_by("code")
    serializer_class = RoomSerializer

    def restrict(self, queryset):
        if not (self.is_admin() or self.is_staff_member() or self.my_teacher()):
            return queryset.none()
        active = self.request.query_params.get("active")
        if active in ("true", "false"):
            queryset = queryset.filter(active=active == "true")
        room_type = self.request.query_params.get("room_type")
        if room_type:
            queryset = queryset.filter(room_type=room_type)
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(Q(code__icontains=search) | Q(name__icontains=search))
        return queryset


class BreakList(SchoolScopedMixin, generics.ListAPIView):
    queryset = SchoolBreak.objects.order_by("start_datetime")
    serializer_class = BreakSerializer


class SlotList(PlanningVisibility, generics.ListAPIView):
    """?school_class= ?teacher= ?room= ?subject= ?weekday= ?academic_year= ?status= (default PUBLISHED)"""

    queryset = ScheduleSlot.objects.select_related(
        "course__subject", "school_class", "teacher__employee__membership__user", "room"
    ).order_by("weekday", "start_time")
    serializer_class = SlotSerializer

    def restrict(self, queryset):
        for name, lookup in (
            ("school_class", "school_class_id"),
            ("teacher", "teacher_id"),
            ("room", "room_id"),
            ("subject", "course__subject_id"),
            ("academic_year", "academic_year_id"),
        ):
            value = self.uuid_param(name)
            if value:
                queryset = queryset.filter(**{lookup: value})
        weekday = self.request.query_params.get("weekday")
        if weekday:
            queryset = queryset.filter(weekday=weekday)
        queryset = queryset.filter(status=self.request.query_params.get("status") or SlotStatus.PUBLISHED)
        if self.is_admin() or self.is_staff_member():
            return queryset
        teacher = self.my_teacher()
        if teacher is not None:
            return queryset.filter(teacher=teacher)
        return queryset.filter(school_class_id__in=self.children_class_ids())


class SessionQuerysetMixin(PlanningVisibility):
    queryset = TeachingSession.objects.select_related(
        "subject",
        "school_class",
        "room",
        "teacher__employee__membership__user",
        "planned_teacher__employee__membership__user",
    ).order_by("scheduled_start")

    def filter_sessions(self, queryset):
        date_from, date_to = self.date_param("date_from"), self.date_param("date_to")
        if date_from:
            queryset = queryset.filter(date__gte=date_from)
        if date_to:
            queryset = queryset.filter(date__lte=date_to)
        for name, lookup in (
            ("school_class", "school_class_id"),
            ("room", "room_id"),
            ("subject", "subject_id"),
            ("academic_period", "academic_period_id"),
            ("course", "course_id"),
        ):
            value = self.uuid_param(name)
            if value:
                queryset = queryset.filter(**{lookup: value})
        teacher = self.uuid_param("teacher")
        if teacher:
            queryset = queryset.filter(Q(teacher_id=teacher) | Q(planned_teacher_id=teacher))
        session_status = self.request.query_params.get("status")
        if session_status:
            if session_status not in SessionStatus.values:
                raise serializers.ValidationError({"status": ["Unknown status."]})
            queryset = queryset.filter(status=session_status)
        return queryset

    def visible_sessions(self, queryset):
        if self.is_admin() or self.is_staff_member():
            return queryset
        teacher = self.my_teacher()
        if teacher is not None:
            return queryset.filter(Q(teacher=teacher) | Q(planned_teacher=teacher))
        return queryset.filter(school_class_id__in=self.children_class_ids())

    def get_serializer_class(self):
        return ParentSessionSerializer if self.is_parent_view() else SessionSerializer


class SessionList(SessionQuerysetMixin, generics.ListAPIView):
    """?date_from= ?date_to= ?school_class= ?teacher= ?room= ?subject= ?academic_period= ?course= ?status="""

    def restrict(self, queryset):
        return self.visible_sessions(self.filter_sessions(queryset))


class SessionDetail(SessionQuerysetMixin, generics.RetrieveAPIView):
    def restrict(self, queryset):
        return self.visible_sessions(queryset)


class MyTeacherSessions(SessionQuerysetMixin, generics.ListAPIView):
    """GET /teacher/sessions/ (spec §6.8): sessions I teach or was planned on."""

    def restrict(self, queryset):
        teacher = self.my_teacher()
        if teacher is None:
            return queryset.none()
        return self.filter_sessions(queryset).filter(Q(teacher=teacher) | Q(planned_teacher=teacher))


class ChangeList(PlanningVisibility, generics.ListAPIView):
    """?school_class= ?session= ?change_type= ?date_from= (changed since)"""

    queryset = ScheduleChange.objects.order_by("-changed_at")

    def get_serializer_class(self):
        return ParentChangeSerializer if self.is_parent_view() else ChangeSerializer

    def restrict(self, queryset):
        for name, lookup in (("school_class", "school_class_id"), ("session", "session_id")):
            value = self.uuid_param(name)
            if value:
                queryset = queryset.filter(**{lookup: value})
        change_type = self.request.query_params.get("change_type")
        if change_type:
            queryset = queryset.filter(change_type=change_type)
        since = self.date_param("date_from")
        if since:
            queryset = queryset.filter(changed_at__date__gte=since)
        if self.is_admin():
            return queryset
        teacher = self.my_teacher()
        if teacher is not None:
            return queryset.filter(teacher_ids__contains=[str(teacher.pk)])
        if self.is_staff_member():
            return queryset.exclude(notification_status="NOT_REQUIRED")
        return queryset.exclude(notification_status="NOT_REQUIRED").filter(
            school_class_id__in=self.children_class_ids()
        )


class StudentTimetable(StudentVisibilityMixin, PlanningVisibility, generics.GenericAPIView):
    """Recurring timetable of a child's class (current year)."""

    queryset = Student.objects.all()

    def restrict(self, queryset):
        return self.visible_students(queryset)

    def get(self, request, pk):
        student = self.get_object()
        enrollment = (
            student.enrollments.filter(academic_year__is_current=True)
            .exclude(status=EnrollmentStatus.WITHDRAWN)
            .first()
        )
        if enrollment is None:
            return Response([])
        slots = SlotList.queryset.filter(school_class=enrollment.school_class, status=SlotStatus.PUBLISHED)
        return Response(SlotSerializer(slots, many=True).data)


class StudentSessions(StudentVisibilityMixin, SessionQuerysetMixin, generics.ListAPIView):
    """Dated sessions of a child's classes. ?date_from= ?date_to= ?status="""

    def restrict(self, queryset):
        students = self.visible_students(scope_to_current_school(Student.objects.all(), self.request))
        student = get_object_or_404(students, pk=self.kwargs["pk"])
        class_ids = student.enrollments.exclude(status=EnrollmentStatus.WITHDRAWN).values("school_class_id")
        return self.filter_sessions(queryset).filter(school_class_id__in=class_ids)


# =============================================================================
# Teacher self-service
# =============================================================================


class TeacherScope(SchoolScopedMixin):
    def teacher(self):
        return scoped(TeacherProfile, self.kwargs["pk"], self.request)

    def can_read(self, teacher):
        return self.is_admin() or teacher.employee.membership_id == self.membership().pk


class AvailabilityListCreate(TeacherScope, generics.ListAPIView):
    serializer_class = AvailabilitySerializer
    queryset = TeacherAvailability.objects.order_by("weekday", "start_time")

    def restrict(self, queryset):
        teacher = self.teacher()
        return queryset.filter(teacher=teacher) if self.can_read(teacher) else queryset.none()

    def post(self, request, pk):
        data = AvailabilitySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        availability = services.declare_availability(self.teacher(), actor=self.membership(), **data.validated_data)
        return Response(AvailabilitySerializer(availability).data, status=status.HTTP_201_CREATED)


class AvailabilityWithdraw(TeacherScope, APIView):
    def post(self, request, pk, av):
        availability = get_object_or_404(TeacherAvailability, pk=av, teacher=self.teacher())
        return Response(
            AvailabilitySerializer(services.withdraw_availability(availability, actor=self.membership())).data
        )


class ExceptionListCreate(TeacherScope, generics.ListAPIView):
    serializer_class = ExceptionSerializer
    queryset = TeacherAvailabilityException.objects.order_by("-date")

    def restrict(self, queryset):
        teacher = self.teacher()
        return queryset.filter(teacher=teacher) if self.can_read(teacher) else queryset.none()

    def post(self, request, pk):
        data = ExceptionSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        request_obj = services.request_unavailability(
            self.teacher(),
            actor=self.membership(),
            date=v["date"],
            start_time=v["start_time"],
            end_time=v["end_time"],
            reason=v["reason"],
        )
        return Response(ExceptionSerializer(request_obj).data, status=status.HTTP_201_CREATED)


class ExceptionCancel(TeacherScope, APIView):
    def post(self, request, pk, ex):
        request_obj = get_object_or_404(TeacherAvailabilityException, pk=ex, teacher=self.teacher())
        return Response(ExceptionSerializer(services.cancel_unavailability(request_obj, actor=self.membership())).data)


# =============================================================================
# Administration
# =============================================================================


class RoomInput(serializers.Serializer):
    code = serializers.CharField(max_length=30, required=False)
    name = serializers.CharField(max_length=100, required=False)
    room_type = serializers.ChoiceField(choices=RoomType.choices, required=False)
    capacity = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    bench_count = serializers.IntegerField(min_value=0, required=False, allow_null=True)


class AdminRoomCreate(AdminMixin, APIView):
    def post(self, request):
        data = RoomInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        if not v.get("code") or not v.get("name"):
            raise serializers.ValidationError({"code": ["Required."], "name": ["Required."]})
        room = services.create_room(self.membership().school, actor=self.membership(), **v)
        return Response(RoomSerializer(room).data, status=status.HTTP_201_CREATED)


class AdminRoomUpdate(AdminMixin, APIView):
    def patch(self, request, pk):
        data = RoomInput(data=request.data)
        data.is_valid(raise_exception=True)
        room = services.update_room(scoped(Room, pk, request), actor=self.membership(), **data.validated_data)
        return Response(RoomSerializer(room).data)


class AdminRoomActivation(AdminMixin, APIView):
    active = None

    def post(self, request, pk):
        room = services.set_room_active(scoped(Room, pk, request), self.active, actor=self.membership())
        return Response(RoomSerializer(room).data)


class MainRoomInput(serializers.Serializer):
    room = serializers.UUIDField(allow_null=True)


class AdminClassMainRoom(AdminMixin, APIView):
    def post(self, request, pk):
        data = MainRoomInput(data=request.data)
        data.is_valid(raise_exception=True)
        school_class = services.set_class_main_room(
            scoped(SchoolClass, pk, request),
            optional_scoped(Room, data.validated_data["room"], request),
            actor=self.membership(),
        )
        return Response(
            {"school_class": str(school_class.pk), "main_room": str(school_class.main_room_id or "") or None}
        )


class CourseInput(serializers.Serializer):
    school_class = serializers.UUIDField()
    subject = serializers.UUIDField()
    teacher = serializers.UUIDField()
    coefficient = serializers.DecimalField(max_digits=6, decimal_places=2, required=False)
    weekly_hours = serializers.DecimalField(max_digits=5, decimal_places=2, required=False)


class AdminCourseCreate(AdminMixin, APIView):
    def post(self, request):
        data = CourseInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        extra = {k: v[k] for k in ("coefficient", "weekly_hours") if k in v}
        course = gradebook.create_course(
            scoped(SchoolClass, v["school_class"], request),
            scoped(Subject, v["subject"], request),
            scoped(TeacherProfile, v["teacher"], request),
            actor=self.membership(),
            **extra,
        )
        return Response(CourseSerializer(course).data, status=status.HTTP_201_CREATED)


class AdminCourseActivation(AdminMixin, APIView):
    active = None

    def post(self, request, pk):
        course = gradebook.set_course_active(scoped(Course, pk, request), self.active, actor=self.membership())
        return Response(CourseSerializer(course).data)


class SlotInput(serializers.Serializer):
    course = serializers.UUIDField()
    weekday = serializers.IntegerField(min_value=1, max_value=7)
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()
    room = serializers.UUIDField(required=False, allow_null=True)
    effective_from = serializers.DateField(required=False, allow_null=True)
    effective_to = serializers.DateField(required=False, allow_null=True)
    force_availability = serializers.BooleanField(required=False, default=False)
    reason = serializers.CharField(required=False, allow_blank=True, allow_null=True)


def _slot_args(data, request):
    v = dict(data)
    v["course"] = scoped(Course, v["course"], request)
    v["room"] = optional_scoped(Room, v.get("room"), request)
    return v


class AdminSlotCreate(AdminMixin, APIView):
    def post(self, request):
        data = SlotInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = _slot_args(data.validated_data, request)
        slot = services.create_slot(v.pop("course"), actor=self.membership(), **v)
        return Response(SlotSerializer(slot).data, status=status.HTTP_201_CREATED)


class AdminSlotCheck(AdminMixin, APIView):
    """Dry run: what would creating this slot hit? Writes nothing."""

    def post(self, request):
        data = SlotInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = _slot_args(data.validated_data, request)
        v.pop("force_availability", None)
        v.pop("reason", None)
        return Response(services.check_slot(v.pop("course"), **v))


class EndSlotInput(serializers.Serializer):
    last_date = serializers.DateField()
    reason = serializers.CharField()


class AdminSlotEnd(AdminMixin, APIView):
    def post(self, request, pk):
        data = EndSlotInput(data=request.data)
        data.is_valid(raise_exception=True)
        slot = services.end_slot(scoped(ScheduleSlot, pk, request), actor=self.membership(), **data.validated_data)
        return Response(SlotSerializer(slot).data)


class RescheduleInput(serializers.Serializer):
    from_date = serializers.DateField()
    weekday = serializers.IntegerField(min_value=1, max_value=7)
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()
    room = serializers.UUIDField(required=False, allow_null=True)
    reason = serializers.CharField()


class AdminSlotReschedule(AdminMixin, APIView):
    def post(self, request, pk):
        data = RescheduleInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = dict(data.validated_data)
        v["room"] = optional_scoped(Room, v.get("room"), request)
        slot = services.reschedule_slot(scoped(ScheduleSlot, pk, request), actor=self.membership(), **v)
        return Response(SlotSerializer(slot).data, status=status.HTTP_201_CREATED)


class GenerateInput(serializers.Serializer):
    date_from = serializers.DateField()
    date_to = serializers.DateField()
    school_class = serializers.UUIDField(required=False, allow_null=True)


class AdminGenerateSessions(AdminMixin, APIView):
    def post(self, request):
        data = GenerateInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        return Response(
            services.generate_sessions(
                self.membership().school,
                actor=self.membership(),
                date_from=v["date_from"],
                date_to=v["date_to"],
                school_class=optional_scoped(SchoolClass, v.get("school_class"), request),
            )
        )


class ExceptionalSessionInput(serializers.Serializer):
    course = serializers.UUIDField()
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    room = serializers.UUIDField(required=False, allow_null=True)
    reason = serializers.CharField()


class AdminSessionCreate(AdminMixin, APIView):
    def post(self, request):
        data = ExceptionalSessionInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        session = services.create_exceptional_session(
            scoped(Course, v["course"], request),
            actor=self.membership(),
            start=v["start"],
            end=v["end"],
            room=optional_scoped(Room, v.get("room"), request),
            reason=v["reason"],
        )
        return Response(SessionSerializer(session).data, status=status.HTTP_201_CREATED)


class ReasonInput(serializers.Serializer):
    reason = serializers.CharField()


class MoveInput(ReasonInput):
    new_start = serializers.DateTimeField()
    new_end = serializers.DateTimeField()


class RoomChangeInput(ReasonInput):
    room = serializers.UUIDField(allow_null=True)


class SubstituteInput(ReasonInput):
    teacher = serializers.UUIDField()


class SwapInput(ReasonInput):
    first = serializers.UUIDField()
    second = serializers.UUIDField()


class AdminSessionAction(AdminMixin, APIView):
    """One endpoint class per action, configured in urlpatterns."""

    action = None

    def post(self, request, pk):
        session = scoped(TeachingSession, pk, request)
        actor = self.membership()
        if self.action == "cancel":
            v = self.valid(ReasonInput)
            session = services.cancel_session(session, actor=actor, **v)
        elif self.action == "move":
            v = self.valid(MoveInput)
            session = services.move_session(session, actor=actor, **v)
        elif self.action == "room":
            v = self.valid(RoomChangeInput)
            session = services.change_session_room(
                session, optional_scoped(Room, v["room"], request), actor=actor, reason=v["reason"]
            )
        elif self.action == "substitute":
            v = self.valid(SubstituteInput)
            session = services.substitute_teacher(
                session, scoped(TeacherProfile, v["teacher"], request), actor=actor, reason=v["reason"]
            )
        elif self.action == "restore-teacher":
            v = self.valid(ReasonInput)
            session = services.restore_teacher(session, actor=actor, **v)
        return Response(SessionSerializer(session).data)

    def valid(self, serializer_class):
        data = serializer_class(data=self.request.data)
        data.is_valid(raise_exception=True)
        return dict(data.validated_data)


class AdminSessionSwap(AdminMixin, APIView):
    def post(self, request):
        data = SwapInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        a, b = services.swap_sessions(
            scoped(TeachingSession, v["first"], request),
            scoped(TeachingSession, v["second"], request),
            actor=self.membership(),
            reason=v["reason"],
        )
        return Response(SessionSerializer([a, b], many=True).data)


class AdminUnavailabilityList(AdminMixin, generics.ListAPIView):
    """?status= (default: PENDING) ?teacher="""

    queryset = TeacherAvailabilityException.objects.order_by("date", "start_time")
    serializer_class = ExceptionSerializer

    def restrict(self, queryset):
        teacher = self.uuid_param("teacher")
        if teacher:
            queryset = queryset.filter(teacher_id=teacher)
        return queryset.filter(status=self.request.query_params.get("status") or ExceptionStatus.PENDING)


class DecisionInput(serializers.Serializer):
    decision = serializers.ChoiceField(
        choices=[ExceptionStatus.APPROVED, ExceptionStatus.REJECTED, ExceptionStatus.CHANGES_REQUESTED]
    )
    comment = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class AdminUnavailabilityDecide(AdminMixin, APIView):
    def post(self, request, pk):
        data = DecisionInput(data=request.data)
        data.is_valid(raise_exception=True)
        request_obj, impacted = services.decide_unavailability(
            scoped(TeacherAvailabilityException, pk, request), actor=self.membership(), **data.validated_data
        )
        return Response(
            {
                "request": ExceptionSerializer(request_obj).data,
                "impacted_sessions": SessionSerializer(impacted, many=True).data,
            }
        )


class AdminImpactedSessions(AdminMixin, APIView):
    def get(self, request, pk):
        request_obj = scoped(TeacherAvailabilityException, pk, request)
        return Response(SessionSerializer(services.impacted_sessions(request_obj), many=True).data)


class BreakInput(serializers.Serializer):
    academic_year = serializers.UUIDField()
    name = serializers.CharField(max_length=120)
    start_datetime = serializers.DateTimeField()
    end_datetime = serializers.DateTimeField()
    break_type = serializers.CharField(required=False, default="HOLIDAY")
    affects_scheduling = serializers.BooleanField(required=False, default=True)


class AdminBreakCreate(AdminMixin, APIView):
    def post(self, request):
        data = BreakInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = dict(data.validated_data)
        year = scoped(AcademicYear, v.pop("academic_year"), request)
        school_break = services.create_school_break(year, actor=self.membership(), **v)
        return Response(BreakSerializer(school_break).data, status=status.HTTP_201_CREATED)


class AdminChangeList(AdminMixin, generics.ListAPIView):
    """?notification_status=PENDING — the feed of the future dispatcher."""

    queryset = ScheduleChange.objects.order_by("changed_at")
    serializer_class = ChangeSerializer

    def restrict(self, queryset):
        notification_status = self.request.query_params.get("notification_status")
        return queryset.filter(notification_status=notification_status) if notification_status else queryset


def _session_action(name):
    return AdminSessionAction.as_view(action=name)


urlpatterns = [
    path("rooms/", RoomList.as_view(), name="rooms"),
    path("school-breaks/", BreakList.as_view(), name="school-breaks"),
    path("schedules/", SlotList.as_view(), name="schedules"),
    path("sessions/", SessionList.as_view(), name="sessions"),
    path("sessions/<uuid:pk>/", SessionDetail.as_view(), name="session"),
    path("teacher/sessions/", MyTeacherSessions.as_view(), name="teacher-sessions"),
    path("planning/changes/", ChangeList.as_view(), name="planning-changes"),
    path("students/<uuid:pk>/timetable/", StudentTimetable.as_view(), name="student-timetable"),
    path("students/<uuid:pk>/sessions/", StudentSessions.as_view(), name="student-sessions"),
    path("teachers/<uuid:pk>/availability/", AvailabilityListCreate.as_view(), name="teacher-availability"),
    path("teachers/<uuid:pk>/availability/<uuid:av>/withdraw/", AvailabilityWithdraw.as_view()),
    path("teachers/<uuid:pk>/availability/exceptions/", ExceptionListCreate.as_view(), name="teacher-exceptions"),
    path("teachers/<uuid:pk>/availability/exceptions/<uuid:ex>/cancel/", ExceptionCancel.as_view()),
    path("admin/rooms/", AdminRoomCreate.as_view(), name="admin-rooms"),
    path("admin/rooms/<uuid:pk>/", AdminRoomUpdate.as_view(), name="admin-room"),
    path("admin/rooms/<uuid:pk>/deactivate/", AdminRoomActivation.as_view(active=False)),
    path("admin/rooms/<uuid:pk>/reactivate/", AdminRoomActivation.as_view(active=True)),
    path("admin/classes/<uuid:pk>/main-room/", AdminClassMainRoom.as_view()),
    path("admin/courses/", AdminCourseCreate.as_view(), name="admin-courses"),
    path("admin/courses/<uuid:pk>/deactivate/", AdminCourseActivation.as_view(active=False)),
    path("admin/courses/<uuid:pk>/reactivate/", AdminCourseActivation.as_view(active=True)),
    path("admin/schedules/", AdminSlotCreate.as_view(), name="admin-schedules"),
    path("admin/schedules/check/", AdminSlotCheck.as_view(), name="admin-schedules-check"),
    path("admin/schedules/<uuid:pk>/end/", AdminSlotEnd.as_view()),
    path("admin/schedules/<uuid:pk>/reschedule/", AdminSlotReschedule.as_view()),
    path("admin/sessions/", AdminSessionCreate.as_view(), name="admin-sessions"),
    path("admin/sessions/generate/", AdminGenerateSessions.as_view(), name="admin-sessions-generate"),
    path("admin/sessions/swap/", AdminSessionSwap.as_view(), name="admin-sessions-swap"),
    *[
        path(f"admin/sessions/<uuid:pk>/{a}/", _session_action(a))
        for a in ("cancel", "move", "room", "substitute", "restore-teacher")
    ],
    path("admin/unavailability/", AdminUnavailabilityList.as_view(), name="admin-unavailability"),
    path("admin/unavailability/<uuid:pk>/decide/", AdminUnavailabilityDecide.as_view()),
    path("admin/unavailability/<uuid:pk>/impacted-sessions/", AdminImpactedSessions.as_view()),
    path("admin/school-breaks/", AdminBreakCreate.as_view(), name="admin-school-breaks"),
    path("admin/planning/changes/", AdminChangeList.as_view(), name="admin-planning-changes"),
]
