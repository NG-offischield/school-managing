"""Account lifecycle: activation of accounts created by the administration,
and administrative disabling (ADR 0024). One mechanism for every business
account (teacher, staff...). No second authentication system: activation
only sets the FIRST password of the existing User (Argon2); the person then
logs in through the normal /auth/login/.

Activation code
- ~100 random bits, Crockford base32, grouped for typing: "7KQ2-M9XA-...";
  normalised on input (case, spaces, dashes, I/L -> 1, O -> 0);
- only its SHA-256 is stored; it is returned ONCE to the administrator,
  never logged (security events carry the activation id only);
- single use (row locked, used_at), expiry, revocation; one pending code per
  membership (issuing a new one revokes the previous one).

Anti-enumeration: every failure of the public endpoints (unknown, expired,
used, revoked code, disabled account, already activated) gives the SAME
answer; the reason is in the security log only.

Disabled account: membership SUSPENDED (+ user inactive when no other
school), sessions revoked, pending code revoked. Login and refresh then
refuse it through the existing checks (inactive user / no active membership).
"""

import secrets

from django.conf import settings
from django.contrib.auth import password_validation
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditLayer
from apps.audit.services import record_audit
from common.permissions import ADMIN_ROLES

from .models import AccountActivation, MembershipStatus, RoleCode, SecurityEventType, SecuritySeverity
from .services import revoke_all_sessions
from .tokens import hash_token

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32 (no I, L, O, U)
CODE_LENGTH = 20  # 20 x 5 bits = 100 bits


class InvalidActivation(Exception):
    """Any refusal of a public activation request (single, generic answer)."""


class AccountState:
    ACTIVE = "ACTIVE"  # a password is set: the person can log in
    PENDING_ACTIVATION = "PENDING_ACTIVATION"  # a valid code is waiting
    NOT_ACTIVATED = "NOT_ACTIVATED"  # no password, no valid code (never issued, expired, revoked)
    DISABLED = "DISABLED"  # suspended by the administration


def new_code():
    raw = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
    return "-".join(raw[i : i + 4] for i in range(0, CODE_LENGTH, 4))


def normalise(code):
    cleaned = "".join(c for c in (code or "").upper() if c.isalnum())
    return cleaned.translate(str.maketrans({"I": "1", "L": "1", "O": "0"}))


def code_hash(code):
    return hash_token(normalise(code))


# --- state ---------------------------------------------------------------------------


def _admin(actor, school):
    if actor is None or actor.school_id != school.pk or not (actor.role_codes() & ADMIN_ROLES):
        raise PermissionDenied("Only the administration of the school manages accounts.")


def _security(event, membership, ctx=None, severity=SecuritySeverity.INFO, **metadata):
    from .services import record_security_event

    record_security_event(
        event, user=membership.user, school=membership.school, ctx=ctx, severity=severity, after_commit=True, **metadata
    )


def pending_activation(membership, now=None):
    now = now or timezone.now()
    return (
        membership.activations.filter(used_at__isnull=True, revoked_at__isnull=True, expires_at__gt=now)
        .order_by("-created_at")
        .first()
    )


def is_disabled(membership):
    return (
        membership.status != MembershipStatus.ACTIVE
        or not membership.user.is_active
        or membership.school.status != "ACTIVE"
    )


def account_state(membership):
    if is_disabled(membership):
        return AccountState.DISABLED
    if membership.user.has_usable_password():
        return AccountState.ACTIVE
    if pending_activation(membership) is not None:
        return AccountState.PENDING_ACTIVATION
    return AccountState.NOT_ACTIVATED


def account_summary(membership):
    """What the administration may know (never a code, never a hash)."""
    pending = pending_activation(membership)
    last = membership.activations.order_by("-created_at").first()
    return {
        "membership": str(membership.pk),
        "name": membership.user.full_name,
        "login": membership.user.username,
        "state": account_state(membership),
        "last_login": membership.user.last_login,
        "pending_expires_at": pending.expires_at if pending else None,
        "last_issued_at": last.created_at if last else None,
        "activated_at": membership.activations.filter(used_at__isnull=False).values_list("used_at", flat=True).first(),
    }


