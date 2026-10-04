"""Courses API (ADR 0020) — PySide6 "Gestion académique → Cours".

    GET   /courses/   ?search= ?status=active|inactive ?academic_year= ?school_class= ?level= ?subject= ?teacher=
                      admin: all; teacher: their own courses; others: none           (paginated)
    POST  /courses/   {school_class, subject, teacher, coefficient?, weekly_hours?, grading_scale?}   (admin)
    GET   /courses/{id}/                                                             (admin, or its teacher)
    PATCH /courses/{id}/   {teacher?, coefficient?, weekly_hours?, grading_scale?}   (admin)
    POST  /courses/{id}/deactivate/ | /reactivate/                                   (admin)
    GET   /courses/eligible-teachers/?school_class=&subject=                         (admin)
          -> {"eligible": [...], "excluded": [{..., "reason"}]}

The year of a course is its class's year. Which teacher may teach is
decided by gradebook.services.teacher_refusal (teacher state, qualification,
compatibility engine at the class's level): the desktop only shows the
`eligible` list. Errors: 403 role, 404 another school's class / subject /
teacher / scale, 409 duplicate, coefficient conflict, identity immutable,
still scheduled; 400 rule (inactive subject / category / class / teacher,
closed year, incompatible or unqualified teacher).
"""

from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404
from django.urls import path
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.academics.models import GradingScale, SchoolClass, Subject
from apps.people.models import QualificationStatus, TeacherProfile
from common.permissions import membership_has_role
from common.tenancy import scope_to_current_school
from common.views import SchoolScopedMixin

from . import services
from .api import CourseSerializer
from .models import Course


def _ref(obj, *names):
    if obj is None:
        return None
    return {"id": str(obj.pk), **{name: getattr(obj, name) for name in names}}


def _teacher_ref(teacher):
    user = teacher.employee.membership.user
    return {
        "id": str(teacher.pk),
        "number": teacher.employee.employee_number,
        "name": f"{user.last_name} {user.first_name}".strip(),
        "category": teacher.pedagogical_category.code,
    }


class CourseAdminSerializer(CourseSerializer):
    """The historical fields (class_name, subject_code, teacher_name…) + labels."""

    class_ref = serializers.SerializerMethodField()
    level = serializers.SerializerMethodField()
    subject_ref = serializers.SerializerMethodField()
    teacher_ref = serializers.SerializerMethodField()
    year = serializers.SerializerMethodField()
    scale = serializers.SerializerMethodField()

    class Meta(CourseSerializer.Meta):
        fields = [*CourseSerializer.Meta.fields, "class_ref", "level", "subject_ref", "teacher_ref", "year", "scale"]

    def get_class_ref(self, obj):
        return _ref(obj.school_class, "name", "active")

    def get_level(self, obj):
        return _ref(obj.school_class.level, "code", "name")

    def get_subject_ref(self, obj):
        return _ref(obj.subject, "code", "name", "active") | {"category": obj.subject.category.code}

    def get_teacher_ref(self, obj):
        return _teacher_ref(obj.teacher)

    def get_year(self, obj):
        return _ref(obj.academic_year, "name", "status")

    def get_scale(self, obj):
        return _ref(obj.grading_scale, "code", "label")


class CourseDetailSerializer(CourseAdminSerializer):
    published_slot_count = serializers.SerializerMethodField()
    upcoming_session_count = serializers.SerializerMethodField()

    class Meta(CourseAdminSerializer.Meta):
        fields = [*CourseAdminSerializer.Meta.fields, "published_slot_count", "upcoming_session_count"]

    def get_published_slot_count(self, obj):
        return services._scheduled(obj)[0]

    def get_upcoming_session_count(self, obj):
        return services._scheduled(obj)[1]


class CourseInput(serializers.Serializer):
    school_class = serializers.UUIDField()
    subject = serializers.UUIDField()
    teacher = serializers.UUIDField()
    coefficient = serializers.DecimalField(max_digits=6, decimal_places=2, min_value=Decimal("0.01"), required=False)
    weekly_hours = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal("0"), required=False)
    grading_scale = serializers.UUIDField(required=False, allow_null=True)


class CourseUpdate(serializers.Serializer):
    school_class = serializers.UUIDField(required=False)  # accepted only to say it is immutable
    subject = serializers.UUIDField(required=False)
    teacher = serializers.UUIDField(required=False)
    coefficient = serializers.DecimalField(max_digits=6, decimal_places=2, min_value=Decimal("0.01"), required=False)
    weekly_hours = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=Decimal("0"), required=False)
    grading_scale = serializers.UUIDField(required=False, allow_null=True)


def _scoped(model, pk, request):
    """An object of the CURRENT school (404 otherwise, like a missing id)."""
    found = scope_to_current_school(model.objects.all(), request).filter(pk=pk).first()
    if found is None:
        raise Http404
    return found


def _resolve(data, request):
    resolved = dict(data)
    for name, model in (("school_class", SchoolClass), ("subject", Subject), ("teacher", TeacherProfile)):
        if name in resolved:
            resolved[name] = _scoped(model, resolved[name], request)
    if "grading_scale" in resolved:
        pk = resolved["grading_scale"]
        resolved["grading_scale"] = _scoped(GradingScale, pk, request) if pk else None
    return resolved


