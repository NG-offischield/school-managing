"""Teachers API (spec §6.4) — reads by visibility, writes by administrators
(PySide6 "Gestion académique → Enseignants", ADR 0019).

    GET   /teachers/            ?search= ?status=active|inactive ?category= ?subject=      (admin: all; teacher: self)
    POST  /teachers/            {identity, employee_number, pedagogical_category, primary_subject, …}   (admin)
    GET   /teachers/{id}/                                                                    (visible)
    PATCH /teachers/{id}/       {identity / HR / profile fields}                             (admin)
    POST  /teachers/{id}/deactivate/ | /reactivate/                                          (admin)
    GET   /teachers/{id}/qualifications/                                                     (visible)
    POST  /teachers/{id}/qualifications/  {subject, level?, notes?}                          (admin)
    POST  /teacher-qualifications/{id}/verify/ | /reject/ {reason}                           (admin)
    GET   /teachers/{id}/compatibility/?subject=&level=   verdict of the engine + why        (admin)
    GET   /teachers/{id}/compatibility-rules/             rules of the teacher's category    (admin)
    GET   /teachers/{id}/overrides/   POST {subject, level?, reason, expires_at?}            (admin)

The compatibility verdict always comes from people/compatibility.py; the
client displays it and never decides. Errors: 403 role, 404 out of scope
(another school's teacher, subject, category, level), 409 number / e-mail
taken, already an employee / already qualified, teacher or qualification
still in use; 400 invalid data or rule (incompatible subject, inactive
subject, employment not active…). Lists are paginated by the API.
"""

from django.core.exceptions import PermissionDenied
from django.db.models import Count, Prefetch, Q
from django.http import Http404
from django.urls import path
from django.utils import timezone
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.academics.models import Level, PedagogicalCategory, SubjectCompatibilityRule
from apps.academics.models import Subject as SubjectModel
from common.tenancy import scope_to_current_school

from . import services
from .api import QualificationSerializer, TeacherSerializer, TeacherVisibilityMixin
from .compatibility import evaluate
from .models import (
    CompatibilityOverride,
    CompatibilityResult,
    EmploymentStatus,
    ProfessionalStatus,
    QualificationStatus,
    TeacherProfile,
    TeacherSubjectQualification,
)

LIVE_QUALIFICATIONS = ~Q(status=QualificationStatus.REJECTED)


def _ref(obj, *extra):
    if obj is None:
        return None
    data = {"id": str(obj.pk), "code": obj.code, "name": obj.name}
    for name in extra:
        data[name] = getattr(obj, name)
    return data


# -----------------------------------------------------------------------------
# Serializers
# -----------------------------------------------------------------------------


class TeacherAdminSerializer(serializers.ModelSerializer):
    teacher_number = serializers.CharField(source="employee.employee_number", read_only=True)
    employee = serializers.UUIDField(source="employee_id", read_only=True)  # payroll / remuneration
    membership = serializers.UUIDField(source="employee.membership_id", read_only=True)  # account (ADR 0024)
    account_state = serializers.SerializerMethodField()
    first_name = serializers.CharField(source="employee.membership.user.first_name", read_only=True)
    last_name = serializers.CharField(source="employee.membership.user.last_name", read_only=True)
    email = serializers.CharField(source="employee.membership.user.email", read_only=True)
    phone = serializers.CharField(source="employee.membership.user.phone", read_only=True)
    employment_status = serializers.CharField(source="employee.employment_status", read_only=True)
    hire_date = serializers.DateField(source="employee.hire_date", read_only=True)
    address = serializers.CharField(source="employee.address", read_only=True)
    pedagogical_category = serializers.SerializerMethodField()
    primary_subject = serializers.SerializerMethodField()
    subjects = serializers.SerializerMethodField()
    active = serializers.SerializerMethodField()
    account_activated = serializers.SerializerMethodField()

    class Meta:
        model = TeacherProfile
        fields = [
            "id",
            "employee",
            "membership",
            "account_state",
            "teacher_number",
            "first_name",
            "last_name",
            "email",
            "phone",
            "pedagogical_category",
            "primary_subject",
            "subjects",
            "professional_status",
            "employment_status",
            "active",
            "hire_date",
            "address",
            "qualification_summary",
            "bio",
            "account_activated",
        ]

    def get_pedagogical_category(self, obj):
        return _ref(obj.pedagogical_category)

    def get_primary_subject(self, obj):
        return _ref(obj.primary_subject)

    def get_subjects(self, obj):
        """Codes of the subjects the teacher may teach (not rejected)."""
        rows = getattr(obj, "live_qualifications", None)
        if rows is None:
            rows = obj.qualifications.filter(LIVE_QUALIFICATIONS).select_related("subject")
        return sorted(q.subject.code for q in rows)

    def get_active(self, obj):
        return obj.professional_status == ProfessionalStatus.ACTIVE and (
            obj.employee.employment_status == EmploymentStatus.ACTIVE
        )

    def get_account_state(self, obj):
        """ACTIVE / PENDING_ACTIVATION / NOT_ACTIVATED / DISABLED (ADR 0024)."""
        from apps.accounts.activation import account_state

        return account_state(obj.employee.membership)

    def get_account_activated(self, obj):
        """True once the person has set a password (the account can log in)."""
        return obj.employee.membership.user.has_usable_password()


