"""Parent registration and verified parent–student linking (ADR 0026).

Every decision is taken here, on the server; the apps only send requests.

Registration (spec §6.3)
    register_parent      public: User (password chosen by the parent, Django
                         validators, Argon2) + membership PENDING + request.
                         Same answer whether or not the e-mail is already used
                         (no account enumeration).
    approve / reject     administration: membership ACTIVE + role PARENT +
                         ParentProfile, or rejected (account deactivated).

Linking (spec §6.5, §9 "a verified workflow, not a name match")
    request_link         a parent names a pupil by number + date of birth (both
                         must match: no browsing of pupils) and gives the type
                         and number of their identity document — only an HMAC
                         of the number is stored.
    check_identity       at the school, the administration types the number of
                         the physical document: HMACs compared (3 misses ->
                         identity rejected).
    record_student_approval  the pupil's designation of the parent, recorded by
                         the administration (pupils have no account), or "not
                         required".
    create_sponsor_code / sponsor_link_request
                         a VERIFIED parent of the pupil issues a short-lived
                         single-use code in their app and hands it over in
                         person; the second parent enters it in their request
                         (identity method SPONSOR_2FA).
    approve_link_request final administrative decision: identity verified +
                         pupil approval given (or not required) -> VERIFIED
                         ParentStudent link with its rights; a sponsored parent
                         never gets more financial rights than the sponsor.
"""

import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import password_validation
from django.contrib.auth.hashers import make_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import (
    ChallengePurpose,
    MembershipRole,
    MembershipStatus,
    Role,
    RoleCode,
    SchoolMembership,
    SecurityEventType,
    SecuritySeverity,
    User,
    VerificationChallenge,
)
from apps.accounts.services import record_security_event
from apps.accounts.tokens import hash_token
from apps.audit.models import AuditLayer
from apps.audit.services import record_audit
from apps.core.models import School
from common.permissions import ADMIN_ROLES, require_role

from . import services as people
from .models import (
    DocumentType,
    IdentityMethod,
    IdentityStatus,
    IdentityVerification,
    LinkInitiator,
    LinkRequestStatus,
    ParentStudent,
    ParentStudentLinkRequest,
    RegistrationRequest,
    RegistrationStatus,
    RelationshipType,
    Student,
    StudentApproval,
    VerificationMethod,
)

SPONSOR_CODE_LIFETIME = timedelta(minutes=10)
SPONSOR_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"  # no 0/O, 1/I/L: read aloud safely
MAX_IDENTITY_MISMATCHES = 3


def _reason(reason):
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("A reason is required.", code="reason_required")
    return reason


def document_hash(number):
    """HMAC-SHA256 (SECRET_KEY) of the normalised document number: the
    number itself is never stored and the hash is useless without the key."""
    normalised = "".join(ch for ch in (number or "").upper() if ch.isalnum())
    if len(normalised) < 4:
        raise ValidationError("A valid document number is required.", code="document_number_invalid")
    return hmac.new(settings.SECRET_KEY.encode(), normalised.encode(), hashlib.sha256).hexdigest()


def _audit(action, actor, entity, **data):
    record_audit(action, actor=actor, entity=entity, new=data, layer=AuditLayer.ADMINISTRATIVE)


# =============================================================================
# Registration
# =============================================================================


def _school(school_code):
    schools = School.objects.filter(status="ACTIVE")
    if school_code:
        return schools.filter(code__iexact=school_code.strip()).first()
    # V1 runs ONE school: without a code, that school (if it is the only one).
    return schools.first() if schools.count() == 1 else None