# --- administration ----------------------------------------------------------------


@transaction.atomic
def issue_activation(membership, *, actor, ctx=None, lifetime=None):
    """New single-use code for an account WITHOUT password. Returns
    (activation, code): the code is shown once and never stored in clear.
    `lifetime` (timedelta): shorter validity for a portal invitation link
    (ADR 0032); default ACCOUNT_ACTIVATION_LIFETIME."""
    _admin(actor, membership.school)
    membership = type(membership).objects.select_for_update().select_related("user", "school").get(pk=membership.pk)
    if membership.user.has_usable_password():
        raise ValidationError("This account is already activated.", code="account_already_active")
    if is_disabled(membership):
        raise ValidationError("This account is disabled.", code="account_disabled")
    if RoleCode.SUPER_ADMIN in membership.role_codes() and RoleCode.SUPER_ADMIN not in actor.role_codes():
        raise PermissionDenied("Only a super administrator manages this account.")
    now = timezone.now()
    previous = membership.activations.filter(used_at__isnull=True, revoked_at__isnull=True)
    for old in previous:
        old.revoked_at, old.revoked_by = now, actor
        old.save(update_fields=["revoked_at", "revoked_by", "updated_at"])
    code = new_code()
    activation = AccountActivation.objects.create(
        school=membership.school,
        membership=membership,
        code_hash=code_hash(code),
        issued_by=actor,
        created_at=now,
        expires_at=now + (lifetime or settings.ACCOUNT_ACTIVATION_LIFETIME),
    )
    record_audit(
        "ACCOUNT_ACTIVATION_ISSUED",
        actor=actor,
        entity=membership,
        new={"activation": str(activation.pk), "expires_at": activation.expires_at.isoformat()},
        layer=AuditLayer.ADMINISTRATIVE,
    )
    _security(SecurityEventType.ACCOUNT_ACTIVATION_ISSUED, membership, ctx, activation_id=str(activation.pk))
    return activation, code


@transaction.atomic
def revoke_activation(membership, *, actor, ctx=None):
    _admin(actor, membership.school)
    activation = (
        AccountActivation.objects.select_for_update()
        .filter(membership=membership, used_at__isnull=True, revoked_at__isnull=True)
        .first()
    )
    if activation is None:
        raise ValidationError("No activation code is pending for this account.", code="no_pending_activation")
    activation.revoked_at, activation.revoked_by = timezone.now(), actor
    activation.save(update_fields=["revoked_at", "revoked_by", "updated_at"])
    record_audit(
        "ACCOUNT_ACTIVATION_REVOKED",
        actor=actor,
        entity=membership,
        new={"activation": str(activation.pk)},
        layer=AuditLayer.ADMINISTRATIVE,
    )
    _security(SecurityEventType.ACCOUNT_ACTIVATION_REVOKED, membership, ctx, activation_id=str(activation.pk))
    return activation


@transaction.atomic
def disable_account(membership, *, actor, reason, ctx=None):
    _admin(actor, membership.school)
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("A reason is required.", code="reason_required")
    if membership.pk == actor.pk:
        raise ValidationError("You cannot disable your own account.", code="cannot_disable_self")
    membership = type(membership).objects.select_for_update().select_related("user", "school").get(pk=membership.pk)
    if RoleCode.SUPER_ADMIN in membership.role_codes() and RoleCode.SUPER_ADMIN not in actor.role_codes():
        raise PermissionDenied("Only a super administrator manages this account.")
    if membership.status == MembershipStatus.SUSPENDED:
        raise ValidationError("This account is already disabled.", code="account_disabled")
    old = membership.status
    membership.status = MembershipStatus.SUSPENDED
    membership.save(update_fields=["status", "updated_at"])
    user = membership.user
    if not user.memberships.filter(status=MembershipStatus.ACTIVE).exclude(pk=membership.pk).exists():
        user.is_active = False  # login and refresh refused by the existing checks
        user.save(update_fields=["is_active", "updated_at"])
    now = timezone.now()
    membership.activations.filter(used_at__isnull=True, revoked_at__isnull=True).update(
        revoked_at=now, revoked_by=actor, updated_at=now
    )
    revoked = revoke_all_sessions(user, ctx=ctx, actor=actor.user)
    record_audit(
        "ACCOUNT_DISABLED",
        actor=actor,
        entity=membership,
        old={"status": old},
        new={"status": membership.status, "reason": reason, "sessions_revoked": revoked},
        layer=AuditLayer.ADMINISTRATIVE,
    )
    _security(SecurityEventType.ACCOUNT_DISABLED, membership, ctx, SecuritySeverity.WARNING, actor_id=str(actor.pk))
    return membership