class TeacherDetailSerializer(TeacherAdminSerializer):
    active_course_count = serializers.SerializerMethodField()
    upcoming_session_count = serializers.SerializerMethodField()

    class Meta(TeacherAdminSerializer.Meta):
        fields = [*TeacherAdminSerializer.Meta.fields, "active_course_count", "upcoming_session_count"]

    def get_active_course_count(self, obj):
        return services._teaching_load(obj)[0]

    def get_upcoming_session_count(self, obj):
        return services._teaching_load(obj)[1]


class QualificationAdminSerializer(serializers.ModelSerializer):
    subject = serializers.SerializerMethodField()
    current_compatibility = serializers.SerializerMethodField()

    class Meta:
        model = TeacherSubjectQualification
        fields = [
            "id",
            "subject",
            "status",
            "verified",
            "verified_at",
            "source",
            "computed_compatibility",
            "current_compatibility",
            "notes",
        ]

    def get_subject(self, obj):
        return _ref(obj.subject) | {"category": obj.subject.category.code if obj.subject.category_id else None}

    def get_current_compatibility(self, obj):
        """What the engine says TODAY (rules or overrides may have changed)."""
        return evaluate(obj.teacher, obj.subject).result


class TeacherInput(serializers.Serializer):
    first_name = serializers.CharField(max_length=120)
    last_name = serializers.CharField(max_length=120)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True, allow_null=True)
    employee_number = serializers.CharField(max_length=50)
    hire_date = serializers.DateField(required=False, allow_null=True)
    address = serializers.CharField(max_length=500, required=False, allow_blank=True, allow_null=True)
    pedagogical_category = serializers.UUIDField()
    primary_subject = serializers.UUIDField()
    qualification_summary = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    bio = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class TeacherUpdate(TeacherInput):
    professional_status = serializers.ChoiceField(choices=ProfessionalStatus.choices, required=False)
    employment_status = serializers.ChoiceField(choices=EmploymentStatus.choices, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, partial=True, **kwargs)


def _scoped(model, pk, request):
    """An object of the CURRENT school (404 otherwise, like a missing id)."""
    found = scope_to_current_school(model.objects.all(), request).filter(pk=pk).first()
    if found is None:
        raise Http404
    return found


def _resolve(data, request):
    resolved = dict(data)
    if "pedagogical_category" in resolved:
        resolved["pedagogical_category"] = _scoped(PedagogicalCategory, resolved["pedagogical_category"], request)
    if "primary_subject" in resolved:
        resolved["primary_subject"] = _scoped(SubjectModel, resolved["primary_subject"], request)
    return resolved


# -----------------------------------------------------------------------------
# Teachers
# -----------------------------------------------------------------------------


class TeacherScope(TeacherVisibilityMixin):
    queryset = TeacherProfile.objects.select_related(
        "employee__membership__user", "pedagogical_category", "primary_subject"
    ).prefetch_related(
        Prefetch(
            "qualifications",
            queryset=TeacherSubjectQualification.objects.filter(LIVE_QUALIFICATIONS).select_related("subject"),
            to_attr="live_qualifications",
        )
    )

    def get_serializer_class(self):
        return TeacherAdminSerializer if self.is_admin() else TeacherSerializer

    def teacher(self):
        found = (
            self.visible_teachers(scope_to_current_school(TeacherProfile.objects.all(), self.request))
            .filter(pk=self.kwargs["pk"])
            .first()
        )
        if found is None:
            raise Http404
        return found

    def require_admin(self):
        if not self.is_admin():
            raise PermissionDenied


