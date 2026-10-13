"""Communication (spec §4.6, §6.11, ADR 0015).

    Notification ── NotificationDelivery      in-app notification of ONE membership,
                                              + push queue (future FCM worker)
    NotificationPreference                    per-type opt-out (non-mandatory types)
    Conversation ── ConversationParticipant   private conversations (administration,
                 └─ Message ── MessageAttachment     parent-teacher, complaint thread)
    ForumSpace ── ForumThread ── ForumPost    school / class groups, announcements
    Complaint ── ComplaintStatusHistory       complaint workflow, immutable history
              └─ ComplaintAttachment

History is never destroyed: messages and posts are soft-deleted (the row
and its body stay), status histories and attachments are append-only,
notifications only move from unread to read (PostgreSQL triggers).
Every row carries `school`; composite foreign keys keep every reference
inside it, and a message's sender must be a participant of its conversation.
"""

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q

from common.models import TenantModel

# =============================================================================
# Notifications
# =============================================================================


class NotificationType(models.TextChoices):
    ATTENDANCE_LATE = "ATTENDANCE_LATE", "Retard"
    ATTENDANCE_ABSENT = "ATTENDANCE_ABSENT", "Absence"
    CONVOCATION = "CONVOCATION", "Convocation"
    SCHEDULE_CHANGE = "SCHEDULE_CHANGE", "Modification de planning"
    SUBSTITUTION = "SUBSTITUTION", "Remplacement d'enseignant"
    PAYMENT = "PAYMENT", "Paiement"
    REFUND = "REFUND", "Remboursement"
    PAYROLL = "PAYROLL", "Paie"
    REPORT_CARD = "REPORT_CARD", "Bulletin disponible"
    MESSAGE = "MESSAGE", "Nouveau message"
    ANNOUNCEMENT = "ANNOUNCEMENT", "Annonce"
    COMPLAINT = "COMPLAINT", "Réclamation"
    FORUM = "FORUM", "Forum"  # new topic / reply in a discussion I belong to (switchable)
    PLAN = "PLAN", "Plan de l'établissement"  # a plan version published for me (switchable)


# Types a member cannot switch off in-app: they carry obligations or money.
MANDATORY_TYPES = frozenset(
    {NotificationType.CONVOCATION, NotificationType.PAYROLL, NotificationType.COMPLAINT, NotificationType.REFUND}
)


class Severity(models.TextChoices):
    INFO = "INFO", "Information"
    WARNING = "WARNING", "Attention"
    CRITICAL = "CRITICAL", "Important"


class Notification(TenantModel):
    """In-app notification delivered to ONE membership (spec §4.6).

    Additions (ADR 0015):
    - `event_key`: identity of the business event ("payment:<id>:SUCCEEDED");
      UNIQUE(recipient, event_key) makes production idempotent (replays,
      retries, two triggers for the same fact never notify twice);
    - `source_type` / `source_id`: the business row that caused it.
    - `text`: for a SYSTEM notification, the language-neutral description of
      its title / message (texts.py: key + parameters), rendered in the
      reader's language; `title` / `message` keep the French rendering. Empty
      for rows created before it: they are shown as stored.
    Only `is_read` / `read_at` may change, once (trigger).
    """

    recipient = models.ForeignKey("accounts.SchoolMembership", on_delete=models.PROTECT, related_name="notifications")
    notification_type = models.CharField(max_length=40, choices=NotificationType.choices, db_index=True)
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.INFO, db_index=True)
    title = models.CharField(max_length=200)
    message = models.TextField()
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(blank=True, null=True)
    payload = models.JSONField(default=dict)
    text = models.JSONField(default=dict, blank=True)  # {"title": spec, "message": spec} (texts.py)
    event_key = models.CharField(max_length=200)
    source_type = models.CharField(max_length=80, blank=True, null=True)
    source_id = models.UUIDField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["recipient", "is_read", "-created_at"], name="notification_inbox_idx")]
        constraints = [
            models.UniqueConstraint(fields=["recipient", "event_key"], name="notification_event_once"),
            models.CheckConstraint(
                condition=Q(notification_type__in=NotificationType.values), name="notification_type_valid"
            ),
            models.CheckConstraint(condition=Q(severity__in=Severity.values), name="notification_severity_valid"),
            models.CheckConstraint(
                condition=(Q(is_read=False) & Q(read_at__isnull=True)) | (Q(is_read=True) & Q(read_at__isnull=False)),
                name="notification_read_consistent",
            ),
        ]


class NotificationPreference(TenantModel):
    """Per-member, per-type choice. Mandatory types stay in-app whatever the
    preference (enforced by the service)."""

    membership = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.PROTECT, related_name="notification_preferences"
    )
    notification_type = models.CharField(max_length=40, choices=NotificationType.choices)
    in_app_enabled = models.BooleanField(default=True)
    push_enabled = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["membership", "notification_type"], name="notification_pref_unique"),
            models.CheckConstraint(
                condition=Q(notification_type__in=NotificationType.values), name="notification_pref_type_valid"
            ),
        ]


