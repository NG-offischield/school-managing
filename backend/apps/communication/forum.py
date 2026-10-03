"""Forum and announcements (spec §4.6, §8 "Forum: CR" for teachers, parents,
staff; guardians excluded; ADR 0015).

A space's members are COMPUTED from existing data (never a copied list):
SCHOOL spaces = members holding one of the space's roles; CLASS spaces =
teachers with an active course in the class + parents with a verified link
to a pupil actively enrolled in it. The administration belongs everywhere.
Announcements (thread_type ANNOUNCEMENT, or spaces flagged
announcements_only) are written by the administration only and notify the
whole space. Posts are never edited; a deletion hides them (moderation by
the administration requires a reason).
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import MembershipStatus, SchoolMembership
from apps.audit.services import record_audit
from apps.people.models import EnrollmentStatus
from common.permissions import ADMIN_ROLES, membership_has_role

from . import access
from .models import (
    FORUM_ROLES,
    ForumPost,
    ForumSpace,
    ForumThread,
    NotificationType,
    PostType,
    Severity,
    SpaceAudience,
    ThreadStatus,
    ThreadType,
)
from .notifications import notify_many

MAX_POST = 10000


def _text(value, code, limit=MAX_POST):
    value = (value or "").strip()
    if not value:
        raise ValidationError("This text is required.", code=code)
    if len(value) > limit:
        raise ValidationError(f"At most {limit} characters.", code=code)
    return value


def members_of(space):
    """Active memberships belonging to the space (administration included)."""
    active = SchoolMembership.objects.filter(school=space.school, status=MembershipStatus.ACTIVE)
    admins = Q(membership_roles__active=True, membership_roles__role__code__in=ADMIN_ROLES)
    if space.audience == SpaceAudience.SCHOOL:
        scope = Q(membership_roles__active=True, membership_roles__role__code__in=space.roles)
    else:
        scope = Q(
            employee_profile__teacher_profile__courses__school_class=space.school_class,
            employee_profile__teacher_profile__courses__active=True,
        ) | Q(
            parent_profile__children_links__active=True,
            parent_profile__children_links__identity_verified=True,
            parent_profile__children_links__student__enrollments__school_class=space.school_class,
            parent_profile__children_links__student__enrollments__status=EnrollmentStatus.ACTIVE,
        )
    return active.filter(pk__in=active.filter(scope | admins).values("pk"))


def is_member(membership, space):
    if membership is None or space.school_id != membership.school_id or not space.active:
        return False
    if access.is_admin(membership):
        return True
    if not membership_has_role(membership, set(FORUM_ROLES)):
        return False  # guardians and others: no forum (spec §8)
    return members_of(space).filter(pk=membership.pk).exists()


def visible_spaces(membership):
    spaces = ForumSpace.objects.filter(school=membership.school, active=True)
    if access.is_admin(membership):
        return ForumSpace.objects.filter(school=membership.school)
    return [space for space in spaces if is_member(membership, space)]


@transaction.atomic
def create_space(
    school, *, actor, name, audience, roles=(), school_class=None, announcements_only=False, description=None
):
    if not access.is_admin(actor, school):
        raise PermissionDenied("Only the administration creates forum spaces.")
    if school_class is not None and school_class.school_id != school.pk:
        raise PermissionDenied("Class of another school.")
    roles = sorted(set(roles))
    if audience == SpaceAudience.SCHOOL and not roles:
        raise ValidationError("Choose the roles of the space.", code="roles_required")
    if not set(roles) <= set(FORUM_ROLES):
        raise ValidationError("Invalid roles.", code="invalid_roles")
    if ForumSpace.objects.filter(school=school, name=name.strip()).exists():
        raise ValidationError("A space with this name exists.", code="duplicate_code")
    space = ForumSpace.objects.create(
        school=school,
        name=name.strip(),
        description=description,
        audience=audience,
        roles=roles if audience == SpaceAudience.SCHOOL else [],
        school_class=school_class,
        announcements_only=announcements_only,
        created_by=actor,
    )
    record_audit("FORUM_SPACE_CREATED", actor=actor, entity=space, new={"name": space.name, "audience": audience})
    return space


@transaction.atomic
def create_thread(space, *, actor, title, body, thread_type=ThreadType.GENERAL):
    if not is_member(actor, space):
        raise PermissionDenied("You are not a member of this space.")
    announcement = thread_type == ThreadType.ANNOUNCEMENT
    if (announcement or space.announcements_only) and not access.is_admin(actor):
        raise PermissionDenied("Only the administration publishes here.")
    if thread_type not in ThreadType.values:
        raise ValidationError("Invalid thread type.", code="invalid_type")
    thread = ForumThread.objects.create(
        school=space.school,
        space=space,
        title=_text(title, "title_required", 200),
        created_by=actor,
        thread_type=thread_type,
        last_post_at=timezone.now(),
    )
    ForumPost.objects.create(
        school=space.school,
        thread=thread,
        author=actor,
        body=_text(body, "body_required"),
        post_type=PostType.ANNOUNCEMENT if announcement else PostType.MESSAGE,
    )
    if announcement:
        notify_many(
            members_of(space).exclude(pk=actor.pk),
            school=space.school,
            notification_type=NotificationType.ANNOUNCEMENT,
            severity=Severity.INFO,
            title=thread.title,
            message=body.strip()[:200],
            event_key=f"announcement:{thread.pk}",
            payload={"thread": str(thread.pk), "space": str(space.pk)},
            source=thread,
        )
    return thread


@transaction.atomic
def add_post(thread, *, actor, body):
    thread = ForumThread.objects.select_for_update().get(pk=thread.pk)
    if not is_member(actor, thread.space):
        raise PermissionDenied("You are not a member of this space.")
    if thread.status != ThreadStatus.OPEN:
        raise ValidationError("This thread is not open.", code="thread_locked")
    if thread.thread_type == ThreadType.ANNOUNCEMENT and not access.is_admin(actor):
        raise PermissionDenied("Announcements are read-only.")
    post = ForumPost.objects.create(
        school=thread.school, thread=thread, author=actor, body=_text(body, "body_required")
    )
    ForumThread.objects.filter(pk=thread.pk).update(last_post_at=post.created_at)
    return post


@transaction.atomic
def delete_post(post, *, actor, reason=None):
    """Author: own post. Administration: moderation, reason required."""
    post = ForumPost.objects.select_for_update().get(pk=post.pk)
    if post.deleted_at is not None:
        raise ValidationError("Already deleted.", code="post_already_deleted")
    own = post.author_id == actor.pk
    if not own:
        if not access.is_admin(actor, post.school):
            raise PermissionDenied("You can only delete your own posts.")
        reason = _text(reason, "reason_required", 1000)
    post.deleted_at, post.deleted_by, post.deletion_reason = timezone.now(), actor, reason
    post.save(update_fields=["deleted_at", "deleted_by", "deletion_reason", "updated_at"])
    if not own:
        record_audit("FORUM_POST_MODERATED", actor=actor, entity=post, new={"reason": reason})
    return post


@transaction.atomic
def set_thread_status(thread, *, actor, status, reason=None):
    if not access.is_admin(actor, thread.school):
        raise PermissionDenied("Only the administration moderates threads.")
    if status not in ThreadStatus.values:
        raise ValidationError("Invalid status.", code="invalid_status")
    thread = ForumThread.objects.select_for_update().get(pk=thread.pk)
    old = thread.status
    thread.status = status
    thread.status_reason = None if status == ThreadStatus.OPEN else _text(reason, "reason_required", 1000)
    thread.save(update_fields=["status", "status_reason", "updated_at"])
    record_audit(
        "FORUM_THREAD_STATUS",
        actor=actor,
        entity=thread,
        old={"status": old},
        new={"status": status, "reason": thread.status_reason},
    )
    return thread
