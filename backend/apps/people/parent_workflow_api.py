"""Parent registration and linking API (spec §6.3, §6.5; ADR 0026).

Public (anonymous, throttled "auth-registration"):
    POST /registrations/parent/   {first_name, last_name, email, password, phone?, school_code?}
                                  -> 202, the SAME answer whatever happens (no enumeration)
The applicant (logged in, membership still PENDING allowed):
    GET  /registrations/me/       state of my registration(s)
Parent (ACTIVE membership, role PARENT):
    GET/POST /parents/link-requests/        {student_number, date_of_birth, relationship_type,
                                             document_type, document_number}  (number -> HMAC only)
    POST /parents/link-requests/{id}/sponsor/   {code}      second parent: sponsor's code
    POST /parents/link-requests/{id}/cancel/
    POST /parents/children/{student}/sponsor-codes/          verified parent: code shown ONCE
    GET  /parents/children/{student}/teachers/               teachers of my verified child
Administration (ADMIN / SUPER_ADMIN; another school = 404):
    GET  /admin/registrations/?status=   GET …/{id}/   POST …/{id}/approve/ | /reject/ {reason}
    GET  /admin/link-requests/?status=   GET …/{id}/
    POST /admin/link-requests/{id}/verify-identity/   {document_type, document_number}
    POST /admin/link-requests/{id}/student-approval/  {decision, note?}
    POST /admin/link-requests/{id}/approve/   {can_pay, can_view_financial_data, can_receive_notifications,
                                               can_submit_complaints}
    POST /admin/link-requests/{id}/reject/    {reason}

Never returned: passwords, document numbers or their hashes, sponsor codes
(except once, to their issuer).
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.urls import path
from django.utils.decorators import method_decorator
from rest_framework import generics, serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.services import ClientContext
from apps.gradebook.models import Course
from common.permissions import ADMIN_ROLES, HasSchoolRole
from common.tenancy import scope_to_current_school
from common.views import SchoolScopedMixin

from . import parent_workflow as workflow
from .models import (
    DocumentType,
    EnrollmentStatus,
    ParentStudentLinkRequest,
    RegistrationRequest,
    RelationshipType,
    Student,
    StudentApproval,
)

# =============================================================================
# Serializers (what each audience may see)
# =============================================================================


def _student_ref(student):
    return {"id": str(student.pk), "name": student.full_name, "student_number": student.student_number}


def request_data(request, *, admin=False):
    identity = request.identity_verification
    data = {
        "id": str(request.pk),
        "student": _student_ref(request.student),
        "relationship_type": request.relationship_type,
        "status": request.status,
        "student_approval_status": request.student_approval_status,
        "identity_status": identity.status,
        "identity_method": identity.method,
        "document_type": identity.document_type,
        "sponsored": request.sponsor_challenge_verified,
        "created_at": request.created_at,
        "decided_at": request.decided_at,
        "decision_reason": request.decision_reason,
    }
    if admin:
        user = request.parent.membership.user
        enrollment = (
            request.student.enrollments.filter(status=EnrollmentStatus.ACTIVE).select_related("school_class").first()
        )
        data.update(
            parent={"id": str(request.parent_id), "name": user.full_name, "email": user.email, "phone": user.phone},
            class_name=enrollment.school_class.name if enrollment else None,
            identity_failed_checks=identity.failed_checks,
            student_approval_note=request.student_approval_note,
            sponsor_name=request.sponsor_parent.membership.user.full_name if request.sponsor_parent_id else None,
            initiated_by=request.initiated_by,
        )
    return data


def registration_data(request):
    return {
        "id": str(request.pk),
        "status": request.status,
        "applicant_name": request.applicant_name,
        "applicant_email": request.applicant_email,
        "applicant_phone": request.applicant_phone,
        "school_name": request.school.name,
        "submitted_at": request.submitted_at,
        "reviewed_at": request.reviewed_at,
        "rejection_reason": request.rejection_reason,
    }


class RowsSerializer(serializers.BaseSerializer):
    def to_representation(self, instance):
        return self.context["render"](instance)


# =============================================================================
# Public registration
# =============================================================================


class RegistrationInput(serializers.Serializer):
    first_name = serializers.CharField(max_length=120)
    last_name = serializers.CharField(max_length=120)
    email = serializers.EmailField()
    # trim_whitespace=False: spaces can be part of a password.
    password = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True)
    school_code = serializers.CharField(max_length=40, required=False, allow_blank=True)


class ParentRegistration(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth-registration"

    def post(self, request):
        data = RegistrationInput(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            workflow.register_parent(**data.validated_data, ctx=ClientContext.from_request(request))
        except DjangoValidationError as exc:
            if exc.error_list[0].code in ("name_required", "email_required"):
                raise
            # The server's password rules, reported on the field (like activation).
            raise serializers.ValidationError({"password": exc.messages}) from None
        return Response(
            {"status": "RECEIVED", "message": "Demande enregistrée : l'établissement la validera."},
            status=status.HTTP_202_ACCEPTED,
        )


class MyRegistrations(APIView):
    """Readable while the membership is still PENDING (no active school yet)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = RegistrationRequest.objects.filter(user=request.user).select_related("school")
        return Response([registration_data(r) for r in rows])