class DeliveryStatus(models.TextChoices):
    PENDING = "PENDING", "À envoyer"
    SENT = "SENT", "Envoyée"
    FAILED = "FAILED", "Échec"
    CANCELLED = "CANCELLED", "Annulée"


class NotificationDelivery(TenantModel):
    """Push queue (outbox) for a future FCM worker — nothing sends it yet.
    One row per notification whose recipient accepts push for that type."""

    notification = models.OneToOneField(Notification, on_delete=models.PROTECT, related_name="delivery")
    channel = models.CharField(max_length=20, default="PUSH")
    status = models.CharField(max_length=20, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(blank=True, null=True)
    last_error = models.TextField(blank=True, null=True)
    sent_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        indexes = [models.Index(fields=["status", "next_attempt_at"], name="delivery_queue_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=DeliveryStatus.values), name="delivery_status_valid"),
        ]


# =============================================================================
# Private messaging
# =============================================================================


class ConversationType(models.TextChoices):
    ADMINISTRATION = "ADMINISTRATION", "Avec l'administration"
    PARENT_TEACHER = "PARENT_TEACHER", "Parent – enseignant"
    COMPLAINT = "COMPLAINT", "Fil de réclamation"


class Conversation(TenantModel):
    """Private conversation container (spec §4.6). `student` (addition): the
    child a parent–teacher conversation is about; it is what justifies the
    two parties talking at all."""

    conversation_type = models.CharField(max_length=20, choices=ConversationType.choices)
    title = models.CharField(max_length=160, blank=True, null=True)
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT, blank=True, null=True, related_name="+")
    created_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )
    active = models.BooleanField(default=True)
    last_message_at = models.DateTimeField(blank=True, null=True, db_index=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(conversation_type__in=ConversationType.values), name="conversation_type_valid"
            ),
            models.CheckConstraint(
                condition=~Q(conversation_type=ConversationType.PARENT_TEACHER) | Q(student__isnull=False),
                name="conversation_parent_teacher_has_student",
            ),
        ]


class ConversationParticipant(TenantModel):
    conversation = models.ForeignKey(Conversation, on_delete=models.PROTECT, related_name="participants")
    membership = models.ForeignKey("accounts.SchoolMembership", on_delete=models.PROTECT, related_name="+")
    joined_at = models.DateTimeField()
    left_at = models.DateTimeField(blank=True, null=True)
    last_read_message = models.ForeignKey(
        "communication.Message", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )
    last_read_at = models.DateTimeField(blank=True, null=True)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["conversation", "membership"], name="participant_unique"),
        ]


class Message(TenantModel):
    """Message of a conversation (spec §4.6). Never edited; "deleting" one
    hides it (deleted_at) and keeps the row. `client_id` (addition): the
    client's id for the message, so a resend after a reconnection is
    recognised instead of duplicated."""

    conversation = models.ForeignKey(Conversation, on_delete=models.PROTECT, related_name="messages")
    sender = models.ForeignKey("accounts.SchoolMembership", on_delete=models.PROTECT, related_name="+")
    body = models.TextField()
    client_id = models.CharField(max_length=64, blank=True, null=True)
    edited_at = models.DateTimeField(blank=True, null=True)
    deleted_at = models.DateTimeField(blank=True, null=True)
    deleted_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["conversation", "created_at"], name="message_conversation_idx")]
        constraints = [
            models.CheckConstraint(condition=~Q(body=""), name="message_body_required"),
            models.UniqueConstraint(
                fields=["sender", "client_id"], condition=Q(client_id__isnull=False), name="message_client_id_once"
            ),
            models.CheckConstraint(
                condition=Q(deleted_at__isnull=True) | Q(deleted_by__isnull=False), name="message_deletion_author"
            ),
        ]


# =============================================================================
# Attachments (private storage)
# =============================================================================


class AttachmentBase(TenantModel):
    """Private file (spec §4.6, §9 "never public by URL alone"). The file
    lives in the `private` storage under a random name; it is only served by
    a download endpoint that checks the permission first."""

    original_name = models.CharField(max_length=255)
    stored_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=120)
    size_bytes = models.BigIntegerField()
    storage_path = models.TextField()
    sha256 = models.CharField(max_length=64)
    uploaded_by = models.ForeignKey("accounts.SchoolMembership", on_delete=models.PROTECT, related_name="+")

    class Meta:
        abstract = True


def _attachment_constraints(prefix):
    return [
        models.CheckConstraint(condition=Q(size_bytes__gt=0), name=f"{prefix}_size_positive"),
        models.UniqueConstraint(fields=["storage_path"], name=f"{prefix}_path_unique"),
    ]


