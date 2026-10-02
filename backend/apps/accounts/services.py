"""Authentication & session services.

Views stay thin: they validate input, call one of these functions and format
the output. All security decisions live here, where they are unit-tested.
"""

from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth import authenticate
from django.db import DatabaseError, transaction
from django.db.models import Q
from django.utils import timezone

from common.db_routers import SECURITY_LOG_ALIAS

from .models import (
    RotatedRefreshToken,
    SecurityEvent,
    SecurityEventType,
    SecuritySeverity,
    User,
    UserDevice,
    UserSession,
)
from .tokens import hash_device_identifier, hash_token, make_access_token, new_refresh_token


class InvalidCredentials(Exception):
    """Login failed. Deliberately carries no reason (see `login`)."""


class InvalidRefreshToken(Exception):
    pass


@dataclass
class ClientContext:
    """Network context of a request, recorded on sessions and security events."""

    ip_address: str | None = None
    user_agent: str | None = None

    @classmethod
    def from_request(cls, request):
        # REMOTE_ADDR only: X-Forwarded-For is client-controlled and will only
        # be trusted once a known reverse proxy is configured (production).
        return cls(
            ip_address=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT"),
        )


@dataclass
class IssuedTokens:
    session: UserSession
    access_token: str
    refresh_token: str  # raw value: returned to the client once, never stored


# -----------------------------------------------------------------------------
# Security log
# -----------------------------------------------------------------------------


def record_security_event(
    event_type,
    *,
    user=None,
    school=None,
    ctx=None,
    severity=SecuritySeverity.INFO,
    after_commit=False,
    **metadata,
):
    """Write a security event through the dedicated `security_log` connection.

    Two timings, chosen per event (ADR 0005):

    - `after_commit=False` (default) — refusals and attacks (LOGIN_FAILED,
      REFRESH_REJECTED, BOOTSTRAP_REJECTED...). Written immediately on the
      autocommit `security_log` connection: the event is durable even if the
      business transaction is rolled back afterwards (e.g. the view raises).
    - `after_commit=True` — successes (LOGIN_SUCCEEDED, LOGOUT...). Written only
      once the business transaction has really committed; otherwise the log
      would claim something happened that was in fact rolled back.
    """
    ctx = ctx or ClientContext()

    def write():
        fields = dict(
            event_type=event_type,
            severity=severity,
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
        )
        try:
            # atomic(using=...) so that a failed insert leaves the autocommit
            # connection clean for the fallback below.
            with transaction.atomic(using=SECURITY_LOG_ALIAS):
                SecurityEvent.objects.create(user=user, school=school, metadata=metadata, **fields)
        except DatabaseError:
            # The FK check (or its lock, bounded by lock_timeout) failed: the
            # referenced row is not visible to the security_log connection yet
            # (still uncommitted in the business transaction, or rolled back).
            # Losing a security event is worse than losing a link: keep the
            # event, keep the ids as plain data (ADR 0005).
            unresolved = {
                key: str(obj.pk) for key, obj in (("user_id", user), ("school_id", school)) if obj is not None
            }
            SecurityEvent.objects.create(metadata={**metadata, "unresolved_refs": unresolved}, **fields)

    if after_commit:
        # Hooked on the business (default) connection; runs at once if no
        # transaction is open.
        transaction.on_commit(write)
    else:
        write()


# -----------------------------------------------------------------------------
# Login / sessions
# -----------------------------------------------------------------------------


def register_device(user, device_data: dict) -> UserDevice:
    """Find or create the device, keyed by the HMAC of its identifier."""
    identifier_hash = hash_device_identifier(device_data["identifier"])
    details = {k: v for k, v in device_data.items() if k != "identifier"}
    device, created = UserDevice.objects.get_or_create(
        user=user, device_identifier_hash=identifier_hash, defaults=details
    )
    if not created:
        for field, value in details.items():
            setattr(device, field, value)
        device.last_seen_at = timezone.now()
        device.save()
    return device


def _issued(session: UserSession, raw_refresh: str) -> IssuedTokens:
    return IssuedTokens(session=session, access_token=make_access_token(session), refresh_token=raw_refresh)


def _find_user(identifier: str):
    """Users may log in with their username or their email (case-insensitive)."""
    return User.objects.filter(Q(username__iexact=identifier) | Q(email__iexact=identifier)).first()


def login(identifier: str, password: str, device_data: dict, ctx: ClientContext) -> IssuedTokens:
    """Check credentials and open a new session.

    Security notes:
    - The error never says whether the account exists or the password is
      wrong (prevents account enumeration).
    - When the user does not exist, Django's `authenticate` still runs a
      password hash, so response time does not reveal it either.
    - Inactive users are refused by `authenticate` itself.
    """
    user = _find_user(identifier)
    authenticated = authenticate(username=user.username if user else identifier, password=password)
    if authenticated is None:
        record_security_event(
            SecurityEventType.LOGIN_FAILED,
            user=user,
            ctx=ctx,
            severity=SecuritySeverity.WARNING,
            # The identifier typed is useful to detect attacks; the password is
            # of course never logged.
            identifier=identifier[:150],
        )
        raise InvalidCredentials()

    with transaction.atomic():
        device = register_device(authenticated, device_data)
        now = timezone.now()
        raw_refresh = new_refresh_token()
        session = UserSession.objects.create(
            user=authenticated,
            device=device,
            refresh_token_hash=hash_token(raw_refresh),
            ip_address=ctx.ip_address,
            user_agent=ctx.user_agent,
            created_at=now,
            last_used_at=now,
            expires_at=now + settings.REFRESH_TOKEN_LIFETIME,
        )
        authenticated.last_login = now
        authenticated.save(update_fields=["last_login"])
        record_security_event(
            SecurityEventType.LOGIN_SUCCEEDED,
            user=authenticated,
            ctx=ctx,
            after_commit=True,
            session_id=str(session.id),
            device_id=str(device.id),
        )
    return _issued(session, raw_refresh)