class TeacherListCreate(TeacherScope, generics.ListAPIView):
    def restrict(self, queryset):
        queryset = self.visible_teachers(queryset)
        params = self.request.query_params
        search = (params.get("search") or "").strip()
        if search:
            q = Q()
            for lookup in (
                "employee__membership__user__last_name",
                "employee__membership__user__first_name",
                "employee__membership__user__email",
                "employee__employee_number",
            ):
                q |= Q(**{f"{lookup}__icontains": search})
            queryset = queryset.filter(q)
        wanted = params.get("status")
        active = Q(professional_status=ProfessionalStatus.ACTIVE, employee__employment_status=EmploymentStatus.ACTIVE)
        if wanted == "active":
            queryset = queryset.filter(active)
        elif wanted == "inactive":
            queryset = queryset.exclude(active)
        elif wanted:
            raise serializers.ValidationError({"status": ["Use active or inactive."]})
        category = self.uuid_param("category")
        if category:
            queryset = queryset.filter(pedagogical_category_id=category)
        subject = self.uuid_param("subject")
        if subject:
            queryset = queryset.filter(
                pk__in=TeacherSubjectQualification.objects.filter(LIVE_QUALIFICATIONS, subject_id=subject).values(
                    "teacher_id"
                )
            )
        return queryset.order_by("employee__membership__user__last_name", "employee__membership__user__first_name")

    def post(self, request):
        data = TeacherInput(data=request.data)
        data.is_valid(raise_exception=True)
        teacher = services.admin_create_teacher(
            self.membership().school, actor=self.membership(), **_resolve(data.validated_data, request)
        )
        return Response(TeacherDetailSerializer(teacher).data, status=status.HTTP_201_CREATED)


class TeacherDetail(TeacherScope, generics.RetrieveAPIView):
    def get_serializer_class(self):
        return TeacherDetailSerializer if self.is_admin() else TeacherSerializer

    def patch(self, request, pk):
        teacher = self.teacher()
        data = TeacherUpdate(data=request.data)
        data.is_valid(raise_exception=True)
        teacher = services.admin_update_teacher(
            teacher, actor=self.membership(), **_resolve(data.validated_data, request)
        )
        return Response(TeacherDetailSerializer(teacher).data)


class TeacherActivation(TeacherScope, APIView):
    active = None  # set by as_view()

    def post(self, request, pk):
        teacher = services.admin_set_teacher_active(self.teacher(), self.active, actor=self.membership())
        return Response(TeacherDetailSerializer(teacher).data)


# -----------------------------------------------------------------------------
# Qualifications, compatibility, overrides
# -----------------------------------------------------------------------------


class QualificationInput(serializers.Serializer):
    subject = serializers.UUIDField()
    level = serializers.UUIDField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class TeacherQualifications(TeacherScope, generics.ListAPIView):
    def get_serializer_class(self):
        return QualificationAdminSerializer if self.is_admin() else QualificationSerializer

    def get_queryset(self):
        # Reading keeps its historical contract: an invisible teacher's list is
        # simply empty (writes below still answer 404).
        visible = self.visible_teachers(scope_to_current_school(TeacherProfile.objects.all(), self.request))
        return (
            TeacherSubjectQualification.objects.filter(teacher_id=self.kwargs["pk"], teacher__in=visible)
            .select_related("subject__category", "teacher")
            .order_by("subject__name")
        )

    def post(self, request, pk):
        teacher = self.teacher()
        data = QualificationInput(data=request.data)
        data.is_valid(raise_exception=True)
        level = data.validated_data.get("level")
        qualification = services.admin_add_qualification(
            teacher,
            _scoped(SubjectModel, data.validated_data["subject"], request),
            actor=self.membership(),
            level=_scoped(Level, level, request) if level else None,
            notes=data.validated_data.get("notes"),
        )
        return Response(QualificationAdminSerializer(qualification).data, status=status.HTTP_201_CREATED)


class RejectInput(serializers.Serializer):
    reason = serializers.CharField()


class QualificationAction(TeacherScope, APIView):
    operation = None  # "verify" | "reject"

    def post(self, request, pk):
        qualification = _scoped(TeacherSubjectQualification, pk, request)
        if self.operation == "verify":
            qualification = services.admin_verify_qualification(qualification, actor=self.membership())
        else:
            data = RejectInput(data=request.data)
            data.is_valid(raise_exception=True)
            qualification = services.admin_reject_qualification(
                qualification, actor=self.membership(), reason=data.validated_data["reason"]
            )
        return Response(QualificationAdminSerializer(qualification).data)


def _rule_payload(rule):
    return {
        "id": str(rule.pk),
        "category": rule.pedagogical_category.code,
        "subject": _ref(rule.subject),
        "level": _ref(rule.level),
        "compatible": rule.compatible,
        "requires_admin_review": rule.requires_admin_review,
        "priority": rule.priority,
    }


def _override_payload(override, now=None):
    approver = override.approved_by.user
    return {
        "id": str(override.pk),
        "subject": _ref(override.subject),
        "level": _ref(override.level),
        "reason": override.reason,
        "approved_by": approver.full_name or approver.username,
        "created_at": override.created_at,
        "expires_at": override.expires_at,
        "active": override.is_active(now),
    }


