"""Pre-enrollment workflow (ADR 0032). The server decides everything:
status at submission, consent timestamp, reference, transitions, history.

Invitation = a parent ACCOUNT of the school without any child link (as an
approved parent registration, ADR 0026) + the activation code of ADR 0024
(48 h here, single use, hashed). The link is returned ONCE to the
administrator, who hands it to the family: nothing is e-mailed by the server
(no mail infrastructure in this phase — the desktop says so).

An e-mail already used by an account is never linked automatically to the
request (it could be anybody's): the invitation is refused with
`account_exists` and the school handles it (existing parent workflows).
"""

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.academics.models import AcademicYear, AcademicYearStatus, Level
from apps.accounts import activation
from apps.accounts.models import MembershipRole, MembershipStatus, Role, RoleCode, SchoolMembership, User
from apps.audit.models import AuditLayer
from apps.audit.services import record_audit
from apps.people import services as people
from common.permissions import ADMIN_ROLES, require_role

from .models import TRANSITIONS, PortalInvitation, PreEnrollment, PreEnrollmentEvent, PreEnrollmentStatus

OPEN_YEARS = (AcademicYearStatus.PLANNED, AcademicYearStatus.ACTIVE)


def _event(request, action, *, actor=None, from_status="", to_status="", note=""):
    return PreEnrollmentEvent.objects.create(
        pre_enrollment=request, action=action, from_status=from_status, to_status=to_status, actor=actor, note=note
    )


def offered_levels(school):
    """The levels the school chose to show publicly (Level.public_visible, an
    existing flag): never every level, never an invented one."""
    return Level.objects.filter(school=school, active=True, public_visible=True).order_by("order_index", "name")


def offered_years(school):
    return AcademicYear.objects.filter(school=school, status__in=OPEN_YEARS).order_by("start_date")


def _next_reference(school, year):
    prefix = f"PRE-{year.start_date.year}-"
    last = (
        PreEnrollment.objects.select_for_update()
        .filter(school=school, reference__startswith=prefix)
        .aggregate(m=Max("reference"))["m"]
    )
    number = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return f"{prefix}{number:04d}"


@transaction.atomic
def submit(school, *, data, ctx=None):
    """A family's request from the public site. `data` was validated by the
    public serializer; status, dates, consent and reference are set HERE."""
    level = offered_levels(school).filter(pk=data["requested_level"]).first()
    year = offered_years(school).filter(pk=data["requested_year"]).first()
    if level is None or year is None:
        raise ValidationError("This level or school year is not open to pre-enrollment.", code="level_not_offered")
    if not data.get("consent"):
        raise ValidationError("The privacy notice must be accepted.", code="consent_required")
    now = timezone.now()
    request = PreEnrollment.objects.create(
        school=school,
        reference=_next_reference(school, year),
        guardian_first_name=data["guardian_first_name"].strip(),
        guardian_last_name=data["guardian_last_name"].strip(),
        guardian_phone=data["guardian_phone"].strip(),
        guardian_email=data["guardian_email"].strip().lower(),
        relationship=data["relationship"],
        child_first_name=data["child_first_name"].strip(),
        child_last_name=data["child_last_name"].strip(),
        child_birth_date=data.get("child_birth_date"),
        requested_level=level,
        requested_year=year,
        previous_school=(data.get("previous_school") or "").strip(),
        comment=(data.get("comment") or "").strip(),
        consent_at=now,
        consent_version=settings.PRE_ENROLLMENT_CONSENT_VERSION,
        status=PreEnrollmentStatus.RECEIVED,
        submitted_at=now,
    )
    _event(request, "SUBMITTED", to_status=PreEnrollmentStatus.RECEIVED)
    record_audit(
        "PRE_ENROLLMENT_SUBMITTED",
        actor=None,
        entity=request,
        new={"reference": request.reference, "level": str(level.pk), "year": str(year.pk)},
        ctx=ctx,
    )
    return request


