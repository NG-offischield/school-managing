"""Private messaging (spec §4.6, §6.11, ADR 0015).

Conversation types and who may open them (spec §8 "private admin messaging:
CR admin" for teachers / parents / staff; guardians excluded):

    ADMINISTRATION   a member <-> the administration (chosen admins, or all of
                     them); an administrator may open one with any member
    PARENT_TEACHER   about ONE pupil: a parent with a verified link to that
                     pupil and a teacher who teaches that pupil
    COMPLAINT        only created by the complaint workflow (complaints.py)

Traceability: the administration of the school can read every conversation
of its school; an administrator who writes in a conversation joins it as a
visible participant (audited). Messages are never edited; "deleting" one
(own messages only) hides it, the row stays.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.accounts.models import MembershipStatus, SchoolMembership
from apps.audit.services import record_audit
from common.permissions import membership_has_role

from . import access, attachments, realtime
from .models import (
    Conversation,
    ConversationParticipant,
    ConversationType,
    Message,
    MessageAttachment,
    NotificationType,
)
from .notifications import administrators, notify_many

MAX_BODY = 5000


def _body(body):
    body = (body or "").strip()
    if not body:
        raise ValidationError("A message cannot be empty.", code="message_empty")
    if len(body) > MAX_BODY:
        raise ValidationError(f"At most {MAX_BODY} characters.", code="message_too_long")
    return body


def _same_school_members(school, members):
    members = list(members)
    for member in members:
        if member.school_id != school.pk:
            raise PermissionDenied("Members of another school.")
        if member.status != MembershipStatus.ACTIVE:
            raise ValidationError("A participant is not an active member.", code="participant_inactive")
    return members


def _require_messaging(actor):
    if not membership_has_role(actor, access.MESSAGING_ROLES):
        raise PermissionDenied("Your role cannot use private messaging.")


def _join(conversation, membership):
    participant, created = ConversationParticipant.objects.get_or_create(
        conversation=conversation,
        membership=membership,
        defaults={"school": conversation.school, "joined_at": timezone.now()},
    )
    if not participant.active:
        participant.active, participant.left_at = True, None
        participant.save()
    return participant, created


def _existing_parent_teacher(student, members):
    ids = {m.pk for m in members}
    candidates = (
        Conversation.objects.filter(conversation_type=ConversationType.PARENT_TEACHER, student=student, active=True)
        .annotate(n=Count("participants"))
        .filter(n=len(ids))
    )
    for conversation in candidates:
        if set(conversation.participants.values_list("membership_id", flat=True)) == ids:
            return conversation
    return None


@transaction.atomic
def create_conversation(
    actor, *, conversation_type, participants=(), student=None, title=None, body=None, files=(), client_id=None
):
    """Returns (conversation, created). An identical parent–teacher
    conversation about the same pupil is reused instead of duplicated."""
    _require_messaging(actor)
    school = actor.school
    others = [m for m in _same_school_members(school, participants) if m.pk != actor.pk]
    actor_is_admin = access.is_admin(actor, school)

    if conversation_type == ConversationType.ADMINISTRATION:
        if actor_is_admin:
            if not others:
                raise ValidationError("Choose at least one participant.", code="participants_required")
            for member in others:
                _require_messaging(member)
        else:
            if others and not all(access.is_admin(m, school) for m in others):
                raise PermissionDenied("Your conversations go to the administration.")
            others = others or list(administrators(school).exclude(pk=actor.pk))
            if not others:
                raise ValidationError("No administrator to write to.", code="no_administrator")
    elif conversation_type == ConversationType.PARENT_TEACHER:
        if student is None or student.school_id != school.pk:
            raise ValidationError("A pupil is required.", code="student_required")
        people = ([] if actor_is_admin else [actor]) + others
        parents = [m for m in people if access.parent_of(m, student)]
        teachers = [m for m in people if access.teaches(m, student)]
        if len(people) != 2 or len(parents) != 1 or len(teachers) != 1 or parents[0] == teachers[0]:
            raise PermissionDenied("A parent of this pupil and one of the pupil's teachers only.")
        existing = _existing_parent_teacher(student, people + ([actor] if actor_is_admin else []))
        if existing is not None:
            return existing, False
    else:
        raise ValidationError(
            "This conversation type is opened by its own workflow.", code="conversation_type_reserved"
        )

    conversation = Conversation.objects.create(
        school=school,
        conversation_type=conversation_type,
        title=(title or "").strip()[:160] or None,
        student=student,
        created_by=actor,
    )
    for member in [actor, *others]:
        _join(conversation, member)
    record_audit(
        "CONVERSATION_CREATED",
        actor=actor,
        entity=conversation,
        new={"type": conversation_type, "participants": [str(m.pk) for m in [actor, *others]]},
    )
    if body:
        send_message(conversation, actor=actor, body=body, files=files, client_id=client_id)
    return conversation, True


@transaction.atomic
def add_participant(conversation, member, *, actor):
    """The administration adds itself or a colleague (traceability), or an
    assignee of a complaint is brought in by the complaint workflow."""
    if not access.is_admin(actor, conversation.school):
        raise PermissionDenied("Only the administration adds participants.")
    _same_school_members(conversation.school, [member])
    if conversation.conversation_type != ConversationType.COMPLAINT and not access.is_admin(
        member, conversation.school
    ):
        raise PermissionDenied("Only administrators can join this conversation.")
    participant, created = _join(conversation, member)
    if created:
        record_audit("CONVERSATION_JOINED", actor=actor, entity=conversation, new={"member": str(member.pk)})
        realtime.to_conversation(
            conversation.pk,
            {"type": "participant.joined", "conversation": str(conversation.pk), "member": str(member.pk)},
        )
    return participant


def serialize_message(message, viewer=None):
    hidden = message.deleted_at is not None
    can_see_hidden = viewer is not None and access.is_admin(viewer, message.school)
    return {
        "id": str(message.pk),
        "conversation": str(message.conversation_id),
        "sender": str(message.sender_id),
        "sender_name": message.sender.user.full_name,
        "body": None if hidden and not can_see_hidden else message.body,
        "client_id": message.client_id,
        "created_at": message.created_at.isoformat(),
        "deleted_at": message.deleted_at.isoformat() if hidden else None,
        "attachments": []
        if hidden and not can_see_hidden
        else [attachments.serialize(a, "message") for a in message.attachments.all()],
    }


@transaction.atomic
def send_message(conversation, *, actor, body, files=(), client_id=None):
    """Returns (message, created). A resend with the same client_id (after a
    reconnection) returns the message already stored."""
    conversation = Conversation.objects.select_for_update().get(pk=conversation.pk)
    if not access.can_read_conversation(actor, conversation):
        raise PermissionDenied("Not a participant of this conversation.")
    if not conversation.active:
        raise ValidationError("This conversation is closed.", code="conversation_closed")
    complaint = getattr(conversation, "complaint", None)
    if complaint is not None and complaint.status in ("CANCELLED", "CLOSED"):
        raise ValidationError("This complaint is closed.", code="conversation_closed")
    if client_id:
        existing = Message.objects.filter(sender=actor, client_id=client_id).first()
        if existing is not None:
            if existing.conversation_id != conversation.pk:
                raise ValidationError("client_id already used.", code="client_id_conflict")
            return existing, False
    body = _body(body)
    inspected = attachments.validate_all(files, conversation.school)
    if access.participant(actor, conversation) is None:
        # Administrator writing in a conversation: joins it, visibly.
        add_participant(conversation, actor, actor=actor)
    try:
        with transaction.atomic():
            message = Message.objects.create(
                school=conversation.school, conversation=conversation, sender=actor, body=body, client_id=client_id
            )
    except IntegrityError:  # two resends racing on the same client_id
        return Message.objects.get(sender=actor, client_id=client_id), False
    attachments.store(MessageAttachment, inspected, school=conversation.school, uploaded_by=actor, message=message)
    now = timezone.now()
    Conversation.objects.filter(pk=conversation.pk).update(last_message_at=now, updated_at=now)
    ConversationParticipant.objects.filter(conversation=conversation, membership=actor).update(
        last_read_message=message, last_read_at=now
    )
    realtime.to_conversation(conversation.pk, {"type": "message.created", "data": serialize_message(message)})
    recipients = SchoolMembership.objects.filter(
        pk__in=conversation.participants.filter(active=True).exclude(membership=actor).values("membership_id")
    )
    notify_many(
        recipients,
        school=conversation.school,
        notification_type=NotificationType.MESSAGE,
        title=f"Message de {actor.user.full_name}",
        message=body[:200],
        event_key=f"message:{message.pk}",
        payload={"conversation": str(conversation.pk), "message": str(message.pk)},
        source=message,
    )
    return message, True


@transaction.atomic
def delete_message(message, *, actor):
    """Spec §6.11: delete OWN message only — hidden, never destroyed."""
    message = Message.objects.select_for_update().get(pk=message.pk)
    if message.sender_id != actor.pk:
        raise PermissionDenied("You can only delete your own messages.")
    if message.deleted_at is not None:
        raise ValidationError("This message is already deleted.", code="message_already_deleted")
    message.deleted_at, message.deleted_by = timezone.now(), actor
    message.save(update_fields=["deleted_at", "deleted_by", "updated_at"])
    realtime.to_conversation(
        message.conversation_id,
        {"type": "message.deleted", "message": str(message.pk), "conversation": str(message.conversation_id)},
    )
    return message


@transaction.atomic
def mark_read(conversation, *, actor):
    participant = access.participant(actor, conversation)
    if participant is None:
        raise PermissionDenied("Not a participant of this conversation.")
    last = conversation.messages.order_by("-created_at").first()
    participant.last_read_message, participant.last_read_at = last, timezone.now()
    participant.save(update_fields=["last_read_message", "last_read_at", "updated_at"])
    return participant


def unread_messages(conversation, membership):
    participant = access.participant(membership, conversation)
    messages = conversation.messages.filter(deleted_at__isnull=True).exclude(sender=membership)
    if participant is not None and participant.last_read_at is not None:
        messages = messages.filter(created_at__gt=participant.last_read_at)
    return messages.count()


def visible_conversations(membership):
    """Participants see theirs; the administration sees its school's."""
    queryset = Conversation.objects.filter(school=membership.school)
    if access.is_admin(membership):
        return queryset
    return queryset.filter(Q(participants__membership=membership, participants__active=True)).distinct()
