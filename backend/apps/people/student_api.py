"""Students API (spec §6.4) — reads by visibility, writes by administrators
(PySide6 "Gestion académique → Élèves", ADR 0018).

    GET   /students/                 ?search= ?status= ?academic_year= ?level= ?school_class=
                                     ?enrollment_status=ACTIVE|COMPLETED|WITHDRAWN|NONE   (visible students)
    POST  /students/                 {identity…, enrollment?: {school_class, enrollment_date?}}   (admin)
    GET   /students/{id}/                                                                (visible)
    PATCH /students/{id}/            {identity…}                                         (admin)
    POST  /students/{id}/archive/ | /reactivate/                                         (admin)
    GET   /students/{id}/enrollments/                                                    (visible)
    POST  /students/{id}/enrollments/  {school_class, enrollment_date?}                  (admin)
    POST  /enrollments/{id}/change-class/  {school_class}                                (admin)
    POST  /enrollments/{id}/withdraw/      {end_date?}                                   (admin)
    GET   /students/{id}/photo/      image/jpeg                                          (visible)
    POST  /students/{id}/photo/      multipart "photo"     DELETE /students/{id}/photo/  (admin)
    GET   /students/{id}/history/    enrollments and changes from the audit trail        (admin)

Visibility (unchanged): administrators see every student of the school, a
parent their verified children, a teacher the pupils of their classes; any
other id — including another school's — is a 404. Writes go through
people.services (role ADMIN/SUPER_ADMIN of the student's school, audit).
Referenced classes are looked up in the current school (404 otherwise).
Errors: 403 role, 404 out of scope, 409 duplicate matricule / already
enrolled / class full / still enrolled / closed enrollment / same class,
400 invalid data or rule (closed year, inactive class, other year…).

The list is paginated by the API; each row carries the enrollment of the
selected year (default: the current year) so the admin list needs no extra
call per student.
"""

from django.db.models import OuterRef, Q, Subquery
from django.http import FileResponse, Http404
from django.urls import path
from rest_framework import generics, serializers, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.academics.models import AcademicYear, SchoolClass
from common.tenancy import scope_to_current_school

from . import services
from .api import EnrollmentSerializer, StudentSerializer, StudentVisibilityMixin
from .models import EnrollmentStatus, Sex, Student, StudentEnrollment, StudentStatus

# -----------------------------------------------------------------------------
# Serializers
# -----------------------------------------------------------------------------


class StudentAdminSerializer(serializers.ModelSerializer):
    """Administrators' view: every administrative field + the enrollment of
    the selected year (annotated by the list, looked up for a detail)."""

    has_photo = serializers.SerializerMethodField()
    enrollment = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = [
            "id",
            "student_number",
            "registration_number",
            "first_name",
            "last_name",
            "date_of_birth",
            "sex",
            "birth_place",
            "address",
            "height_cm",
            "status",
            "archived_at",
            "has_photo",
            "enrollment",
        ]

    def get_has_photo(self, obj):
        return bool(obj.photo)

    def get_enrollment(self, obj):
        if hasattr(obj, "enr_id"):  # annotated by the list
            if obj.enr_id is None:
                return None
            return {
                "id": str(obj.enr_id),
                "academic_year": str(obj.enr_year),
                "academic_year_name": obj.enr_year_name,
                "school_class": str(obj.enr_class),
                "class_name": obj.enr_class_name,
                "level": str(obj.enr_level),
                "level_code": obj.enr_level_code,
                "level_name": obj.enr_level_name,
                "status": obj.enr_status,
            }
        enrollment = current_enrollment(obj)
        return enrollment_payload(enrollment) if enrollment else None


def enrollment_payload(enrollment):
    return {
        "id": str(enrollment.pk),
        "academic_year": str(enrollment.academic_year_id),
        "academic_year_name": enrollment.academic_year.name,
        "school_class": str(enrollment.school_class_id),
        "class_name": enrollment.school_class.name,
        "level": str(enrollment.school_class.level_id),
        "level_code": enrollment.school_class.level.code,
        "level_name": enrollment.school_class.level.name,
        "status": enrollment.status,
    }


