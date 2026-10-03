"""Who may talk to whom (spec §8, ADR 0015) — shared by REST and WebSocket
so both enforce exactly the same rules (spec §9).

Relations are read from the existing domains, never copied:
- a parent "has" a pupil through an ACTIVE + VERIFIED ParentStudent link;
- a teacher "teaches" a pupil through an ACTIVE course of the class the
  pupil is actively enrolled in (gradebook.Course, people.StudentEnrollment).
"""

from apps.gradebook.models import Course
from apps.people.models import EnrollmentStatus, ParentStudent
from common.permissions import ADMIN_ROLES, membership_has_role

from .models import ConversationParticipant

MESSAGING_ROLES = frozenset({"TEACHER", "PARENT", "STAFF", *ADMIN_ROLES})  # spec §8: guardians excluded


def is_admin(membership, school=None):
    return (
        membership is not None
        and (school is None or membership.school_id == school.pk)
        and membership_has_role(membership, ADMIN_ROLES)
    )


def parent_of(membership, student, right=None):
    links = ParentStudent.objects.filter(
        parent__membership=membership, student=student, active=True, identity_verified=True
    )
    if right:
        links = links.filter(**{right: True})
    return membership_has_role(membership, {"PARENT"}) and links.exists()


def teaches(membership, student):
    return (
        membership_has_role(membership, {"TEACHER"})
        and Course.objects.filter(
            active=True,
            teacher__employee__membership=membership,
            school_class__enrollments__student=student,
            school_class__enrollments__status=EnrollmentStatus.ACTIVE,
        ).exists()
    )


def participant(membership, conversation):
    return ConversationParticipant.objects.filter(conversation=conversation, membership=membership, active=True).first()


def can_read_conversation(membership, conversation):
    """Active participants; the school's administration for traceability
    (spec §8: admin CRUD on messaging). Never across schools."""
    if membership is None or conversation.school_id != membership.school_id:
        return False
    return participant(membership, conversation) is not None or is_admin(membership)