@transaction.atomic
def register_parent(*, first_name, last_name, email, password, phone=None, school_code=None, ctx=None):
    """Returns the RegistrationRequest, or None when nothing was created
    (unknown school, e-mail already used). The API answers the same way in
    every case, so the existence of an account is never revealed."""
    first_name, last_name = (first_name or "").strip(), (last_name or "").strip()
    email = (email or "").strip().lower()
    if not first_name or not last_name:
        raise ValidationError("First and last name are required.", code="name_required")
    if "@" not in email:
        raise ValidationError("A valid e-mail address is required.", code="email_required")
    candidate = User(username=email, email=email, first_name=first_name, last_name=last_name)
    password_validation.validate_password(password, candidate)  # raised before any lookup: no oracle
    school = _school(school_code)
    if school is None:
        make_password(password)  # same cost as a real registration: no timing oracle
        return None
    if User.objects.filter(email__iexact=email).exists() or User.objects.filter(username__iexact=email).exists():
        make_password(password)
        record_security_event(
            SecurityEventType.PARENT_REGISTRATION_DUPLICATE, school=school, ctx=ctx, severity=SecuritySeverity.WARNING
        )
        return None
    user = User.objects.create_user(
        username=email, email=email, password=password, first_name=first_name, last_name=last_name, phone=phone
    )
    membership = SchoolMembership.objects.create(
        school=school, user=user, status=MembershipStatus.PENDING, is_primary_school=True
    )
    request = RegistrationRequest.objects.create(
        school=school,
        user=user,
        membership=membership,
        applicant_name=f"{first_name} {last_name}",
        applicant_email=email,
        applicant_phone=(phone or "").strip() or None,
        submitted_at=timezone.now(),
    )
    record_security_event(
        SecurityEventType.PARENT_REGISTRATION_SUBMITTED,
        user=user,
        school=school,
        ctx=ctx,
        after_commit=True,
        registration_id=str(request.pk),
    )
    return request


def _pending_registration(request):
    request = RegistrationRequest.objects.select_for_update().get(pk=request.pk)
    if request.status != RegistrationStatus.PENDING:
        raise ValidationError("This registration was already decided.", code="registration_not_pending")
    return request


@transaction.atomic
def approve_registration(request, *, actor):
    require_role(actor, ADMIN_ROLES, school=request.school)
    request = _pending_registration(request)
    membership = SchoolMembership.objects.select_for_update().get(pk=request.membership_id)
    membership.status, membership.joined_at = MembershipStatus.ACTIVE, timezone.now()
    membership.save(update_fields=["status", "joined_at", "updated_at"])
    MembershipRole.objects.get_or_create(
        membership=membership, role=Role.objects.get(code=RoleCode.PARENT), defaults={"assigned_by": actor}
    )
    if not hasattr(membership, "parent_profile"):
        people.create_parent_profile(membership)
    request.status, request.reviewed_at, request.reviewed_by = RegistrationStatus.APPROVED, timezone.now(), actor
    request.save(update_fields=["status", "reviewed_at", "reviewed_by", "updated_at"])
    _audit("PARENT_REGISTRATION_APPROVED", actor, request, membership=str(membership.pk))
    return request


@transaction.atomic
def reject_registration(request, *, actor, reason):
    require_role(actor, ADMIN_ROLES, school=request.school)
    reason = _reason(reason)
    request = _pending_registration(request)
    membership = SchoolMembership.objects.select_for_update().get(pk=request.membership_id)
    membership.status, membership.left_at = MembershipStatus.LEFT, timezone.now()
    membership.save(update_fields=["status", "left_at", "updated_at"])
    user = membership.user
    if not user.memberships.exclude(pk=membership.pk).filter(status=MembershipStatus.ACTIVE).exists():
        user.is_active = False
        user.save(update_fields=["is_active", "updated_at"])
    request.status, request.reviewed_at, request.reviewed_by = RegistrationStatus.REJECTED, timezone.now(), actor
    request.rejection_reason = reason
    request.save(update_fields=["status", "reviewed_at", "reviewed_by", "rejection_reason", "updated_at"])
    _audit("PARENT_REGISTRATION_REJECTED", actor, request, reason=reason)
    return request


# =============================================================================
# Link requests (parent side)
# =============================================================================


def _parent_profile(membership):
    """The calling parent: ACTIVE membership with the PARENT role."""
    if (
        membership is None
        or membership.status != MembershipStatus.ACTIVE
        or RoleCode.PARENT not in membership.role_codes()
        or not hasattr(membership, "parent_profile")
    ):
        raise PermissionDenied("Only an approved parent account can do this.")
    return membership.parent_profile