# =============================================================================
# Parent side
# =============================================================================


class LinkRequestInput(serializers.Serializer):
    student_number = serializers.CharField(max_length=50)
    date_of_birth = serializers.DateField()
    relationship_type = serializers.ChoiceField(choices=RelationshipType.choices)
    document_type = serializers.ChoiceField(choices=DocumentType.choices)
    document_number = serializers.CharField(max_length=60, write_only=True)


class ParentLinkRequests(SchoolScopedMixin, generics.ListAPIView):
    queryset = ParentStudentLinkRequest.objects.select_related("student", "identity_verification").order_by(
        "-created_at"
    )

    def restrict(self, queryset):
        return queryset.filter(parent__membership=self.membership())

    def get_serializer(self, *args, **kwargs):
        return RowsSerializer(*args, context={"render": request_data}, **kwargs)

    def post(self, request):
        data = LinkRequestInput(data=request.data)
        data.is_valid(raise_exception=True)
        created = workflow.request_link(self.membership(), **data.validated_data)
        return Response(request_data(created), status=status.HTTP_201_CREATED)


class OwnRequestMixin(SchoolScopedMixin):
    def own(self, pk):
        queryset = scope_to_current_school(ParentStudentLinkRequest.objects.all(), self.request)
        return get_object_or_404(queryset, pk=pk, parent__membership=self.membership())


