"""Identity & security models (spec §4.2).

Key idea: a `User` is a *global* identity (a person), while a
`SchoolMembership` is that person's presence in one school. Roles are attached
to the membership, never to the user directly, so being ADMIN in school A
grants nothing in school B. V1 has one school, but this split is what keeps
the model multi-tenant ready.
"""

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower
from django.utils import timezone

from common.models import BaseModel

# =============================================================================
# User
# =============================================================================


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, username, email, password, **extra_fields):
        if not username:
            raise ValueError("A username is required.")
        if not email:
            raise ValueError("An email is required.")
        user = self.model(username=username, email=self.normalize_email(email), **extra_fields)
        # set_password() hashes with the first PASSWORD_HASHERS entry (Argon2).
        # Passing None creates an unusable password (account activated later).
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, username, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(username, email, password, **extra_fields)

    def create_superuser(self, username, email, password=None, **extra_fields):
        extra_fields["is_staff"] = True
        extra_fields["is_superuser"] = True
        return self._create_user(username, email, password, **extra_fields)


class User(BaseModel, AbstractBaseUser, PermissionsMixin):
    """Global identity of a person.

    Inherited from AbstractBaseUser: `password` (hashed, never plaintext) and
    `last_login`. PermissionsMixin adds Django's global `is_superuser` / groups,
    used ONLY for the developer Django admin. Business authorization relies on
    tenant-scoped roles (MembershipRole), never on these global flags.
    """

    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=120)
    last_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=40, blank=True, null=True, db_index=True)
    profile_photo = models.ImageField(upload_to="users/photos/", blank=True, null=True)
    is_active = models.BooleanField(default=True, db_index=True)
    email_verified = models.BooleanField(default=False)
    phone_verified = models.BooleanField(default=False)
    # Required by the Django admin site only (not in the business spec).
    is_staff = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "username"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["email", "first_name", "last_name"]

    class Meta:
        constraints = [
            # Case-insensitive uniqueness: "Admin" and "admin" must not be two
            # different accounts (classic impersonation trick).
            models.UniqueConstraint(Lower("username"), name="user_username_ci_unique"),
            models.UniqueConstraint(Lower("email"), name="user_email_ci_unique"),
        ]

    def save(self, *args, **kwargs):
        # Emails are compared case-insensitively; store them lower-cased.
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def __str__(self):
        return self.username


# =============================================================================
# Roles & memberships
# =============================================================================


class RoleCode(models.TextChoices):
    """System roles from the permission matrix (spec §8)."""

    SUPER_ADMIN = "SUPER_ADMIN", "Super administrateur"
    ADMIN = "ADMIN", "Administrateur"
    TEACHER = "TEACHER", "Enseignant"
    PARENT = "PARENT", "Parent / Tuteur"
    GUARDIAN = "GUARDIAN", "Gardien"
    STAFF = "STAFF", "Personnel"
    CONTENT_MANAGER = "CONTENT_MANAGER", "Gestionnaire de contenu"


class Role(BaseModel):
    """Global role catalog. System roles are seeded by migration 0002."""

    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    # System roles are referenced by code in permission checks: they must not
    # be renamed or removed from the admin UI.
    system_role = models.BooleanField(default=False)

    def __str__(self):
        return self.code


class MembershipStatus(models.TextChoices):
    # PENDING: e.g. a teacher who registered on the public site and awaits
    # administrative validation (spec §15).
    PENDING = "PENDING", "En attente"
    ACTIVE = "ACTIVE", "Active"
    SUSPENDED = "SUSPENDED", "Suspendue"
    LEFT = "LEFT", "Partie"


class SchoolMembershipQuerySet(models.QuerySet):
    def active(self):
        """Memberships that may act: ACTIVE membership in an ACTIVE school."""
        return self.filter(status=MembershipStatus.ACTIVE, school__status="ACTIVE")