def refresh(raw_refresh_token: str, ctx: ClientContext) -> IssuedTokens:
    """Exchange a refresh token for a new access token AND a new refresh token.

    Rotation means a stolen refresh token stops working as soon as the
    legitimate client refreshes once. `select_for_update` prevents two
    concurrent refreshes with the same token from both succeeding.

    Reuse detection (ADR 0002): the replaced hash is kept in
    RotatedRefreshToken. If such an old token is presented again, someone
    holds a copy of it: the request is refused, the event is logged as
    CRITICAL and the whole session (= token family) is revoked, so neither the
    attacker nor the victim's copy can continue. Other sessions of the user
    are NOT touched (no global policy is triggered here).

    Transaction contract: the revocation must be committed even though the
    function then raises. It is committed by the atomic block below, so the
    caller must not run inside an outer transaction that will be rolled back
    (RefreshView is excluded from ATOMIC_REQUESTS for that reason).
    """
    presented_hash = hash_token(raw_refresh_token)
    with transaction.atomic():
        session = (
            UserSession.objects.select_for_update(of=("self",))
            .select_related("user")
            .filter(refresh_token_hash=presented_hash)
            .first()
        )
        if session is not None and session.is_usable():
            # Normal rotation: archive the presented token, issue a new one.
            RotatedRefreshToken.objects.create(session=session, token_hash=presented_hash)
            raw_refresh = new_refresh_token()
            session.refresh_token_hash = hash_token(raw_refresh)
            session.last_used_at = timezone.now()
            session.ip_address = ctx.ip_address
            session.save(update_fields=["refresh_token_hash", "last_used_at", "ip_address", "updated_at"])
            record_security_event(
                SecurityEventType.TOKEN_REFRESHED,
                user=session.user,
                ctx=ctx,
                after_commit=True,
                session_id=str(session.id),
            )
            return _issued(session, raw_refresh)

        reused = None
        if session is None:
            reused = RotatedRefreshToken.objects.filter(token_hash=presented_hash).first()
            if reused is not None:
                session = (
                    UserSession.objects.select_for_update(of=("self",)).select_related("user").get(pk=reused.session_id)
                )
                was_active = session.revoked_at is None
                if was_active:
                    session.revoked_at = timezone.now()
                    session.save(update_fields=["revoked_at", "updated_at"])

    # Rejection paths. Events are written immediately on the security_log
    # connection (ADR 0005); reasons are distinguished in the log only, never
    # in the API answer.
    if reused is not None:
        record_security_event(
            SecurityEventType.REFRESH_TOKEN_REUSE_DETECTED,
            user=session.user,
            ctx=ctx,
            severity=SecuritySeverity.CRITICAL,
            session_id=str(session.id),
            session_was_active=was_active,
        )
    else:
        if session is None:
            reason = "UNKNOWN_TOKEN"
        elif session.revoked_at is not None:
            reason = "SESSION_REVOKED"
        elif not session.user.is_active:
            reason = "USER_INACTIVE"
        else:
            reason = "SESSION_EXPIRED"
        record_security_event(
            SecurityEventType.REFRESH_REJECTED,
            user=session.user if session else None,
            ctx=ctx,
            severity=SecuritySeverity.WARNING,
            reason=reason,
        )
    raise InvalidRefreshToken()


def revoke_session(session: UserSession, *, ctx=None, reason=SecurityEventType.SESSION_REVOKED) -> None:
    if session.revoked_at is None:
        session.revoked_at = timezone.now()
        session.save(update_fields=["revoked_at", "updated_at"])
        record_security_event(reason, user=session.user, ctx=ctx, after_commit=True, session_id=str(session.id))


@transaction.atomic
def revoke_all_sessions(user, *, except_session=None, ctx=None, actor=None) -> int:
    """Global logout: revoke every active session of `user` (optionally
    keeping one). Returns the number revoked.

    Access tokens die with their sessions, since each request re-checks the
    session (ADR 0002).

    `actor` prepares the future *administrative* revocation (an admin cutting
    off a compromised account). This service does not authorise anything: the
    calling view must check the permission (role ADMIN/SUPER_ADMIN in the
    target user's school, see ADR 0002). The actor is recorded so the log
    distinguishes a self-service logout from an administrative one.
    """
    sessions = user.sessions.filter(revoked_at__isnull=True)
    if except_session is not None:
        sessions = sessions.exclude(pk=except_session.pk)
    count = sessions.update(revoked_at=timezone.now())

    administrative = actor is not None and actor.pk != user.pk
    metadata = {"revoked_count": count, "initiated_by": "ADMIN" if administrative else "SELF"}
    if administrative:
        metadata["actor_id"] = str(actor.pk)
    record_security_event(
        SecurityEventType.ALL_SESSIONS_REVOKED,
        user=user,
        ctx=ctx,
        severity=SecuritySeverity.WARNING if administrative else SecuritySeverity.INFO,
        after_commit=True,
        **metadata,
    )
    return count


@transaction.atomic
def change_password(user, new_password: str, *, keep_session=None, ctx=None) -> None:
    """Change the password and disconnect every OTHER session.

    If the password was changed because it leaked, the attacker's sessions
    must die with it; the device doing the change stays logged in.
    """
    user.set_password(new_password)
    user.save(update_fields=["password", "updated_at"])
    revoke_all_sessions(user, except_session=keep_session, ctx=ctx)
    record_security_event(SecurityEventType.PASSWORD_CHANGED, user=user, ctx=ctx, after_commit=True)
