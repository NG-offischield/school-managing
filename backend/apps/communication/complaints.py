"""Complaints / requests (spec §4.6, §6.11, §8, ADR 0015).

    DRAFT ──submit──> OPEN ──> IN_PROGRESS ──> RESOLVED ──> CLOSED
      │                │            │             │
      └──cancel──> CANCELLED <──────┘             └──reopen──> IN_PROGRESS

Who (spec §8: parent "CR own", teacher "CR parent/teacher scope", staff
"R/CR assigned", admin CRUD):
- a PARENT files about a pupil they have a verified link to, with the
  link's `can_submit_complaints` right; the concerned member (optional) is
  one of the pupil's teachers;
- a TEACHER files about a pupil they teach; the concerned member (optional)
  is a verified parent of that pupil;
- the administration may file too, sees every complaint and drives it;
- the assignee (any member chosen by the administration) and the concerned
  member may take it IN_PROGRESS and RESOLVE it;
- the author may cancel while unprocessed (DRAFT / OPEN), confirm (CLOSE) or
  reopen a resolved complaint.

A reason is mandatory for every important decision (resolve, close, reopen,
cancel after submission). Nothing is ever deleted: cancellation is a status,
content is frozen once submitted (trigger), every change is an immutable
ComplaintStatusHistory row. On submission a COMPLAINT conversation opens
between author, concerned member, assignee and — when chosen for
traceability — the administration.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit.services import record_audit
from common.permissions import membership_has_role

from . import access, attachments, messaging
from .models import (
    FINAL_COMPLAINT_STATUSES,
    Complaint,
    ComplaintAttachment,
    ComplaintCategory,
    ComplaintPriority,
    ComplaintStatus,
    ComplaintStatusHistory,
    Conversation,
    ConversationType,
    NotificationType,
    Severity,
)
from .notifications import administrators, notify_many
from .texts import label, text

S = ComplaintStatus


def _text(value, code, limit):
    value = (value or "").strip()
    if not value:
        raise ValidationError("This field is required.", code=code)
    return value[:limit]


def _reason(reason):
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("A reason is required for this decision.", code="reason_required")
    return reason


def can_view(membership, complaint):
    """A draft belongs to its author only; once submitted: author, concerned
    member, assignee and the administration of the school."""
    if membership is None or complaint.school_id != membership.school_id:
        return False
    if complaint.author_id == membership.pk:
        return True
    if complaint.status == S.DRAFT:
        return False
    return access.is_admin(membership) or membership.pk in (complaint.concerned_member_id, complaint.assigned_to_id)


def visible_complaints(membership):
    queryset = Complaint.objects.filter(school=membership.school)
    mine = Q(author=membership)
    submitted = ~Q(status=S.DRAFT)
    if access.is_admin(membership):
        return queryset.filter(mine | submitted)
    return queryset.filter(mine | (submitted & (Q(concerned_member=membership) | Q(assigned_to=membership))))


def _history(complaint, old, new, actor, comment=None):
    ComplaintStatusHistory.objects.create(
        school=complaint.school,
        complaint=complaint,
        old_status=old,
        new_status=new,
        changed_by=actor,
        comment=comment,
    )


def _parties(complaint):
    parties = {m for m in (complaint.author, complaint.concerned_member, complaint.assigned_to) if m is not None}
    if complaint.include_administration:
        parties |= set(administrators(complaint.school))
    return parties


def _notify(complaint, actor, title, message):
    notify_many(
        [m for m in _parties(complaint) if m.pk != actor.pk],
        school=complaint.school,
        notification_type=NotificationType.COMPLAINT,
        severity=Severity.WARNING
        if complaint.priority in (ComplaintPriority.HIGH, ComplaintPriority.URGENT)
        else Severity.INFO,
        title=title,
        message=message,
        event_key=f"complaint:{complaint.pk}:{complaint.history.count()}",
        payload={"complaint": str(complaint.pk), "status": complaint.status},
        source=complaint,
    )


def _check_parties(actor, student, concerned):
    school = actor.school
    if student is not None and student.school_id != school.pk:
        raise PermissionDenied("Pupil of another school.")
    if concerned is not None and concerned.school_id != school.pk:
        raise PermissionDenied("Member of another school.")
    if access.is_admin(actor, school):
        return
    if (
        membership_has_role(actor, {"PARENT"})
        and student is not None
        and access.parent_of(actor, student, right="can_submit_complaints")
    ):
        if concerned is not None and not access.teaches(concerned, student):
            raise PermissionDenied("The concerned member must teach this pupil.")
        return
    if membership_has_role(actor, {"TEACHER"}) and (student is None or access.teaches(actor, student)):
        if concerned is not None and (student is None or not access.parent_of(concerned, student)):
            raise PermissionDenied("The concerned member must be a verified parent of this pupil.")
        return
    raise PermissionDenied("You cannot file a complaint in this scope.")


@transaction.atomic
def create_complaint(
    actor,
    *,
    category,
    subject,
    description,
    student=None,
    concerned_member=None,
    include_administration=True,
    priority=ComplaintPriority.NORMAL,
    submit=False,
):
    _check_parties(actor, student, concerned_member)
    if category not in ComplaintCategory.values or priority not in ComplaintPriority.values:
        raise ValidationError("Invalid category or priority.", code="invalid_choice")
    if not include_administration and concerned_member is None:
        raise ValidationError("Somebody must receive the complaint.", code="complaint_without_recipient")
    complaint = Complaint.objects.create(
        school=actor.school,
        author=actor,
        student=student,
        concerned_member=concerned_member,
        include_administration=include_administration,
        category=category,
        subject=_text(subject, "subject_required", 200),
        description=_text(description, "description_required", 10000),
        priority=priority,
    )
    _history(complaint, None, S.DRAFT, actor)
    if submit:
        submit_complaint(complaint, actor=actor)
        complaint.refresh_from_db()
    return complaint


@transaction.atomic
def update_draft(complaint, *, actor, **fields):
    complaint = Complaint.objects.select_for_update().get(pk=complaint.pk)
    if complaint.author_id != actor.pk:
        raise PermissionDenied("Only the author edits a draft.")
    if complaint.status != S.DRAFT:
        raise ValidationError("A submitted complaint is never rewritten.", code="complaint_not_draft")
    for key in ("subject", "description", "category", "priority"):
        if fields.get(key) is not None:
            setattr(complaint, key, fields[key].strip() if isinstance(fields[key], str) else fields[key])
    complaint.save()
    return complaint


@transaction.atomic
def submit_complaint(complaint, *, actor):
    complaint = Complaint.objects.select_for_update().get(pk=complaint.pk)
    if complaint.author_id != actor.pk:
        raise PermissionDenied("Only the author submits a complaint.")
    if complaint.status != S.DRAFT:
        raise ValidationError("Already submitted.", code="complaint_not_draft")
    complaint.status, complaint.submitted_at = S.OPEN, timezone.now()
    conversation = Conversation.objects.create(
        school=complaint.school,
        conversation_type=ConversationType.COMPLAINT,
        title=complaint.subject[:160],
        student=complaint.student,
        created_by=actor,
    )
    for member in _parties(complaint):
        messaging._join(conversation, member)
    complaint.conversation = conversation
    complaint.save()
    _history(complaint, S.DRAFT, S.OPEN, actor)
    _notify(complaint, actor, text("complaint.new.title", subject=complaint.subject), complaint.description[:200])
    return complaint


# (from, to) -> who may do it: "admin", "assignee", "concerned", "author"
TRANSITIONS = {
    (S.OPEN, S.IN_PROGRESS): {"admin", "assignee", "concerned"},
    (S.OPEN, S.RESOLVED): {"admin", "assignee", "concerned"},
    (S.IN_PROGRESS, S.RESOLVED): {"admin", "assignee", "concerned"},
    (S.RESOLVED, S.CLOSED): {"admin", "author"},
    (S.RESOLVED, S.IN_PROGRESS): {"admin", "author"},  # reopen
}
REASON_REQUIRED = {S.RESOLVED, S.CLOSED, S.CANCELLED}


def _roles(actor, complaint):
    roles = set()
    if access.is_admin(actor, complaint.school):
        roles.add("admin")
    if complaint.assigned_to_id == actor.pk:
        roles.add("assignee")
    if complaint.concerned_member_id == actor.pk:
        roles.add("concerned")
    if complaint.author_id == actor.pk:
        roles.add("author")
    return roles


@transaction.atomic
def change_status(complaint, *, actor, status, reason=None):
    complaint = Complaint.objects.select_for_update().get(pk=complaint.pk)
    if not can_view(actor, complaint):
        raise PermissionDenied("Not your complaint.")
    if status == S.CANCELLED:
        return cancel_complaint(complaint, actor=actor, reason=reason)
    if complaint.status in FINAL_COMPLAINT_STATUSES:
        raise ValidationError("This complaint is final.", code="complaint_final")
    allowed = TRANSITIONS.get((complaint.status, status))
    if allowed is None:
        raise ValidationError(f"{complaint.status} -> {status} is not allowed.", code="invalid_transition")
    if not (allowed & _roles(actor, complaint)):
        raise PermissionDenied("You cannot take this decision.")
    reopen = complaint.status == S.RESOLVED and status == S.IN_PROGRESS
    comment = _reason(reason) if status in REASON_REQUIRED or reopen else (reason or None)
    old = complaint.status
    complaint.status = status
    now = timezone.now()
    if status == S.RESOLVED:
        complaint.resolved_at = now
    if status == S.CLOSED:
        complaint.closed_at = now
    if reopen:
        complaint.resolved_at = None
    complaint.save()
    _history(complaint, old, status, actor, comment)
    _notify(
        complaint,
        actor,
        text("complaint.status.title", status=label("complaint_status", complaint.status, lower=True)),
        comment or complaint.subject,
    )
    return complaint


@transaction.atomic
def cancel_complaint(complaint, *, actor, reason=None):
    """Cancellation, never deletion. The author cancels an unprocessed
    complaint (DRAFT / OPEN); the administration any non-final one."""
    complaint = Complaint.objects.select_for_update().get(pk=complaint.pk)
    if complaint.status in FINAL_COMPLAINT_STATUSES:
        raise ValidationError("This complaint is final.", code="complaint_final")
    roles = _roles(actor, complaint)
    if "admin" not in roles and not ("author" in roles and complaint.status in (S.DRAFT, S.OPEN)):
        raise PermissionDenied("You cannot cancel this complaint.")
    comment = reason.strip() if reason and reason.strip() else None
    if complaint.status != S.DRAFT:
        comment = _reason(reason)
    old = complaint.status
    complaint.status, complaint.cancelled_at = S.CANCELLED, timezone.now()
    complaint.save()
    _history(complaint, old, S.CANCELLED, actor, comment)
    if old != S.DRAFT:
        _notify(complaint, actor, text("complaint.cancelled.title"), comment)
    return complaint


@transaction.atomic
def assign(complaint, *, actor, assignee, reason=None):
    complaint = Complaint.objects.select_for_update().get(pk=complaint.pk)
    if not access.is_admin(actor, complaint.school):
        raise PermissionDenied("Only the administration assigns complaints.")
    if assignee.school_id != complaint.school_id:
        raise PermissionDenied("Member of another school.")
    if complaint.status == S.DRAFT or complaint.status in FINAL_COMPLAINT_STATUSES:
        raise ValidationError("Only an open complaint can be assigned.", code="complaint_not_open")
    complaint.assigned_to = assignee
    complaint.save(update_fields=["assigned_to", "updated_at"])
    if complaint.conversation_id:
        messaging._join(complaint.conversation, assignee)
    _history(
        complaint,
        complaint.status,
        complaint.status,
        actor,
        f"Assignée à {assignee.user.full_name}" + (f" — {reason.strip()}" if reason and reason.strip() else ""),
    )
    _notify(complaint, actor, text("complaint.assigned.title"), complaint.subject)
    return complaint


@transaction.atomic
def add_attachments(complaint, *, actor, files):
    complaint = Complaint.objects.select_for_update().get(pk=complaint.pk)
    if not can_view(actor, complaint):
        raise PermissionDenied("Not your complaint.")
    if complaint.status in FINAL_COMPLAINT_STATUSES:
        raise ValidationError("This complaint is final.", code="complaint_final")
    inspected = attachments.validate_all(files, complaint.school)
    if not inspected:
        raise ValidationError("No file.", code="attachment_empty")
    created = attachments.store(
        ComplaintAttachment, inspected, school=complaint.school, uploaded_by=actor, complaint=complaint
    )
    record_audit(
        "COMPLAINT_ATTACHMENT_ADDED", actor=actor, entity=complaint, new={"files": [a.original_name for a in created]}
    )
    return created