class SchoolMembership(BaseModel):
    """Links a global User to one School (tenant)."""

    # PROTECT on both sides: membership rows are referenced by history
    # (who validated a grade, who approved a payment...) and must survive.
    school = models.ForeignKey("core.School", on_delete=models.PROTECT, related_name="memberships")
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="memberships")
    status = models.CharField(
        max_length=20, choices=MembershipStatus.choices, default=MembershipStatus.PENDING, db_index=True
    )
    joined_at = models.DateTimeField(blank=True, null=True)
    left_at = models.DateTimeField(blank=True, null=True)
    is_primary_school = models.BooleanField(default=False)

    objects = SchoolMembershipQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["school", "user"], name="membership_school_user_unique"),
            models.CheckConstraint(condition=Q(status__in=MembershipStatus.values), name="membership_status_valid"),
            models.CheckConstraint(
                condition=Q(left_at__isnull=True) | Q(joined_at__isnull=True) | Q(left_at__gte=F("joined_at")),
                name="membership_left_after_joined",
            ),
            # A user has at most one primary school, otherwise tenant
            # resolution (common.tenancy) would be ambiguous.
            models.UniqueConstraint(
                fields=["user"], condition=Q(is_primary_school=True), name="membership_one_primary_per_user"
            ),
        ]

    def role_codes(self) -> set[str]:
        """Codes of the roles currently active on this membership."""
        return set(self.membership_roles.filter(active=True).values_list("role__code", flat=True))

    def __str__(self):
        return f"{self.user} @ {self.school}"


class MembershipRole(BaseModel):
    """Role assignment inside one school membership (tenant-scoped role)."""

    # CASCADE: a role assignment has no meaning without its membership.
    membership = models.ForeignKey(SchoolMembership, on_delete=models.CASCADE, related_name="membership_roles")
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="assignments")
    # SET_NULL: the assigner may leave the school, the assignment history stays.
    assigned_by = models.ForeignKey(
        SchoolMembership, on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )
    active = models.BooleanField(default=True, db_index=True)
    assigned_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["membership", "role"], name="membership_role_unique"),
        ]

    def __str__(self):
        return f"{self.membership} → {self.role}"


# =============================================================================
# Devices & sessions (multi-device security)
# =============================================================================


class UserDevice(BaseModel):
    """A device (phone, admin PC, browser) a user has logged in from.

    The raw device identifier sent by the client is never stored: only an HMAC
    of it (see tokens.hash_device_identifier), so a database leak does not
    expose hardware identifiers.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="devices")
    device_name = models.CharField(max_length=120)
    device_type = models.CharField(max_length=30)
    platform = models.CharField(max_length=30)
    os_version = models.CharField(max_length=80, blank=True, null=True)
    android_sdk = models.PositiveIntegerField(blank=True, null=True)
    app_version = models.CharField(max_length=40, blank=True, null=True)
    device_identifier_hash = models.CharField(max_length=128, db_index=True)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)
    is_trusted = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "device_identifier_hash"], name="device_user_identifier_unique"),
        ]

    def __str__(self):
        return f"{self.device_name} ({self.platform})"


class UserSession(BaseModel):
    """One logged-in session = one refresh token on one device.

    Only the SHA-256 hash of the refresh token is stored (like a password): a
    stolen database dump cannot be replayed to impersonate users. Revoking a
    session (logout, "disconnect this device", password change) immediately
    invalidates its access tokens too, because access tokens point to it.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sessions")
    device = models.ForeignKey(UserDevice, on_delete=models.CASCADE, related_name="sessions")
    # Indexed (deviation from spec table, see ADR 0002): every refresh call
    # looks the session up by this hash.
    refresh_token_hash = models.CharField(max_length=128, unique=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)
    last_used_at = models.DateTimeField(blank=True, null=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(expires_at__gt=F("created_at")), name="session_expires_after_creation"),
        ]

    def is_usable(self, now=None) -> bool:
        now = now or timezone.now()
        return self.revoked_at is None and self.expires_at > now and self.user.is_active

    def __str__(self):
        return f"Session {self.id} ({self.user})"