def current_enrollment(student):
    """Enrollment of the current year, else the most recent one."""
    rows = student.enrollments.select_related("academic_year", "school_class__level")
    return rows.filter(academic_year__is_current=True).first() or rows.order_by("-academic_year__start_date").first()


class EnrollmentAdminSerializer(EnrollmentSerializer):
    level = serializers.UUIDField(source="school_class.level_id", read_only=True)
    level_code = serializers.CharField(source="school_class.level.code", read_only=True)
    level_name = serializers.CharField(source="school_class.level.name", read_only=True)

    class Meta(EnrollmentSerializer.Meta):
        fields = [*EnrollmentSerializer.Meta.fields, "level", "level_code", "level_name", "student"]


class EnrollmentInput(serializers.Serializer):
    school_class = serializers.UUIDField()
    enrollment_date = serializers.DateField(required=False, allow_null=True)


class StudentInput(serializers.Serializer):
    student_number = serializers.CharField(max_length=50)
    registration_number = serializers.CharField(max_length=50)
    first_name = serializers.CharField(max_length=120)
    last_name = serializers.CharField(max_length=120)
    date_of_birth = serializers.DateField()
    sex = serializers.ChoiceField(choices=Sex.choices)
    birth_place = serializers.CharField(max_length=160, required=False, allow_blank=True, allow_null=True)
    address = serializers.CharField(max_length=500, required=False, allow_blank=True, allow_null=True)
    height_cm = serializers.IntegerField(required=False, allow_null=True)
    enrollment = EnrollmentInput(required=False, allow_null=True)


class StudentUpdate(StudentInput):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, partial=True, **kwargs)
        self.fields.pop("enrollment")


def _class_of(pk, request):
    """A class of the CURRENT school (404 otherwise, like a missing id)."""
    school_class = (
        scope_to_current_school(SchoolClass.objects.select_related("academic_year", "level"), request)
        .filter(pk=pk)
        .first()
    )
    if school_class is None:
        raise Http404
    return school_class


# -----------------------------------------------------------------------------
# Students
# -----------------------------------------------------------------------------

ENROLLMENT_FILTERS = {s for s in EnrollmentStatus.values} | {"NONE"}


class StudentScope(StudentVisibilityMixin):
    queryset = Student.objects.all()

    def restrict(self, queryset):
        return self.visible_students(queryset)

    def get_serializer_class(self):
        return StudentAdminSerializer if self.is_admin() else StudentSerializer

    def student(self):
        student = self.restrict(scope_to_current_school(Student.objects.all(), self.request)).filter(
            pk=self.kwargs["pk"]
        )
        found = student.first()
        if found is None:
            raise Http404
        return found


class StudentListCreate(StudentScope, generics.ListAPIView):
    def target_year(self):
        wanted = self.uuid_param("academic_year")
        years = scope_to_current_school(AcademicYear.objects.all(), self.request)
        return wanted if wanted else years.filter(is_current=True).values_list("pk", flat=True).first()

    def restrict(self, queryset):
        queryset = self.visible_students(queryset)
        params = self.request.query_params
        search = (params.get("search") or "").strip()
        if search:
            q = Q()
            for lookup in ("last_name", "first_name", "student_number", "registration_number"):
                q |= Q(**{f"{lookup}__icontains": search})
            queryset = queryset.filter(q)
        wanted_status = params.get("status")
        if wanted_status:
            if wanted_status not in StudentStatus.values:
                raise serializers.ValidationError({"status": ["Unknown student status."]})
            queryset = queryset.filter(status=wanted_status)
        year = self.target_year()
        enrollments = StudentEnrollment.objects.filter(student=OuterRef("pk"), academic_year=year)
        queryset = queryset.annotate(
            enr_id=Subquery(enrollments.values("pk")[:1]),
            enr_year=Subquery(enrollments.values("academic_year")[:1]),
            enr_year_name=Subquery(enrollments.values("academic_year__name")[:1]),
            enr_class=Subquery(enrollments.values("school_class")[:1]),
            enr_class_name=Subquery(enrollments.values("school_class__name")[:1]),
            enr_level=Subquery(enrollments.values("school_class__level")[:1]),
            enr_level_code=Subquery(enrollments.values("school_class__level__code")[:1]),
            enr_level_name=Subquery(enrollments.values("school_class__level__name")[:1]),
            enr_status=Subquery(enrollments.values("status")[:1]),
        )
        level, school_class = self.uuid_param("level"), self.uuid_param("school_class")
        if level:
            queryset = queryset.filter(enr_level=level)
        if school_class:
            queryset = queryset.filter(enr_class=school_class)
        enrollment_status = params.get("enrollment_status")
        if enrollment_status:
            if enrollment_status not in ENROLLMENT_FILTERS:
                raise serializers.ValidationError({"enrollment_status": ["Unknown enrollment status."]})
            queryset = (
                queryset.filter(enr_id__isnull=True)
                if enrollment_status == "NONE"
                else queryset.filter(enr_status=enrollment_status)
            )
        elif self.request.query_params.get("academic_year"):
            queryset = queryset.filter(enr_id__isnull=False)  # a year filter lists that year's pupils
        return queryset.order_by("last_name", "first_name", "student_number")

    def post(self, request):
        data = StudentInput(data=request.data)
        data.is_valid(raise_exception=True)
        fields = dict(data.validated_data)
        enrollment = fields.pop("enrollment", None)
        if enrollment:
            enrollment = {**enrollment, "school_class": _class_of(enrollment["school_class"], request)}
        student = services.admin_create_student(
            self.membership().school, actor=self.membership(), enrollment=enrollment, **fields
        )
        return Response(StudentAdminSerializer(student).data, status=status.HTTP_201_CREATED)