@transaction.atomic
def request_link(membership, *, student_number, date_of_birth, relationship_type, document_type, document_number):
    parent = _parent_profile(membership)
    if relationship_type not in RelationshipType.values:
        raise ValidationError("Invalid relationship.", code="invalid_choice")
    if document_type not in DocumentType.values:
        raise ValidationError("Invalid document type.", code="invalid_choice")
    reference = document_hash(document_number)
    # Number AND date of birth must match (the same answer otherwise): a parent
    # cannot browse or confirm pupils of the school.
    student = Student.objects.filter(
        school=membership.school,
        student_number__iexact=(student_number or "").strip(),
        date_of_birth=date_of_birth,
    ).first()
    if student is None:
        raise ValidationError("No pupil matches this information.", code="student_not_found")
    if ParentStudent.objects.filter(parent=parent, student=student, identity_verified=True, active=True).exists():
        raise ValidationError("You are already linked to this pupil.", code="already_linked")
    if ParentStudentLinkRequest.objects.filter(
        parent=parent, student=student, status=LinkRequestStatus.PENDING
    ).exists():
        raise ValidationError("A request is already in progress for this pupil.", code="link_request_pending")
    identity = IdentityVerification.objects.create(
        school=membership.school,
        membership=membership,
        method=IdentityMethod.ID_DOCUMENT,
        document_type=document_type,
        document_reference_hash=reference,
    )
    request = ParentStudentLinkRequest.objects.create(
        school=membership.school,
        parent=parent,
        student=student,
        relationship_type=relationship_type,
        initiated_by=LinkInitiator.PARENT,
        identity_verification=identity,
    )
    _audit("LINK_REQUEST_CREATED", membership, request, student=str(student.pk))
    return request


def _own_pending(request, membership):
    request = ParentStudentLinkRequest.objects.select_for_update().get(pk=request.pk)
    if request.parent.membership_id != membership.pk:
        raise PermissionDenied("Not your request.")
    if request.status != LinkRequestStatus.PENDING:
        raise ValidationError("This request is no longer in progress.", code="request_not_pending")
    return request


@transaction.atomic
def cancel_link_request(request, *, membership):
    request = _own_pending(request, membership)
    request.status, request.decided_at = LinkRequestStatus.CANCELLED, timezone.now()
    request.save(update_fields=["status", "decided_at", "updated_at"])
    _audit("LINK_REQUEST_CANCELLED", membership, request)
    return request


def _verified_link(parent, student):
    return ParentStudent.objects.filter(parent=parent, student=student, identity_verified=True, active=True).first()