class CourseScope(SchoolScopedMixin):
    queryset = Course.objects.select_related(
        "school_class__level",
        "subject__category",
        "teacher__employee__membership__user",
        "teacher__pedagogical_category",
        "academic_year",
        "grading_scale",
    )

    def visible(self, queryset):
        if self.is_admin():
            return queryset
        if membership_has_role(self.membership(), {"TEACHER"}):
            return queryset.filter(teacher__employee__membership=self.membership())
        return queryset.none()

    def restrict(self, queryset):
        return self.visible(queryset)

    def get_serializer_class(self):
        return CourseAdminSerializer if self.is_admin() else CourseSerializer

    def course(self):
        found = self.visible(scope_to_current_school(Course.objects.all(), self.request)).filter(pk=self.kwargs["pk"])
        found = found.first()
        if found is None:
            raise Http404
        return found


class CourseListCreate(CourseScope, generics.ListAPIView):
    def restrict(self, queryset):
        queryset = self.visible(queryset)
        params = self.request.query_params
        for name, field in (
            ("academic_year", "academic_year_id"),
            ("school_class", "school_class_id"),
            ("level", "school_class__level_id"),
            ("subject", "subject_id"),
            ("teacher", "teacher_id"),
        ):
            value = self.uuid_param(name)
            if value:
                queryset = queryset.filter(**{field: value})
        wanted = params.get("status")
        if wanted in ("active", "inactive"):
            queryset = queryset.filter(active=wanted == "active")
        elif wanted:
            raise serializers.ValidationError({"status": ["Use active or inactive."]})
        search = (params.get("search") or "").strip()
        if search:
            q = Q()
            for lookup in (
                "subject__code",
                "subject__name",
                "school_class__name",
                "teacher__employee__membership__user__last_name",
                "teacher__employee__membership__user__first_name",
                "teacher__employee__employee_number",
            ):
                q |= Q(**{f"{lookup}__icontains": search})
            queryset = queryset.filter(q)
        return queryset.order_by("school_class__name", "subject__name", "teacher__employee__employee_number")

    def post(self, request):
        data = CourseInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = _resolve(data.validated_data, request)
        extra = {k: v[k] for k in ("coefficient", "weekly_hours", "grading_scale") if k in v}
        course = services.create_course(v["school_class"], v["subject"], v["teacher"], actor=self.membership(), **extra)
        return Response(CourseDetailSerializer(course).data, status=status.HTTP_201_CREATED)


class CourseDetail(CourseScope, generics.RetrieveAPIView):
    def get_serializer_class(self):
        return CourseDetailSerializer if self.is_admin() else CourseSerializer

    def patch(self, request, pk):
        course = self.course()
        data = CourseUpdate(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        course = services.update_course(course, actor=self.membership(), **_resolve(data.validated_data, request))
        return Response(CourseDetailSerializer(course).data)


class CourseActivation(CourseScope, APIView):
    active = None  # set by as_view()

    def post(self, request, pk):
        course = services.set_course_active(self.course(), self.active, actor=self.membership())
        return Response(CourseDetailSerializer(course).data)


class EligibleTeachers(CourseScope, APIView):
    """Teachers who may teach `subject` in `school_class`, decided by the
    server (teacher_refusal). Teachers holding a qualification for the
    subject who are NOT eligible are listed apart with the rule code, so the
    screen can say why someone is missing."""

    def get(self, request):
        if not self.is_admin():
            raise PermissionDenied
        class_id, subject_id = self.uuid_param("school_class"), self.uuid_param("subject")
        if not (class_id and subject_id):
            raise serializers.ValidationError({"school_class": ["school_class and subject are required."]})
        school_class = _scoped(SchoolClass, class_id, request)
        subject = _scoped(Subject, subject_id, request)
        candidates = (
            scope_to_current_school(TeacherProfile.objects.all(), request)
            .filter(qualifications__subject=subject)
            .exclude(qualifications__subject=subject, qualifications__status=QualificationStatus.REJECTED)
            .select_related("employee__membership__user", "pedagogical_category")
            .distinct()
        )
        eligible, excluded = [], []
        for teacher in candidates:
            refusal = services.teacher_refusal(teacher, subject, school_class)
            if refusal is None:
                eligible.append(_teacher_ref(teacher))
            else:
                excluded.append(_teacher_ref(teacher) | {"reason": refusal})
        key = lambda row: row["name"]  # noqa: E731
        return Response({"eligible": sorted(eligible, key=key), "excluded": sorted(excluded, key=key)})


urlpatterns = [
    path("courses/", CourseListCreate.as_view(), name="courses"),
    path("courses/eligible-teachers/", EligibleTeachers.as_view(), name="course-eligible-teachers"),
    path("courses/<uuid:pk>/", CourseDetail.as_view(), name="course"),
    path("courses/<uuid:pk>/deactivate/", CourseActivation.as_view(active=False), name="course-deactivate"),
    path("courses/<uuid:pk>/reactivate/", CourseActivation.as_view(active=True), name="course-reactivate"),
]