class MessageAttachment(AttachmentBase):
    message = models.ForeignKey(Message, on_delete=models.PROTECT, related_name="attachments")

    class Meta:
        constraints = _attachment_constraints("message_attachment")


# =============================================================================
# Forum / announcements
# =============================================================================


class SpaceAudience(models.TextChoices):
    SCHOOL = "SCHOOL", "Toute l'école (rôles choisis)"
    CLASS = "CLASS", "Communauté d'une classe"


FORUM_ROLES = ("TEACHER", "PARENT", "STAFF")  # spec §8: forum CR for these roles


class ForumSpace(TenantModel):
    """Group a thread belongs to (addition, ADR 0015). Who belongs is
    COMPUTED from existing data, never copied:
    - SCHOOL: members holding one of `roles`;
    - CLASS: teachers with an active course in the class and parents with a
      verified link to a pupil enrolled in it.
    Administrators always belong. `announcements_only`: only the
    administration opens threads there."""

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, null=True)
    audience = models.CharField(max_length=20, choices=SpaceAudience.choices)
    roles = ArrayField(models.CharField(max_length=30), default=list, blank=True)
    school_class = models.ForeignKey(
        "academics.SchoolClass", on_delete=models.PROTECT, blank=True, null=True, related_name="+"
    )
    announcements_only = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey("accounts.SchoolMembership", on_delete=models.PROTECT, related_name="+")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["school", "name"], name="forum_space_name_unique"),
            models.CheckConstraint(condition=Q(audience__in=SpaceAudience.values), name="forum_space_audience_valid"),
            models.CheckConstraint(
                condition=(Q(audience=SpaceAudience.CLASS) & Q(school_class__isnull=False))
                | (Q(audience=SpaceAudience.SCHOOL) & Q(school_class__isnull=True)),
                name="forum_space_class_consistent",
            ),
            models.CheckConstraint(
                condition=Q(roles__contained_by=list(FORUM_ROLES)), name="forum_space_roles_allowed"
            ),
        ]


class ThreadType(models.TextChoices):
    GENERAL = "GENERAL", "Discussion"
    ANNOUNCEMENT = "ANNOUNCEMENT", "Annonce"


class ThreadStatus(models.TextChoices):
    OPEN = "OPEN", "Ouvert"
    LOCKED = "LOCKED", "Verrouillé"
    ARCHIVED = "ARCHIVED", "Archivé"


class ForumThread(TenantModel):
    """Forum thread (spec §4.6) inside a space. Announcements are written by
    the administration only; replies to an announcement too."""

    space = models.ForeignKey(ForumSpace, on_delete=models.PROTECT, related_name="threads")
    title = models.CharField(max_length=200)
    created_by = models.ForeignKey("accounts.SchoolMembership", on_delete=models.PROTECT, related_name="+")
    thread_type = models.CharField(max_length=30, choices=ThreadType.choices, default=ThreadType.GENERAL)
    status = models.CharField(max_length=20, choices=ThreadStatus.choices, default=ThreadStatus.OPEN, db_index=True)
    status_reason = models.TextField(blank=True, null=True)
    last_post_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-last_post_at", "-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(thread_type__in=ThreadType.values), name="forum_thread_type_valid"),
            models.CheckConstraint(condition=Q(status__in=ThreadStatus.values), name="forum_thread_status_valid"),
            models.CheckConstraint(
                condition=Q(status=ThreadStatus.OPEN) | (Q(status_reason__isnull=False) & ~Q(status_reason="")),
                name="forum_thread_status_reason",
            ),
        ]


class PostType(models.TextChoices):
    MESSAGE = "MESSAGE", "Message"
    ANNOUNCEMENT = "ANNOUNCEMENT", "Annonce"


class ForumPost(TenantModel):
    """Forum post (spec §4.6). Never edited; a deletion (by its author, or a
    moderation by the administration with a reason) only hides it."""

    thread = models.ForeignKey(ForumThread, on_delete=models.PROTECT, related_name="posts")
    author = models.ForeignKey("accounts.SchoolMembership", on_delete=models.PROTECT, related_name="+")
    body = models.TextField()
    post_type = models.CharField(max_length=30, choices=PostType.choices, default=PostType.MESSAGE)
    edited_at = models.DateTimeField(blank=True, null=True)
    deleted_at = models.DateTimeField(blank=True, null=True)
    deleted_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )
    deletion_reason = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(condition=~Q(body=""), name="forum_post_body_required"),
            models.CheckConstraint(condition=Q(post_type__in=PostType.values), name="forum_post_type_valid"),
            models.CheckConstraint(
                condition=Q(deleted_at__isnull=True) | Q(deleted_by__isnull=False), name="forum_post_deletion_author"
            ),
        ]