@transaction.atomic
def change_status(request, to_status, *, actor, note="", message_to_family=None):
    require_role(actor, ADMIN_ROLES, school=request.school)
    request = PreEnrollment.objects.select_for_update().get(pk=request.pk)
    if to_status not in TRANSITIONS.get(request.status, set()):
        raise ValidationError("This status change is not allowed.", code="invalid_transition")
    if to_status in (PreEnrollmentStatus.REJECTED, PreEnrollmentStatus.INFO_REQUESTED) and not (note or "").strip():
        raise ValidationError("A reason is required.", code="reason_required")
    old = request.status
    request.status = to_status
    if to_status in (PreEnrollmentStatus.ACCEPTED, PreEnrollmentStatus.REJECTED):
        request.decided_at, request.decided_by = timezone.now(), actor
    if message_to_family is not None:
        request.message_to_family = message_to_family.strip()[:500]
    request.save()
    _event(request, "STATUS_CHANGED", actor=actor, from_status=old, to_status=to_status, note=(note or "").strip())
    record_audit(
        "PRE_ENROLLMENT_STATUS",
        actor=actor,
        entity=request,
        old={"status": old},
        new={"status": to_status},
        layer=AuditLayer.ADMINISTRATIVE,
    )
    return request


def _parent_account(request, actor):
    """The parent account of the request: created once (ACTIVE membership,
    role PARENT, parent profile, NO child link, no usable password)."""
    if request.account_id:
        return request.account
    email = request.guardian_email.strip().lower()
    if User.objects.filter(email__iexact=email).exists() or User.objects.filter(username__iexact=email).exists():
        raise ValidationError(
            "An account already uses this e-mail: link it through the parent workflows instead.",
            code="account_exists",
        )
    user = User.objects.create_user(
        username=email,
        email=email,
        password=None,  # unusable: the family chooses it with the invitation code
        first_name=request.guardian_first_name,
        last_name=request.guardian_last_name,
        phone=request.guardian_phone,
    )
    membership = SchoolMembership.objects.create(
        school=request.school,
        user=user,
        status=MembershipStatus.ACTIVE,
        is_primary_school=True,
        joined_at=timezone.now(),
    )
    MembershipRole.objects.create(membership=membership, role=Role.objects.get(code=RoleCode.PARENT), assigned_by=actor)
    people.create_parent_profile(membership)
    request.account = membership
    request.save(update_fields=["account", "updated_at"])
    return membership


def invitation_link(code):
    """The family's link: the code travels in the URL FRAGMENT (#), which
    browsers never send to a server — it stays out of access logs."""
    base = (settings.ISBREE_PORTAL_URL or "").rstrip("/")
    return f"{base}/activation#code={code}"


@transaction.atomic
def invite(request, *, actor, ctx=None):
    """Create the parent account (first time) and a 48 h single-use code.
    Returns (invitation, code, link): the code is shown once, never stored."""
    require_role(actor, ADMIN_ROLES, school=request.school)
    request = PreEnrollment.objects.select_for_update().get(pk=request.pk)
    if request.status != PreEnrollmentStatus.ACCEPTED:
        raise ValidationError("Only an accepted request can be invited.", code="not_accepted")
    previous = request.invitations.select_related("activation").first()
    if previous is not None:
        if previous.activation.used_at is not None:
            raise ValidationError("The family has already activated its account.", code="already_activated")
        if timezone.now() - previous.created_at < settings.PORTAL_INVITATION_MIN_INTERVAL:
            raise ValidationError("An invitation was just issued: wait a few minutes.", code="invitation_recent")
        if request.invitations.count() >= settings.PORTAL_INVITATION_MAX_PER_REQUEST:
            raise ValidationError("Too many invitations for this request.", code="invitation_limit")
    membership = _parent_account(request, actor)
    if membership.status != MembershipStatus.ACTIVE:
        raise PermissionDenied("This account is not active.")
    issued, code = activation.issue_activation(
        membership, actor=actor, ctx=ctx, lifetime=settings.PORTAL_INVITATION_LIFETIME
    )  # revokes the previous code (one pending code per account)
    invitation = PortalInvitation.objects.create(pre_enrollment=request, activation=issued, created_by=actor)
    _event(request, "INVITATION_RESENT" if previous else "INVITED", actor=actor)
    record_audit(
        "PRE_ENROLLMENT_INVITED",
        actor=actor,
        entity=request,
        new={"invitation": str(invitation.pk), "expires_at": issued.expires_at.isoformat()},
        layer=AuditLayer.ADMINISTRATIVE,
    )
    return invitation, code, invitation_link(code)


def invitation_state(request, now=None):
    """NONE | PENDING | EXPIRED | REVOKED | USED for the latest invitation."""
    latest = request.invitations.select_related("activation").first()
    if latest is None:
        return "NONE", None
    a, now = latest.activation, now or timezone.now()
    if a.used_at:
        return "USED", latest
    if a.revoked_at:
        return "REVOKED", latest
    if a.expires_at <= now:
        return "EXPIRED", latest
    return "PENDING", latest