class RotatedRefreshToken(BaseModel):
    """Hash of a refresh token that has been replaced by rotation.

    A session is a *token family*: each refresh replaces its token by a new
    one. The session id is therefore the family identifier, no extra column
    is needed on UserSession. Keeping the superseded hashes lets the server
    recognise a token that was already used: only someone holding a copy
    (an attacker, or the victim after the attacker refreshed first) can
    present it again. That family is then revoked (ADR 0002).

    Addition to the spec (§4.2 has no such table) — see ADR 0002.
    """

    # CASCADE: the history has no meaning without its session.
    session = models.ForeignKey(UserSession, on_delete=models.CASCADE, related_name="rotated_tokens")
    token_hash = models.CharField(max_length=128, unique=True)

    def __str__(self):
        return f"Rotated token of {self.session_id}"


# =============================================================================
# Account activation (ADR 0024)
# =============================================================================


class AccountActivation(BaseModel):
    """One-time code that lets a person set the FIRST password of an account
    created by the administration (teacher, staff...).

    - Only the SHA-256 of the code is stored (like refresh tokens): the code
      has ~100 random bits, so a fast hash is enough; it is shown to the
      administrator once and never logged.
    - Single use (`used_at`), expiry (`expires_at`), revocation (`revoked_at`).
    - At most ONE pending code per membership (partial unique index): issuing
      a new code revokes the previous one.
    - Rows are history (who issued, when used / revoked): never deleted.
    """

    school = models.ForeignKey("core.School", on_delete=models.PROTECT, related_name="+")
    membership = models.ForeignKey(SchoolMembership, on_delete=models.PROTECT, related_name="activations")
    code_hash = models.CharField(max_length=64, unique=True)
    issued_by = models.ForeignKey(SchoolMembership, on_delete=models.SET_NULL, blank=True, null=True, related_name="+")
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(blank=True, null=True)
    revoked_at = models.DateTimeField(blank=True, null=True)
    revoked_by = models.ForeignKey(SchoolMembership, on_delete=models.SET_NULL, blank=True, null=True, related_name="+")

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(expires_at__gt=F("created_at")), name="activation_expires_after_creation"
            ),
            models.CheckConstraint(
                condition=Q(used_at__isnull=True) | Q(revoked_at__isnull=True), name="activation_used_or_revoked"
            ),
            models.UniqueConstraint(
                fields=["membership"],
                condition=Q(used_at__isnull=True, revoked_at__isnull=True),
                name="activation_one_pending_per_membership",
            ),
        ]

    def is_pending(self, now=None):
        now = now or timezone.now()
        return self.used_at is None and self.revoked_at is None and self.expires_at > now

    def __str__(self):
        return f"Activation {self.id} ({self.membership_id})"


# =============================================================================
# Verification challenges (spec V4 "VerificationChallenge", ADR 0026)
# =============================================================================


class ChallengePurpose(models.TextChoices):
    # A VERIFIED parent vouches for a second parent / tutor of the same pupil.
    LINK_SPONSOR = "LINK_SPONSOR", "Parrainage d'un rattachement parent–élève"


class ChallengeChannel(models.TextChoices):
    # Shown in the issuer's authenticated app, handed over in person: no SMS /
    # e-mail provider needed (LAN-first, no cloud dependency).
    IN_APP = "IN_APP", "Application (remis en personne)"


class VerificationChallenge(BaseModel):
    """Short-lived, single-use challenge. Only its SHA-256 is stored.

    Additions to the spec table (ADR 0026): `school` and `target_id` (the
    object the challenge is about — the pupil for LINK_SPONSOR) so that a
    challenge can only be used inside its school and for its object.
    """

    school = models.ForeignKey("core.School", on_delete=models.PROTECT, related_name="+")
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="challenges")
    purpose = models.CharField(max_length=40, choices=ChallengePurpose.choices)
    channel = models.CharField(max_length=30, choices=ChallengeChannel.choices, default=ChallengeChannel.IN_APP)
    target_id = models.UUIDField(db_index=True)
    challenge_hash = models.CharField(max_length=128, unique=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(blank=True, null=True)
    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(expires_at__gt=F("created_at")), name="challenge_expires_after_creation"
            ),
            models.CheckConstraint(condition=Q(purpose__in=ChallengePurpose.values), name="challenge_purpose_valid"),
        ]

    def usable(self, now=None):
        now = now or timezone.now()
        return self.consumed_at is None and self.expires_at > now and self.attempt_count < self.max_attempts


