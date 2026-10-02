"""Business services for students, parents, teachers, staff and guardians.

Conventions:
- every write goes through a service; views (read-only in this phase) never
  write;
- actions reserved to administrators take the acting membership (`actor`)
  and check it with common.permissions.require_role — services do not trust
  their caller;
- broken business rules raise django.core.exceptions.ValidationError with a
  stable `code`; missing rights raise django.core.exceptions.PermissionDenied;
- single-row and same-school rules are also enforced by PostgreSQL.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.academics.models import AcademicYearStatus
from common.permissions import ADMIN_ROLES, membership_has_role, require_role

from .compatibility import evaluate
from .models import (
    CompatibilityOverride,
    CompatibilityResult,
    EmployeeProfile,
    EmployeeType,
    EnrollmentStatus,
    GuardianProfile,
    ParentProfile,
    ParentStudent,
    PromotionStatus,
    QualificationSource,
    QualificationStatus,
    StaffFunctionAssignment,
    StaffProfile,
    Student,
    StudentEnrollment,
    StudentStatus,
    TeacherProfile,
    TeacherSubjectQualification,
)


def _require_membership_role(membership, role):
    """A profile extends a membership that must carry the matching role."""
    if not membership_has_role(membership, {role}):
        raise ValidationError(f"The membership must be ACTIVE and hold the {role} role.", code="role_missing")


# =============================================================================
# Students & enrollments
# =============================================================================


def create_student(school, **fields):
    if fields.get("date_of_birth") and fields["date_of_birth"] >= timezone.localdate():
        raise ValidationError("The date of birth must be in the past.", code="birth_date_future")
    return Student.objects.create(school=school, **fields)


@transaction.atomic
def archive_student(student, *, actor):
    """Archive instead of delete. A student still ACTIVE in a class must
    first leave it (withdraw or end-of-year decision)."""
    require_role(actor, ADMIN_ROLES, school=student.school)
    if student.enrollments.filter(status=EnrollmentStatus.ACTIVE).exists():
        raise ValidationError("The student still has an active enrollment.", code="active_enrollment")
    student.status = StudentStatus.ARCHIVED
    student.archived_at = timezone.now()
    student.save(update_fields=["status", "archived_at", "updated_at"])
    return student


def enroll_student(student, school_class, *, enrollment_date=None):
    """Enroll a student in a class for the class's academic year.

    The year is taken from the class (the database also guarantees they
    match). One enrollment per student and year (unique constraint).
    """
    if student.status != StudentStatus.ACTIVE:
        raise ValidationError("Only an active student can be enrolled.", code="student_not_active")
    year = school_class.academic_year
    if year.status in (AcademicYearStatus.CLOSED, AcademicYearStatus.ARCHIVED):
        raise ValidationError("Enrollment in a closed year is not allowed.", code="year_closed")
    return StudentEnrollment.objects.create(
        school=student.school,
        student=student,
        academic_year=year,
        school_class=school_class,
        enrollment_date=enrollment_date or timezone.localdate(),
    )


@transaction.atomic
def decide_promotion(enrollment, decision, *, actor, note=None):
    """Record the end-of-year decision. "The software computes, the
    administration decides": this is the *human* step — only an
    administrator can call it, and the actor and date are stored.

    (Computed suggestions will come with the grades phase; they will never
    write promotion_status themselves.)
    """
    require_role(actor, ADMIN_ROLES, school=enrollment.school)
    if decision == PromotionStatus.PENDING:
        raise ValidationError("A decision cannot be PENDING.", code="decision_pending")
    if enrollment.status != EnrollmentStatus.ACTIVE:
        raise ValidationError("This enrollment is already closed.", code="enrollment_closed")
    enrollment.promotion_status = decision
    enrollment.decision_by = actor
    enrollment.decision_date = timezone.now()
    enrollment.decision_note = note
    enrollment.status = EnrollmentStatus.COMPLETED
    enrollment.end_date = enrollment.end_date or timezone.localdate()
    enrollment.save()
    return enrollment


# =============================================================================
# Parents
# =============================================================================


def create_parent_profile(membership, **fields):
    _require_membership_role(membership, "PARENT")
    return ParentProfile.objects.create(school=membership.school, membership=membership, **fields)


def link_parent(parent, student, *, relationship_type, **rights):
    """Record a DECLARED link: it grants no access until verified.
    Financial rights cannot be set yet (refused by PostgreSQL)."""
    return ParentStudent.objects.create(
        school=parent.school, parent=parent, student=student, relationship_type=relationship_type, **rights
    )


def verify_parent_link(link, *, actor, method, reference=None):
    """Mark a link as VERIFIED (simple administrative verification; the CNI /
    2FA workflow of spec §6.5 arrives in a later phase)."""
    require_role(actor, ADMIN_ROLES, school=link.school)
    link.identity_verified = True
    link.verification_method = method
    link.verification_reference = reference
    link.verified_at = timezone.now()
    link.verified_by = actor
    link.save()
    return link


# =============================================================================
# Employees, teachers, qualifications
# =============================================================================


def create_employee(membership, *, employee_number, employee_type, **fields):
    return EmployeeProfile.objects.create(
        school=membership.school,
        membership=membership,
        employee_number=employee_number,
        employee_type=employee_type,
        **fields,
    )


@transaction.atomic
def create_teacher(employee, *, pedagogical_category, primary_subject, **fields):
    """Create a teacher profile and the qualification for its primary subject.

    The primary subject goes through the same compatibility evaluation as any
    other subject: an incompatible primary subject is refused unless an
    override exists (it cannot be granted before the profile exists, so in
    practice the admin picks a compatible primary subject).
    """
    if employee.employee_type != EmployeeType.TEACHER:
        raise ValidationError("The employee must be of type TEACHER.", code="not_teacher_employee")
    _require_membership_role(employee.membership, "TEACHER")
    teacher = TeacherProfile.objects.create(
        school=employee.school,
        employee=employee,
        pedagogical_category=pedagogical_category,
        primary_subject=primary_subject,
        **fields,
    )
    declare_qualification(teacher, primary_subject)
    return teacher


class IncompatibleSubject(ValidationError):
    pass


def declare_qualification(teacher, subject, *, level=None, source=QualificationSource.DECLARATION, notes=None):
    """A teacher declares a subject.

    - COMPATIBLE / OVERRIDDEN -> stored as DECLARED (an admin still verifies);
    - REQUIRES_REVIEW         -> stored as PENDING (admin review required);
    - INCOMPATIBLE            -> refused, nothing stored (IncompatibleSubject).
    """
    evaluation = evaluate(teacher, subject, level)
    if evaluation.result == CompatibilityResult.INCOMPATIBLE:
        raise IncompatibleSubject(
            "This subject is incompatible with the teacher's pedagogical category.", code="incompatible_subject"
        )
    status = (
        QualificationStatus.PENDING
        if evaluation.result == CompatibilityResult.REQUIRES_REVIEW
        else QualificationStatus.DECLARED
    )
    if evaluation.result == CompatibilityResult.OVERRIDDEN:
        source = QualificationSource.OVERRIDE
    return TeacherSubjectQualification.objects.create(
        school=teacher.school,
        teacher=teacher,
        subject=subject,
        status=status,
        source=source,
        computed_compatibility=evaluation.result,
        notes=notes,
    )


def verify_qualification(qualification, *, actor):
    """Administrative confirmation (the final decision belongs to a human)."""
    require_role(actor, ADMIN_ROLES, school=qualification.school)
    if qualification.status == QualificationStatus.REJECTED:
        raise ValidationError("A rejected qualification must be declared again.", code="qualification_rejected")
    qualification.status = QualificationStatus.VERIFIED
    qualification.verified = True
    qualification.verified_by = actor
    qualification.verified_at = timezone.now()
    qualification.save()
    return qualification


def reject_qualification(qualification, *, actor, reason):
    require_role(actor, ADMIN_ROLES, school=qualification.school)
    if not reason:
        raise ValidationError("A reason is required to reject a qualification.", code="reason_required")
    qualification.status = QualificationStatus.REJECTED
    qualification.verified = False
    qualification.notes = reason
    qualification.save()
    return qualification


def grant_compatibility_override(teacher, subject, *, actor, reason, level=None, expires_at=None):
    """Audited exception: actor + reason + timestamp + scope (spec §9)."""
    require_role(actor, ADMIN_ROLES, school=teacher.school)
    if not reason or not reason.strip():
        raise ValidationError("An override requires a reason.", code="reason_required")
    return CompatibilityOverride.objects.create(
        school=teacher.school,
        teacher=teacher,
        subject=subject,
        level=level,
        approved_by=actor,
        reason=reason.strip(),
        expires_at=expires_at,
    )


# =============================================================================
# Staff
# =============================================================================


def create_staff(employee, *, staff_number):
    if employee.employee_type != EmployeeType.STAFF:
        raise ValidationError("The employee must be of type STAFF.", code="not_staff_employee")
    _require_membership_role(employee.membership, "STAFF")
    return StaffProfile.objects.create(school=employee.school, employee=employee, staff_number=staff_number)


def assign_staff_function(staff, function, *, actor):
    """Give a function to a staff member. Several functions may be held at
    once; holding the same one twice at the same time is refused by
    PostgreSQL (partial unique index)."""
    require_role(actor, ADMIN_ROLES, school=staff.school)
    return StaffFunctionAssignment.objects.create(
        school=staff.school, staff=staff, function=function, assigned_by=actor
    )


def end_staff_function(assignment, *, actor):
    """End a function; the row is kept as history."""
    require_role(actor, ADMIN_ROLES, school=assignment.school)
    assignment.active = False
    assignment.ended_at = timezone.now()
    assignment.save(update_fields=["active", "ended_at", "updated_at"])
    return assignment


# =============================================================================
# Guardians
# =============================================================================


def create_guardian(membership, *, guardian_number):
    _require_membership_role(membership, "GUARDIAN")
    return GuardianProfile.objects.create(
        school=membership.school, membership=membership, guardian_number=guardian_number
    )