# =============================================================================
# Complaints
# =============================================================================


class ComplaintStatus(models.TextChoices):
    DRAFT = "DRAFT", "Brouillon"
    OPEN = "OPEN", "Ouverte"
    IN_PROGRESS = "IN_PROGRESS", "En traitement"
    RESOLVED = "RESOLVED", "Résolue"
    CANCELLED = "CANCELLED", "Annulée"
    CLOSED = "CLOSED", "Clôturée"


FINAL_COMPLAINT_STATUSES = (ComplaintStatus.CANCELLED, ComplaintStatus.CLOSED)


class ComplaintCategory(models.TextChoices):
    PEDAGOGY = "PEDAGOGY", "Pédagogie"
    BEHAVIOR = "BEHAVIOR", "Comportement"
    ADMINISTRATIVE = "ADMINISTRATIVE", "Administratif"
    FINANCE = "FINANCE", "Finance"
    OTHER = "OTHER", "Autre"


class ComplaintPriority(models.TextChoices):
    LOW = "LOW", "Basse"
    NORMAL = "NORMAL", "Normale"
    HIGH = "HIGH", "Haute"
    URGENT = "URGENT", "Urgente"


class Complaint(TenantModel):
    """Complaint / request (spec §4.6) between a parent and a teacher, with
    the administration included for traceability when chosen.

    Additions (ADR 0015): `concerned_member` (the other party: the teacher a
    parent complains to, or the parent a teacher writes to),
    `include_administration`, `submitted_at`, `cancelled_at`.
    Never deleted; content frozen once submitted; CANCELLED / CLOSED final
    (trigger). Every status change is a ComplaintStatusHistory row.
    """

    author = models.ForeignKey("accounts.SchoolMembership", on_delete=models.PROTECT, related_name="complaints")
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT, blank=True, null=True, related_name="+")
    concerned_member = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.PROTECT, blank=True, null=True, related_name="+"
    )
    include_administration = models.BooleanField(default=True)
    category = models.CharField(max_length=40, choices=ComplaintCategory.choices)
    subject = models.CharField(max_length=200)
    description = models.TextField()
    priority = models.CharField(max_length=20, choices=ComplaintPriority.choices, default=ComplaintPriority.NORMAL)
    status = models.CharField(
        max_length=30, choices=ComplaintStatus.choices, default=ComplaintStatus.DRAFT, db_index=True
    )
    assigned_to = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )
    conversation = models.OneToOneField(
        Conversation, on_delete=models.SET_NULL, blank=True, null=True, related_name="complaint"
    )
    submitted_at = models.DateTimeField(blank=True, null=True)
    resolved_at = models.DateTimeField(blank=True, null=True)
    closed_at = models.DateTimeField(blank=True, null=True)
    cancelled_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=ComplaintStatus.values), name="complaint_status_valid"),
            models.CheckConstraint(condition=Q(category__in=ComplaintCategory.values), name="complaint_category_valid"),
            models.CheckConstraint(condition=Q(priority__in=ComplaintPriority.values), name="complaint_priority_valid"),
            models.CheckConstraint(condition=~Q(subject="") & ~Q(description=""), name="complaint_content_required"),
            models.CheckConstraint(
                condition=Q(status=ComplaintStatus.DRAFT)
                | Q(submitted_at__isnull=False)
                | Q(status=ComplaintStatus.CANCELLED),
                name="complaint_submitted_at",
            ),
            models.CheckConstraint(
                condition=~Q(status=ComplaintStatus.RESOLVED) | Q(resolved_at__isnull=False),
                name="complaint_resolved_at",
            ),
            models.CheckConstraint(
                condition=~Q(status=ComplaintStatus.CLOSED) | Q(closed_at__isnull=False), name="complaint_closed_at"
            ),
            models.CheckConstraint(
                condition=~Q(status=ComplaintStatus.CANCELLED) | Q(cancelled_at__isnull=False),
                name="complaint_cancelled_at",
            ),
            models.CheckConstraint(
                condition=Q(concerned_member__isnull=True) | ~Q(concerned_member=models.F("author")),
                name="complaint_not_against_self",
            ),
        ]


class ComplaintStatusHistory(TenantModel):
    """Immutable complaint workflow history (spec §4.6), creation included."""

    complaint = models.ForeignKey(Complaint, on_delete=models.PROTECT, related_name="history")
    old_status = models.CharField(max_length=30, blank=True, null=True)
    new_status = models.CharField(max_length=30)
    changed_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )
    comment = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(new_status__in=ComplaintStatus.values), name="complaint_history_status_valid"
            ),
        ]


class ComplaintAttachment(AttachmentBase):
    complaint = models.ForeignKey(Complaint, on_delete=models.PROTECT, related_name="attachments")

    class Meta:
        constraints = _attachment_constraints("complaint_attachment")