class StudentDetail(StudentScope, generics.RetrieveAPIView):
    def patch(self, request, pk):
        student = self.student()
        data = StudentUpdate(data=request.data)
        data.is_valid(raise_exception=True)
        student = services.admin_update_student(student, actor=self.membership(), **data.validated_data)
        return Response(StudentAdminSerializer(student).data)


class StudentStatusAction(StudentScope, APIView):
    operation = None  # "archive" | "reactivate", set by as_view()

    def post(self, request, pk):
        handler = services.admin_archive_student if self.operation == "archive" else services.admin_reactivate_student
        return Response(StudentAdminSerializer(handler(self.student(), actor=self.membership())).data)


# -----------------------------------------------------------------------------
# Enrollments
# -----------------------------------------------------------------------------


class StudentEnrollments(StudentScope, generics.ListAPIView):
    """GET: the year-by-year history. POST: enroll in a class."""

    def get_serializer_class(self):
        return EnrollmentAdminSerializer if self.is_admin() else EnrollmentSerializer

    def get_queryset(self):
        return (
            StudentEnrollment.objects.filter(student=self.student())
            .select_related("academic_year", "school_class__level")
            .order_by("-academic_year__start_date")
        )

    def post(self, request, pk):
        student = self.student()
        data = EnrollmentInput(data=request.data)
        data.is_valid(raise_exception=True)
        enrollment = services.admin_enroll_student(
            student,
            _class_of(data.validated_data["school_class"], request),
            actor=self.membership(),
            enrollment_date=data.validated_data.get("enrollment_date"),
        )
        return Response(EnrollmentAdminSerializer(enrollment).data, status=status.HTTP_201_CREATED)


class ChangeClassInput(serializers.Serializer):
    school_class = serializers.UUIDField()


class WithdrawInput(serializers.Serializer):
    end_date = serializers.DateField(required=False, allow_null=True)


class EnrollmentAction(StudentScope, APIView):
    operation = None  # "change-class" | "withdraw"

    def enrollment(self):
        visible = self.visible_students(scope_to_current_school(Student.objects.all(), self.request))
        enrollment = (
            scope_to_current_school(StudentEnrollment.objects.all(), self.request)
            .filter(pk=self.kwargs["pk"], student__in=visible)
            .first()
        )
        if enrollment is None:
            raise Http404
        return enrollment

    def post(self, request, pk):
        enrollment = self.enrollment()
        if self.operation == "change-class":
            data = ChangeClassInput(data=request.data)
            data.is_valid(raise_exception=True)
            enrollment = services.admin_change_class(
                enrollment, _class_of(data.validated_data["school_class"], request), actor=self.membership()
            )
        else:
            data = WithdrawInput(data=request.data)
            data.is_valid(raise_exception=True)
            enrollment = services.admin_withdraw_enrollment(
                enrollment, actor=self.membership(), end_date=data.validated_data.get("end_date")
            )
        return Response(EnrollmentAdminSerializer(enrollment).data)