class TeacherCompatibility(TeacherScope, APIView):
    """GET ?subject=&level= : the engine's verdict and WHY (reason code,
    applicable rule or override). The desktop only displays it."""

    def get(self, request, pk):
        self.require_admin()
        teacher = self.teacher()
        subject_id = self.uuid_param("subject")
        if subject_id is None:
            raise serializers.ValidationError({"subject": ["This query parameter is required."]})
        subject = _scoped(SubjectModel, subject_id, request)
        level_id = self.uuid_param("level")
        level = _scoped(Level, level_id, request) if level_id else None
        evaluation = evaluate(teacher, subject, level)
        if evaluation.override is not None:
            reason = "override"
        elif evaluation.rule is not None:
            reason = {
                CompatibilityResult.COMPATIBLE: "rule_compatible",
                CompatibilityResult.REQUIRES_REVIEW: "rule_review",
                CompatibilityResult.INCOMPATIBLE: "rule_incompatible",
            }[evaluation.result]
        elif subject.pk == teacher.primary_subject_id:
            reason = "primary_subject"
        elif evaluation.result == CompatibilityResult.COMPATIBLE:
            reason = "same_category"
        else:
            reason = "no_rule"
        existing = teacher.qualifications.filter(subject=subject).first()
        return Response(
            {
                "subject": _ref(subject),
                "level": _ref(level),
                "result": evaluation.result,
                "reason": reason,
                "rule": _rule_payload(evaluation.rule) if evaluation.rule else None,
                "override": _override_payload(evaluation.override) if evaluation.override else None,
                "qualification_status": existing.status if existing else None,
            }
        )


class TeacherRules(TeacherScope, APIView):
    def get(self, request, pk):
        self.require_admin()
        teacher = self.teacher()
        rules = (
            SubjectCompatibilityRule.objects.filter(
                school=teacher.school, pedagogical_category=teacher.pedagogical_category
            )
            .select_related("pedagogical_category", "subject", "level")
            .order_by("subject__name", "level__order_index", "-priority")
        )
        return Response([_rule_payload(rule) for rule in rules])


class OverrideInput(serializers.Serializer):
    subject = serializers.UUIDField()
    level = serializers.UUIDField(required=False, allow_null=True)
    reason = serializers.CharField()
    expires_at = serializers.DateTimeField(required=False, allow_null=True)


class TeacherOverrides(TeacherScope, APIView):
    def get(self, request, pk):
        self.require_admin()
        now = timezone.now()
        rows = (
            CompatibilityOverride.objects.filter(teacher=self.teacher())
            .select_related("subject", "level", "approved_by__user")
            .order_by("-created_at")
        )
        return Response([_override_payload(row, now) for row in rows])

    def post(self, request, pk):
        teacher = self.teacher()
        data = OverrideInput(data=request.data)
        data.is_valid(raise_exception=True)
        level = data.validated_data.get("level")
        override = services.admin_grant_override(
            teacher,
            _scoped(SubjectModel, data.validated_data["subject"], request),
            actor=self.membership(),
            reason=data.validated_data["reason"],
            level=_scoped(Level, level, request) if level else None,
            expires_at=data.validated_data.get("expires_at"),
        )
        return Response(_override_payload(override), status=status.HTTP_201_CREATED)


def teacher_counts(school):
    """Active teachers by pedagogical category (dashboard)."""
    active = Q(professional_status=ProfessionalStatus.ACTIVE, employee__employment_status=EmploymentStatus.ACTIVE)
    return (
        TeacherProfile.objects.filter(school=school)
        .filter(active)
        .values("pedagogical_category__code", "pedagogical_category__name")
        .annotate(count=Count("id"))
        .order_by("pedagogical_category__name")
    )


urlpatterns = [
    path("teachers/", TeacherListCreate.as_view(), name="teachers"),
    path("teachers/<uuid:pk>/", TeacherDetail.as_view(), name="teacher"),
    path("teachers/<uuid:pk>/deactivate/", TeacherActivation.as_view(active=False), name="teacher-deactivate"),
    path("teachers/<uuid:pk>/reactivate/", TeacherActivation.as_view(active=True), name="teacher-reactivate"),
    path("teachers/<uuid:pk>/qualifications/", TeacherQualifications.as_view(), name="teacher-qualifications"),
    path("teachers/<uuid:pk>/compatibility/", TeacherCompatibility.as_view(), name="teacher-compatibility"),
    path("teachers/<uuid:pk>/compatibility-rules/", TeacherRules.as_view(), name="teacher-compatibility-rules"),
    path("teachers/<uuid:pk>/overrides/", TeacherOverrides.as_view(), name="teacher-overrides"),
    path(
        "teacher-qualifications/<uuid:pk>/verify/",
        QualificationAction.as_view(operation="verify"),
        name="qualification-verify",
    ),
    path(
        "teacher-qualifications/<uuid:pk>/reject/",
        QualificationAction.as_view(operation="reject"),
        name="qualification-reject",
    ),
]