# =============================================================================
# Security events (separate from business audit - spec §3)
# =============================================================================


class SecurityEventType(models.TextChoices):
    LOGIN_SUCCEEDED = "LOGIN_SUCCEEDED"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"
    # Event names, not secrets (silences the linter's hardcoded-password rule).
    TOKEN_REFRESHED = "TOKEN_REFRESHED"  # noqa: S105
    REFRESH_REJECTED = "REFRESH_REJECTED"
    # An already-rotated refresh token was presented: the session is
    # considered compromised and revoked (ADR 0002).
    REFRESH_TOKEN_REUSE_DETECTED = "REFRESH_TOKEN_REUSE_DETECTED"  # noqa: S105
    SESSION_REVOKED = "SESSION_REVOKED"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"  # noqa: S105
    ALL_SESSIONS_REVOKED = "ALL_SESSIONS_REVOKED"
    BOOTSTRAP_COMPLETED = "BOOTSTRAP_COMPLETED"
    BOOTSTRAP_REJECTED = "BOOTSTRAP_REJECTED"
    # Account lifecycle (ADR 0024). The activation code itself is never logged.
    ACCOUNT_ACTIVATION_ISSUED = "ACCOUNT_ACTIVATION_ISSUED"
    ACCOUNT_ACTIVATION_REVOKED = "ACCOUNT_ACTIVATION_REVOKED"
    ACCOUNT_ACTIVATED = "ACCOUNT_ACTIVATED"
    ACCOUNT_ACTIVATION_REJECTED = "ACCOUNT_ACTIVATION_REJECTED"
    ACCOUNT_DISABLED = "ACCOUNT_DISABLED"
    ACCOUNT_ENABLED = "ACCOUNT_ENABLED"
    # Parent registration and linking (ADR 0026). Never a password, a code or
    # an identity document number in the metadata.
    PARENT_REGISTRATION_SUBMITTED = "PARENT_REGISTRATION_SUBMITTED"
    PARENT_REGISTRATION_DUPLICATE = "PARENT_REGISTRATION_DUPLICATE"
    LINK_IDENTITY_MISMATCH = "LINK_IDENTITY_MISMATCH"
    LINK_SPONSOR_CODE_ISSUED = "LINK_SPONSOR_CODE_ISSUED"
    LINK_SPONSOR_CODE_REJECTED = "LINK_SPONSOR_CODE_REJECTED"


class SecuritySeverity(models.TextChoices):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class SecurityEvent(BaseModel):
    """Append-only security log (logins, failures, revocations...).

    Written through the dedicated `security_log` connection (ADR 0005), so it
    is committed independently of the business transaction.

    `metadata` must never contain passwords, tokens or identity documents
    (spec §9): only identifiers and non-sensitive context.

    Referential integrity (ADR 0005): `user` and `school` are real PostgreSQL
    foreign keys declared `ON DELETE SET NULL` at database level (migration
    0003): an event outlives the user/school it mentions, and a reference,
    when present, always points to an existing row. When an event must be
    written while the referenced row is not yet committed by the business
    transaction, `record_security_event` keeps the event and moves the id into
    `metadata["unresolved_refs"]` instead of losing it.
    """

    school = models.ForeignKey("core.School", on_delete=models.SET_NULL, blank=True, null=True, related_name="+")
    user = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True, related_name="security_events")
    event_type = models.CharField(max_length=50, choices=SecurityEventType.choices, db_index=True)
    severity = models.CharField(
        max_length=20, choices=SecuritySeverity.choices, default=SecuritySeverity.INFO, db_index=True
    )
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)
    metadata = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.event_type} ({self.created_at:%Y-%m-%d %H:%M})"