# -----------------------------------------------------------------------------
# Photo & history
# -----------------------------------------------------------------------------


class StudentPhoto(StudentScope, APIView):
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request, pk):
        student = self.student()
        if not student.photo:
            raise Http404
        response = FileResponse(student.photo.open("rb"), content_type="image/jpeg")
        response["Cache-Control"] = "private, no-store"  # a child's face never sits in a shared cache
        response["X-Content-Type-Options"] = "nosniff"
        return response

    def post(self, request, pk):
        student = services.admin_set_photo(self.student(), request.FILES.get("photo"), actor=self.membership())
        return Response(StudentAdminSerializer(student).data)

    def delete(self, request, pk):
        student = services.admin_remove_photo(self.student(), actor=self.membership())
        return Response(StudentAdminSerializer(student).data)


HISTORY_ACTIONS = {
    "STUDENT_CREATED",
    "STUDENT_UPDATED",
    "STUDENT_ARCHIVED",
    "STUDENT_REACTIVATED",
    "STUDENT_ENROLLED",
    "STUDENT_CLASS_CHANGED",
    "STUDENT_WITHDRAWN",
    "STUDENT_PHOTO_SET",
    "STUDENT_PHOTO_REMOVED",
}


class StudentHistory(StudentScope, APIView):
    """Administrators only: what happened to this student's record and
    schooling (audit trail), newest first. Only the facts needed by the
    screen leave the server (action, date, author, short summary)."""

    def get(self, request, pk):
        from django.core.exceptions import PermissionDenied

        from apps.audit.models import AuditLog

        if not self.is_admin():
            raise PermissionDenied
        student = self.student()
        enrollment_ids = list(student.enrollments.values_list("pk", flat=True))
        rows = (
            AuditLog.objects.filter(school=student.school, action__in=HISTORY_ACTIONS)
            .filter(Q(entity_id=student.pk) | Q(entity_id__in=enrollment_ids))
            .select_related("actor__user")
            .order_by("-created_at")[:100]
        )
        return Response([_history(row) for row in rows])


def _history(row):
    old, new = row.old_data or {}, row.new_data or {}
    if row.action == "STUDENT_CLASS_CHANGED":
        summary = f"{old.get('class_name', '?')} → {new.get('class_name', '?')} ({new.get('academic_year_name', '')})"
    elif row.action in ("STUDENT_ENROLLED", "STUDENT_WITHDRAWN"):
        summary = f"{new.get('class_name', '')} ({new.get('academic_year_name', '')})"
    elif row.action == "STUDENT_UPDATED":
        changed = sorted(k for k in new if new.get(k) != old.get(k))
        summary = ", ".join(changed)
    else:
        summary = ""
    actor = row.actor.user if row.actor_id else None
    return {
        "id": str(row.pk),
        "at": row.created_at,
        "action": row.action,
        "summary": summary,
        "actor": (actor.full_name or actor.username) if actor else "",
    }


urlpatterns = [
    path("students/", StudentListCreate.as_view(), name="students"),
    path("students/<uuid:pk>/", StudentDetail.as_view(), name="student"),
    path("students/<uuid:pk>/archive/", StudentStatusAction.as_view(operation="archive"), name="student-archive"),
    path(
        "students/<uuid:pk>/reactivate/",
        StudentStatusAction.as_view(operation="reactivate"),
        name="student-reactivate",
    ),
    path("students/<uuid:pk>/enrollments/", StudentEnrollments.as_view(), name="student-enrollments"),
    path("students/<uuid:pk>/photo/", StudentPhoto.as_view(), name="student-photo"),
    path("students/<uuid:pk>/history/", StudentHistory.as_view(), name="student-history"),
    path(
        "enrollments/<uuid:pk>/change-class/",
        EnrollmentAction.as_view(operation="change-class"),
        name="enrollment-change-class",
    ),
    path("enrollments/<uuid:pk>/withdraw/", EnrollmentAction.as_view(operation="withdraw"), name="enrollment-withdraw"),
]
