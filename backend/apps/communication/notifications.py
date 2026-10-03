"""Notification services (ADR 0015).

`notify()` is the ONLY way a notification is created:
- explicit recipient (one membership), in the SAME school as the event;
- idempotent: UNIQUE(recipient, event_key) — replaying an event, or two
  triggers for the same fact, never notify twice;
- preferences: a non-mandatory type can be switched off in-app or for push;
- push queue: a PENDING NotificationDelivery for the future FCM worker;
- real-time: pushed on the member's WebSocket group after commit.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import MembershipStatus, SchoolMembership
from common.permissions import ADMIN_ROLES

from . import realtime
from .models import (
    MANDATORY_TYPES,
    Notification,
    NotificationDelivery,
    NotificationPreference,
    NotificationType,
    Severity,
)


def serialize(notification):
    return {
        "id": str(notification.pk),
        "notification_type": notification.notification_type,
        "severity": notification.severity,
        "title": notification.title,
        "message": notification.message,
        "payload": notification.payload,
        "is_read": notification.is_read,
        "read_at": notification.read_at.isoformat() if notification.read_at else None,
        "created_at": notification.created_at.isoformat(),
    }


def preference(membership, notification_type):
    pref = NotificationPreference.objects.filter(membership=membership, notification_type=notification_type).first()
    in_app = True if pref is None else pref.in_app_enabled
    push = True if pref is None else pref.push_enabled
    if notification_type in MANDATORY_TYPES:
        in_app = True
    return in_app, push


def notify(
    recipient,
    *,
    school,
    notification_type,
    title,
    message,
    event_key,
    severity=Severity.INFO,
    payload=None,
    source=None,
):
    """Create (once) the notification of `event_key` for `recipient`.
    Returns the new Notification, or None when nothing was created
    (already notified, inactive member, or switched off by preference)."""
    if recipient.school_id != school.pk:
        # A notification never crosses schools — even a programming error
        # must not deliver another school's event.
        raise PermissionDenied("Cross-school notification refused.")
    if recipient.status != MembershipStatus.ACTIVE:
        return None
    in_app, push = preference(recipient, notification_type)
    if not in_app:
        return None
    try:
        with transaction.atomic():
            notification = Notification.objects.create(
                school=school,
                recipient=recipient,
                notification_type=notification_type,
                severity=severity,
                title=title[:200],
                message=message,
                payload=payload or {},
                event_key=event_key,
                source_type=source._meta.label if source is not None else None,
                source_id=source.pk if source is not None else None,
            )
    except IntegrityError:
        return None  # this event was already notified to this member
    if push:
        NotificationDelivery.objects.create(school=school, notification=notification)
    realtime.to_member(recipient.pk, {"type": "notification", "data": serialize(notification)})
    return notification


def notify_many(recipients, **kwargs):
    seen, created = set(), []
    for recipient in recipients:
        if recipient.pk in seen:
            continue
        seen.add(recipient.pk)
        notification = notify(recipient, **kwargs)
        if notification is not None:
            created.append(notification)
    return created


# --- Recipients --------------------------------------------------------------


def active_members(school):
    return SchoolMembership.objects.filter(school=school, status=MembershipStatus.ACTIVE)


def administrators(school):
    return (
        active_members(school)
        .filter(membership_roles__active=True, membership_roles__role__code__in=ADMIN_ROLES)
        .distinct()
    )


def parents_to_inform(student):
    """Parents with an ACTIVE, VERIFIED link to the pupil that accepts
    notifications (ParentStudent.can_receive_notifications). All conditions
    apply to the SAME link (one filter call)."""
    return (
        active_members(student.school)
        .filter(
            parent_profile__children_links__student=student,
            parent_profile__children_links__active=True,
            parent_profile__children_links__identity_verified=True,
            parent_profile__children_links__can_receive_notifications=True,
        )
        .distinct()
    )


# --- Inbox operations ----------------------------------------------------------


@transaction.atomic
def mark_read(notification, *, actor):
    if notification.recipient_id != actor.pk:
        raise PermissionDenied("Not your notification.")
    notification = Notification.objects.select_for_update().get(pk=notification.pk)
    if not notification.is_read:
        notification.is_read, notification.read_at = True, timezone.now()
        notification.save(update_fields=["is_read", "read_at", "updated_at"])
    return notification


@transaction.atomic
def mark_all_read(actor):
    return Notification.objects.filter(recipient=actor, is_read=False).update(
        is_read=True, read_at=timezone.now(), updated_at=timezone.now()
    )


def unread_count(actor):
    return Notification.objects.filter(recipient=actor, is_read=False).count()


@transaction.atomic
def set_preference(actor, notification_type, *, in_app_enabled=None, push_enabled=None):
    if notification_type not in NotificationType.values:
        raise ValidationError("Unknown notification type.", code="invalid_type")
    if in_app_enabled is False and notification_type in MANDATORY_TYPES:
        raise ValidationError("This notification cannot be switched off.", code="notification_mandatory")
    pref, _ = NotificationPreference.objects.get_or_create(
        membership=actor, notification_type=notification_type, defaults={"school": actor.school}
    )
    if in_app_enabled is not None:
        pref.in_app_enabled = in_app_enabled
    if push_enabled is not None:
        pref.push_enabled = push_enabled
    pref.save()
    return pref