class CodeInput(serializers.Serializer):
    code = serializers.CharField(max_length=20, write_only=True)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class LinkRequestSponsor(OwnRequestMixin, APIView):
    """Not in the request transaction: failed attempts must stay counted."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth-activation"

    def post(self, request, pk):
        data = CodeInput(data=request.data)
        data.is_valid(raise_exception=True)
        updated = workflow.sponsor_link_request(
            self.own(pk),
            membership=self.membership(),
            code=data.validated_data["code"],
            ctx=ClientContext.from_request(request),
        )
        return Response(request_data(updated))


class LinkRequestCancel(OwnRequestMixin, APIView):
    def post(self, request, pk):
        return Response(request_data(workflow.cancel_link_request(self.own(pk), membership=self.membership())))


class ChildMixin(SchoolScopedMixin):
    def child(self, pk):
        """A pupil of the current school to whom the caller is a VERIFIED parent (else 404)."""
        queryset = scope_to_current_school(Student.objects.all(), self.request)
        return get_object_or_404(
            queryset,
            pk=pk,
            parent_links__parent__membership=self.membership(),
            parent_links__active=True,
            parent_links__identity_verified=True,
        )


class SponsorCodes(ChildMixin, APIView):
    def post(self, request, pk):
        challenge, code = workflow.create_sponsor_code(
            self.membership(), self.child(pk), ctx=ClientContext.from_request(request)
        )
        response = Response({"code": code, "expires_at": challenge.expires_at}, status=status.HTTP_201_CREATED)
        response["Cache-Control"] = "no-store"
        return response


class ChildTeachers(ChildMixin, APIView):
    """Teachers of my verified child's current courses: who a parent may
    write to (parent–teacher conversation)."""

    def get(self, request, pk):
        student = self.child(pk)
        courses = (
            Course.objects.filter(
                active=True,
                school_class__enrollments__student=student,
                school_class__enrollments__status=EnrollmentStatus.ACTIVE,
            )
            .select_related("teacher__employee__membership__user", "subject")
            .order_by("subject__code")
        )
        teachers = {}
        for course in courses:
            membership = course.teacher.employee.membership
            entry = teachers.setdefault(
                membership.pk, {"member": str(membership.pk), "name": membership.user.full_name, "subjects": []}
            )
            entry["subjects"].append(course.subject.code)
        return Response(list(teachers.values()))


# =============================================================================
# Administration
# =============================================================================


class AdminMixin(SchoolScopedMixin):
    permission_classes = [HasSchoolRole]
    required_roles = ADMIN_ROLES


class AdminRegistrations(AdminMixin, generics.ListAPIView):
    queryset = RegistrationRequest.objects.select_related("school").order_by("-submitted_at")

    def restrict(self, queryset):
        wanted = self.request.query_params.get("status")
        search = (self.request.query_params.get("search") or "").strip()
        if wanted:
            queryset = queryset.filter(status=wanted)
        if search:
            queryset = queryset.filter(Q(applicant_name__icontains=search) | Q(applicant_email__icontains=search))
        return queryset

    def get_serializer(self, *args, **kwargs):
        return RowsSerializer(*args, context={"render": registration_data}, **kwargs)


class AdminRegistrationMixin(AdminMixin):
    def registration(self, pk):
        return get_object_or_404(scope_to_current_school(RegistrationRequest.objects.all(), self.request), pk=pk)


class AdminRegistrationDetail(AdminRegistrationMixin, APIView):
    def get(self, request, pk):
        return Response(registration_data(self.registration(pk)))


class AdminRegistrationApprove(AdminRegistrationMixin, APIView):
    def post(self, request, pk):
        return Response(
            registration_data(workflow.approve_registration(self.registration(pk), actor=self.membership()))
        )


class ReasonInput(serializers.Serializer):
    reason = serializers.CharField(max_length=1000)


class AdminRegistrationReject(AdminRegistrationMixin, APIView):
    def post(self, request, pk):
        data = ReasonInput(data=request.data)
        data.is_valid(raise_exception=True)
        rejected = workflow.reject_registration(
            self.registration(pk), actor=self.membership(), reason=data.validated_data["reason"]
        )
        return Response(registration_data(rejected))


class AdminLinkRequests(AdminMixin, generics.ListAPIView):
    queryset = ParentStudentLinkRequest.objects.select_related(
        "student", "identity_verification", "parent__membership__user", "sponsor_parent__membership__user"
    ).order_by("-created_at")

    def restrict(self, queryset):
        wanted = self.request.query_params.get("status")
        search = (self.request.query_params.get("search") or "").strip()
        if wanted:
            queryset = queryset.filter(status=wanted)
        if search:
            queryset = queryset.filter(
                Q(student__last_name__icontains=search)
                | Q(student__first_name__icontains=search)
                | Q(parent__membership__user__last_name__icontains=search)
            )
        return queryset

    def get_serializer(self, *args, **kwargs):
        return RowsSerializer(*args, context={"render": lambda r: request_data(r, admin=True)}, **kwargs)


class AdminLinkMixin(AdminMixin):
    def link_request(self, pk):
        return get_object_or_404(scope_to_current_school(ParentStudentLinkRequest.objects.all(), self.request), pk=pk)


class AdminLinkDetail(AdminLinkMixin, APIView):
    def get(self, request, pk):
        return Response(request_data(self.link_request(pk), admin=True))


class IdentityInput(serializers.Serializer):
    document_type = serializers.ChoiceField(choices=DocumentType.choices)
    document_number = serializers.CharField(max_length=60, write_only=True)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class AdminLinkVerifyIdentity(AdminLinkMixin, APIView):
    """Not in the request transaction: a mismatch must stay counted."""

    def post(self, request, pk):
        data = IdentityInput(data=request.data)
        data.is_valid(raise_exception=True)
        checked = workflow.check_identity(self.link_request(pk), actor=self.membership(), **data.validated_data)
        return Response(request_data(checked, admin=True))


class ApprovalInput(serializers.Serializer):
    decision = serializers.ChoiceField(
        choices=[StudentApproval.APPROVED, StudentApproval.REJECTED, StudentApproval.NOT_REQUIRED]
    )
    note = serializers.CharField(max_length=1000, required=False, allow_blank=True)


class AdminLinkStudentApproval(AdminLinkMixin, APIView):
    def post(self, request, pk):
        data = ApprovalInput(data=request.data)
        data.is_valid(raise_exception=True)
        recorded = workflow.record_student_approval(
            self.link_request(pk), actor=self.membership(), **data.validated_data
        )
        return Response(request_data(recorded, admin=True))


class RightsInput(serializers.Serializer):
    can_pay = serializers.BooleanField(default=False)
    can_view_financial_data = serializers.BooleanField(default=False)
    can_receive_notifications = serializers.BooleanField(default=True)
    can_submit_complaints = serializers.BooleanField(default=True)


class AdminLinkApprove(AdminLinkMixin, APIView):
    def post(self, request, pk):
        data = RightsInput(data=request.data)
        data.is_valid(raise_exception=True)
        approved = workflow.approve_link_request(self.link_request(pk), actor=self.membership(), **data.validated_data)
        return Response(request_data(approved, admin=True))


class AdminLinkReject(AdminLinkMixin, APIView):
    def post(self, request, pk):
        data = ReasonInput(data=request.data)
        data.is_valid(raise_exception=True)
        rejected = workflow.reject_link_request(
            self.link_request(pk), actor=self.membership(), reason=data.validated_data["reason"]
        )
        return Response(request_data(rejected, admin=True))


urlpatterns = [
    path("registrations/parent/", ParentRegistration.as_view(), name="parent-registration"),
    path("registrations/me/", MyRegistrations.as_view()),
    path("parents/link-requests/", ParentLinkRequests.as_view()),
    path("parents/link-requests/<uuid:pk>/sponsor/", LinkRequestSponsor.as_view()),
    path("parents/link-requests/<uuid:pk>/cancel/", LinkRequestCancel.as_view()),
    path("parents/children/<uuid:pk>/sponsor-codes/", SponsorCodes.as_view()),
    path("parents/children/<uuid:pk>/teachers/", ChildTeachers.as_view()),
    path("admin/registrations/", AdminRegistrations.as_view()),
    path("admin/registrations/<uuid:pk>/", AdminRegistrationDetail.as_view()),
    path("admin/registrations/<uuid:pk>/approve/", AdminRegistrationApprove.as_view()),
    path("admin/registrations/<uuid:pk>/reject/", AdminRegistrationReject.as_view()),
    path("admin/link-requests/", AdminLinkRequests.as_view()),
    path("admin/link-requests/<uuid:pk>/", AdminLinkDetail.as_view()),
    path("admin/link-requests/<uuid:pk>/verify-identity/", AdminLinkVerifyIdentity.as_view()),
    path("admin/link-requests/<uuid:pk>/student-approval/", AdminLinkStudentApproval.as_view()),
    path("admin/link-requests/<uuid:pk>/approve/", AdminLinkApprove.as_view()),
    path("admin/link-requests/<uuid:pk>/reject/", AdminLinkReject.as_view()),
]