def new_sponsor_code():
    raw = "".join(secrets.choice(SPONSOR_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def _sponsor_hash(code):
    return hash_token("".join(ch for ch in (code or "").upper() if ch.isalnum()))


@transaction.atomic
def create_sponsor_code(membership, student, *, ctx=None):
    """A VERIFIED parent of the pupil vouches for a second parent / tutor:
    returns (challenge, code) — the code is shown once, in the sponsor's app."""
    parent = _parent_profile(membership)
    if student.school_id != membership.school_id or _verified_link(parent, student) is None:
        raise PermissionDenied("Only a verified parent of this pupil can sponsor.")
    now = timezone.now()
    VerificationChallenge.objects.filter(
        user=membership.user, purpose=ChallengePurpose.LINK_SPONSOR, target_id=student.pk, consumed_at__isnull=True
    ).update(consumed_at=now)  # a new code replaces the previous one
    code = new_sponsor_code()
    challenge = VerificationChallenge.objects.create(
        school=membership.school,
        user=membership.user,
        purpose=ChallengePurpose.LINK_SPONSOR,
        target_id=student.pk,
        challenge_hash=_sponsor_hash(code),
        created_at=now,
        expires_at=now + SPONSOR_CODE_LIFETIME,
    )
    record_security_event(
        SecurityEventType.LINK_SPONSOR_CODE_ISSUED,
        user=membership.user,
        school=membership.school,
        ctx=ctx,
        after_commit=True,
        challenge_id=str(challenge.pk),
    )
    return challenge, code


def sponsor_link_request(request, *, membership, code, ctx=None):
    """The second parent enters the sponsor's code. A wrong code counts an
    attempt on every live challenge of this pupil (max 5 each)."""
    with transaction.atomic():
        request = _own_pending(request, membership)
        if request.sponsor_challenge_verified:
            raise ValidationError("This request is already sponsored.", code="already_sponsored")
        now = timezone.now()
        live = list(
            VerificationChallenge.objects.select_for_update()
            .filter(
                school=request.school,
                purpose=ChallengePurpose.LINK_SPONSOR,
                target_id=request.student_id,
                consumed_at__isnull=True,
                expires_at__gt=now,
            )
            .select_related("user")
        )
        presented = _sponsor_hash(code)
        match = next(
            (c for c in live if c.usable(now) and hmac.compare_digest(c.challenge_hash, presented)),
            None,
        )
        if match is not None:
            sponsor_membership = SchoolMembership.objects.filter(
                school=request.school, user=match.user, status=MembershipStatus.ACTIVE
            ).first()
            sponsor = getattr(sponsor_membership, "parent_profile", None)
            if sponsor is not None and sponsor.pk != request.parent_id and _verified_link(sponsor, request.student):
                match.consumed_at = now
                match.save(update_fields=["consumed_at", "updated_at"])
                identity = request.identity_verification
                identity.method, identity.status, identity.verified_at = (
                    IdentityMethod.SPONSOR_2FA,
                    IdentityStatus.VERIFIED,
                    now,
                )
                identity.notes = "Parrainage par un parent vérifié de l'élève (code à usage unique)."
                identity.save(update_fields=["method", "status", "verified_at", "notes", "updated_at"])
                request.sponsor_parent, request.sponsor_challenge_verified = sponsor, True
                request.save(update_fields=["sponsor_parent", "sponsor_challenge_verified", "updated_at"])
                _audit("LINK_REQUEST_SPONSORED", membership, request, sponsor=str(sponsor.pk))
                return request
        for challenge in live:
            challenge.attempt_count += 1
            challenge.save(update_fields=["attempt_count", "updated_at"])
    # Outside the atomic block: the counted attempts are committed, then refused.
    record_security_event(
        SecurityEventType.LINK_SPONSOR_CODE_REJECTED,
        user=membership.user,
        school=membership.school,
        ctx=ctx,
        severity=SecuritySeverity.WARNING,
        request_id=str(request.pk),
    )
    raise ValidationError("This code is invalid or expired.", code="sponsor_code_invalid")


# =============================================================================
# Link requests (administration)
# =============================================================================


def _pending_admin(request, actor):
    require_role(actor, ADMIN_ROLES, school=request.school)
    request = (
        ParentStudentLinkRequest.objects.select_for_update()
        .select_related("identity_verification", "parent__membership", "student")
        .get(pk=request.pk)
    )
    if request.status != LinkRequestStatus.PENDING:
        raise ValidationError("This request is no longer in progress.", code="request_not_pending")
    return request


def check_identity(request, *, actor, document_type, document_number):
    """The administration checked the PHYSICAL document and types its
    number: compared with the HMAC given by the parent."""
    with transaction.atomic():
        request = _pending_admin(request, actor)
        identity = request.identity_verification
        if identity.status == IdentityStatus.VERIFIED:
            return request
        if identity.status == IdentityStatus.REJECTED:
            raise ValidationError("The identity check was rejected.", code="identity_rejected")
        matches = document_type == identity.document_type and hmac.compare_digest(
            document_hash(document_number), identity.document_reference_hash or ""
        )
        if matches:
            identity.status, identity.verified_by, identity.verified_at = IdentityStatus.VERIFIED, actor, timezone.now()
            identity.save(update_fields=["status", "verified_by", "verified_at", "updated_at"])
            _audit("LINK_IDENTITY_VERIFIED", actor, request, document_type=document_type)
            return request
        identity.failed_checks += 1
        if identity.failed_checks >= MAX_IDENTITY_MISMATCHES:
            identity.status = IdentityStatus.REJECTED
        identity.save(update_fields=["failed_checks", "status", "updated_at"])
    record_security_event(
        SecurityEventType.LINK_IDENTITY_MISMATCH,
        user=request.parent.membership.user,
        school=request.school,
        severity=SecuritySeverity.WARNING,
        request_id=str(request.pk),
        failed_checks=identity.failed_checks,
    )
    raise ValidationError("The document does not match the one declared.", code="identity_mismatch")


@transaction.atomic
def record_student_approval(request, *, actor, decision, note=None):
    request = _pending_admin(request, actor)
    if decision not in (StudentApproval.APPROVED, StudentApproval.REJECTED, StudentApproval.NOT_REQUIRED):
        raise ValidationError("Invalid decision.", code="invalid_choice")
    request.student_approval_status = decision
    request.student_approval_note = (note or "").strip() or None
    request.save(update_fields=["student_approval_status", "student_approval_note", "updated_at"])
    _audit("LINK_STUDENT_APPROVAL", actor, request, decision=decision)
    return request


@transaction.atomic
def approve_link_request(
    request,
    *,
    actor,
    can_pay=False,
    can_view_financial_data=False,
    can_receive_notifications=True,
    can_submit_complaints=True,
):
    request = _pending_admin(request, actor)
    identity = request.identity_verification
    if identity.status != IdentityStatus.VERIFIED:
        raise ValidationError("The identity is not verified yet.", code="identity_not_verified")
    if request.student_approval_status not in (StudentApproval.APPROVED, StudentApproval.NOT_REQUIRED):
        raise ValidationError("The pupil's approval is missing.", code="student_approval_required")
    if request.sponsor_challenge_verified:
        sponsor_link = _verified_link(request.sponsor_parent, request.student)
        if sponsor_link is None:
            raise ValidationError("The sponsor is no longer a verified parent.", code="sponsor_not_verified")
        if (can_pay and not sponsor_link.can_pay) or (
            can_view_financial_data and not sponsor_link.can_view_financial_data
        ):
            raise ValidationError(
                "A sponsored parent cannot have more rights than the sponsor.", code="rights_exceed_sponsor"
            )
    method = (
        VerificationMethod.SPONSOR_2FA
        if identity.method == IdentityMethod.SPONSOR_2FA
        else VerificationMethod.ID_DOCUMENT
    )
    link = ParentStudent.objects.select_for_update().filter(parent=request.parent, student=request.student).first()
    if link is None:
        link = people.link_parent(request.parent, request.student, relationship_type=request.relationship_type)
    link.relationship_type, link.active = request.relationship_type, True
    link.save(update_fields=["relationship_type", "active", "updated_at"])
    people.verify_parent_link(link, actor=actor, method=method, reference=f"link-request:{request.pk}")
    link.can_pay, link.can_view_financial_data = can_pay, can_view_financial_data
    link.can_receive_notifications, link.can_submit_complaints = can_receive_notifications, can_submit_complaints
    link.save(
        update_fields=[
            "can_pay",
            "can_view_financial_data",
            "can_receive_notifications",
            "can_submit_complaints",
            "updated_at",
        ]
    )
    request.status, request.decided_by, request.decided_at, request.link = (
        LinkRequestStatus.APPROVED,
        actor,
        timezone.now(),
        link,
    )
    request.save(update_fields=["status", "decided_by", "decided_at", "link", "updated_at"])
    _audit(
        "LINK_REQUEST_APPROVED",
        actor,
        request,
        link=str(link.pk),
        method=method,
        can_pay=can_pay,
        can_view_financial_data=can_view_financial_data,
    )
    return request


@transaction.atomic
def reject_link_request(request, *, actor, reason):
    reason = _reason(reason)
    request = _pending_admin(request, actor)
    request.status, request.decided_by, request.decided_at, request.decision_reason = (
        LinkRequestStatus.REJECTED,
        actor,
        timezone.now(),
        reason,
    )
    request.save(update_fields=["status", "decided_by", "decided_at", "decision_reason", "updated_at"])
    _audit("LINK_REQUEST_REJECTED", actor, request, reason=reason)
    return request