@transaction.atomic
def enable_account(membership, *, actor, ctx=None):
    _admin(actor, membership.school)
    membership = type(membership).objects.select_for_update().select_related("user").get(pk=membership.pk)
    if membership.status != MembershipStatus.SUSPENDED:
        raise ValidationError("This account is not disabled.", code="account_not_disabled")
    membership.status = MembershipStatus.ACTIVE
    membership.save(update_fields=["status", "updated_at"])
    if not membership.user.is_active:
        membership.user.is_active = True
        membership.user.save(update_fields=["is_active", "updated_at"])
    record_audit(
        "ACCOUNT_ENABLED",
        actor=actor,
        entity=membership,
        old={"status": MembershipStatus.SUSPENDED},
        new={"status": membership.status},
        layer=AuditLayer.ADMINISTRATIVE,
    )
    _security(SecurityEventType.ACCOUNT_ENABLED, membership, ctx, actor_id=str(actor.pk))
    return membership


# --- public activation ---------------------------------------------------------------


def _reject(reason, ctx, activation=None):
    from .services import record_security_event

    record_security_event(
        SecurityEventType.ACCOUNT_ACTIVATION_REJECTED,
        user=activation.membership.user if activation else None,
        school=activation.school if activation else None,
        ctx=ctx,
        severity=SecuritySeverity.WARNING,
        reason=reason,
        **({"activation_id": str(activation.pk)} if activation else {}),
    )
    raise InvalidActivation()


def _usable(code, ctx, *, lock):
    queryset = AccountActivation.objects.select_related("membership__user", "membership__school", "school")
    if lock:
        queryset = queryset.select_for_update(of=("self",))
    activation = queryset.filter(code_hash=code_hash(code)).first()
    if activation is None:
        _reject("UNKNOWN_CODE", ctx)
    membership = activation.membership
    if activation.used_at is not None:
        _reject("ALREADY_USED", ctx, activation)
    if activation.revoked_at is not None:
        _reject("REVOKED", ctx, activation)
    if activation.expires_at <= timezone.now():
        _reject("EXPIRED", ctx, activation)
    if membership.school_id != activation.school_id:
        _reject("SCHOOL_MISMATCH", ctx, activation)
    if is_disabled(membership):
        _reject("ACCOUNT_DISABLED", ctx, activation)
    if membership.user.has_usable_password():
        _reject("ALREADY_ACTIVE", ctx, activation)
    return activation


def check_activation(code, *, ctx=None):
    """What the person sees before choosing a password (minimal)."""
    activation = _usable(code, ctx, lock=False)
    user = activation.membership.user
    return {
        "first_name": user.first_name,
        "school": activation.school.name,
        "login": user.username,
        "expires_at": activation.expires_at,
    }


def complete_activation(code, password, *, ctx=None):
    """Set the first password (Django validators, Argon2) and burn the code.
    Raises InvalidActivation (generic) or ValidationError (weak password)."""
    with transaction.atomic():
        activation = _usable(code, ctx, lock=True)
        user = activation.membership.user
        password_validation.validate_password(password, user)
        user.set_password(password)
        user.save(update_fields=["password", "updated_at"])
        activation.used_at = timezone.now()
        activation.save(update_fields=["used_at", "updated_at"])
        record_audit(
            "ACCOUNT_ACTIVATED",
            actor=activation.membership,
            entity=activation.membership,
            new={"activation": str(activation.pk)},
            layer=AuditLayer.ADMINISTRATIVE,
        )
        _security(SecurityEventType.ACCOUNT_ACTIVATED, activation.membership, ctx, activation_id=str(activation.pk))
    return {"login": user.username}
