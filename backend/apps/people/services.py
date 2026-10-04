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

from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.academics.models import AcademicYearStatus
from apps.audit.services import snapshot
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
    Sex,
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
# Students administration (admin desktop: Gestion académique → Élèves, ADR 0018)
# =============================================================================
# The person (Student) and the schooling (StudentEnrollment) stay separate:
# a student is created once; each year they are enrolled in ONE class of that
# year (unique per student and year). A class change inside the year moves
# the same enrollment to another class of the same year — never to another
# year, never to another school — and is written to the audit trail, which
# is the history shown on the student's record. Nothing is deleted: a
# student is archived (and can be reactivated), an enrollment is withdrawn.
#
# Matricule (student_number) and registration number are typed by the
# school (no generator exists in the spec); their uniqueness per school is
# checked here (clear 409) and guaranteed by PostgreSQL.

STUDENT_FIELDS = [
    "student_number",
    "registration_number",
    "first_name",
    "last_name",
    "date_of_birth",
    "sex",
    "birth_place",
    "address",
    "height_cm",
    "status",
]
STUDENT_EDITABLE = [f for f in STUDENT_FIELDS if f != "status"]
OPEN_YEARS = (AcademicYearStatus.PLANNED, AcademicYearStatus.ACTIVE)
OLDEST_BIRTH_DATE = date(1900, 1, 1)


def _audit_student(action, actor, entity, old=None, new=None):
    from apps.audit.services import record_audit

    record_audit(action, actor=actor, entity=entity, old=old, new=new)


def _text(value, field, *, required=False):
    value = (value or "").strip()
    if required and not value:
        raise ValidationError(f"{field} is required.", code=f"{field}_required")
    return value


def _check_identity(fields):
    """Normalise and check the identity fields present in `fields`."""
    clean = dict(fields)
    for name in ("student_number", "registration_number", "first_name", "last_name"):
        if name in clean:
            clean[name] = _text(clean[name], name, required=True)
    for name in ("birth_place", "address"):
        if name in clean:
            clean[name] = _text(clean[name], name) or None
    born = clean.get("date_of_birth")
    if "date_of_birth" in clean:
        if born is None:
            raise ValidationError("The date of birth is required.", code="date_of_birth_required")
        if born >= timezone.localdate():
            raise ValidationError("The date of birth must be in the past.", code="birth_date_future")
        if born < OLDEST_BIRTH_DATE:
            raise ValidationError("This date of birth is not plausible.", code="birth_date_invalid")
    if "sex" in clean and clean["sex"] not in Sex.values:
        raise ValidationError("Unknown sex.", code="sex_invalid")
    height = clean.get("height_cm")
    if height is not None and not 30 <= height <= 250:
        raise ValidationError("The height must be between 30 and 250 cm.", code="height_invalid")
    return clean


def _unique_numbers(school, fields, exclude=None):
    for name, rule in (
        ("student_number", "duplicate_student_number"),
        ("registration_number", "duplicate_registration_number"),
    ):
        if name not in fields:
            continue
        duplicates = Student.objects.filter(school=school, **{f"{name}__iexact": fields[name]})
        if exclude is not None:
            duplicates = duplicates.exclude(pk=exclude.pk)
        if duplicates.exists():
            raise ValidationError(f"{fields[name]} is already used by another student.", code=rule)


def _check_class_for(student, school_class):
    """The class must be of the student's school, active, in an open year."""
    if school_class is None:
        raise ValidationError("Choose a class.", code="class_required")
    if school_class.school_id != student.school_id:
        # The API never gets here (another school's id is a 404): defence in depth.
        raise ValidationError("The class belongs to another school.", code="class_other_school")
    if not school_class.active:
        raise ValidationError("This class is inactive.", code="class_inactive")
    if school_class.academic_year.status not in OPEN_YEARS:
        raise ValidationError("This academic year is closed.", code="year_closed")


def _check_room_left(school_class, moving=None):
    """Capacity of the class (if set) counts every non-withdrawn enrollment,
    like the planning rules do."""
    if not school_class.capacity:
        return
    taken = StudentEnrollment.objects.filter(school_class=school_class).exclude(status=EnrollmentStatus.WITHDRAWN)
    if moving is not None:
        taken = taken.exclude(pk=moving.pk)
    if taken.count() >= school_class.capacity:
        raise ValidationError(
            f"The class {school_class.name} is full ({school_class.capacity} places).", code="class_full"
        )


def _enrollment_data(enrollment):
    return {
        "academic_year": str(enrollment.academic_year_id),
        "academic_year_name": enrollment.academic_year.name,
        "school_class": str(enrollment.school_class_id),
        "class_name": enrollment.school_class.name,
        "status": enrollment.status,
    }


@transaction.atomic
def admin_create_student(school, *, actor, enrollment=None, **fields):
    """Create a student; `enrollment` = {"school_class", "enrollment_date"?}
    enrolls them in the same transaction (both or nothing)."""
    require_role(actor, ADMIN_ROLES, school=school)
    missing = [
        f
        for f in ("student_number", "registration_number", "first_name", "last_name", "date_of_birth", "sex")
        if f not in fields
    ]
    if missing:
        raise ValidationError(f"Missing fields: {', '.join(missing)}.", code="fields_required")
    fields = _check_identity({k: v for k, v in fields.items() if k in STUDENT_EDITABLE})
    _unique_numbers(school, fields)
    student = Student.objects.create(school=school, **fields)
    _audit_student("STUDENT_CREATED", actor, student, new=snapshot(student, STUDENT_FIELDS))
    if enrollment:
        admin_enroll_student(
            student, enrollment["school_class"], actor=actor, enrollment_date=enrollment.get("enrollment_date")
        )
    return student


@transaction.atomic
def admin_update_student(student, *, actor, **changes):
    """Editable: identity and administrative fields. Not the status (archive /
    reactivate) and not an archived student (reactivate first)."""
    require_role(actor, ADMIN_ROLES, school=student.school)
    student = Student.objects.select_for_update().get(pk=student.pk)
    if student.status == StudentStatus.ARCHIVED:
        raise ValidationError("An archived student cannot be modified.", code="student_archived")
    changes = _check_identity({k: v for k, v in changes.items() if k in STUDENT_EDITABLE})
    _unique_numbers(student.school, changes, exclude=student)
    old = snapshot(student, STUDENT_FIELDS)
    for name, value in changes.items():
        setattr(student, name, value)
    student.save()
    _audit_student("STUDENT_UPDATED", actor, student, old=old, new=snapshot(student, STUDENT_FIELDS))
    return student


@transaction.atomic
def admin_archive_student(student, *, actor):
    """archive_student + audit. Refused (409 active_enrollment) while the
    student is still active in a class: withdraw the enrollment first.
    Grades, report cards, attendance, QR codes, invoices and documents all
    stay (PROTECT foreign keys); the student only leaves the active lists."""
    old = snapshot(student, STUDENT_FIELDS)
    student = archive_student(student, actor=actor)
    _audit_student("STUDENT_ARCHIVED", actor, student, old=old, new=snapshot(student, STUDENT_FIELDS))
    return student


@transaction.atomic
def admin_reactivate_student(student, *, actor):
    require_role(actor, ADMIN_ROLES, school=student.school)
    student = Student.objects.select_for_update().get(pk=student.pk)
    if student.status == StudentStatus.ACTIVE:
        return student
    old = snapshot(student, STUDENT_FIELDS)
    student.status = StudentStatus.ACTIVE
    student.archived_at = None
    student.save(update_fields=["status", "archived_at", "updated_at"])
    _audit_student("STUDENT_REACTIVATED", actor, student, old=old, new=snapshot(student, STUDENT_FIELDS))
    return student


@transaction.atomic
def admin_enroll_student(student, school_class, *, actor, enrollment_date=None):
    """Enroll in a class (its year is the enrollment's year). One enrollment
    per student and year (409 already_enrolled), class full (409 class_full)."""
    require_role(actor, ADMIN_ROLES, school=student.school)
    student = Student.objects.select_for_update().get(pk=student.pk)
    if student.status != StudentStatus.ACTIVE:
        raise ValidationError("Only an active student can be enrolled.", code="student_not_active")
    _check_class_for(student, school_class)
    year = school_class.academic_year
    if StudentEnrollment.objects.filter(student=student, academic_year=year).exists():
        raise ValidationError(f"The student is already enrolled in {year.name}.", code="already_enrolled")
    if enrollment_date is not None and not year.start_date <= enrollment_date <= year.end_date:
        raise ValidationError("The enrollment date must lie within the academic year.", code="date_outside_year")
    _check_room_left(school_class)
    enrollment = enroll_student(student, school_class, enrollment_date=enrollment_date or _default_date(year))
    _audit_student("STUDENT_ENROLLED", actor, enrollment, new=_enrollment_data(enrollment))
    return enrollment


def _default_date(year):
    """Today, kept inside the year (an enrollment prepared before the year starts)."""
    today = timezone.localdate()
    return min(max(today, year.start_date), year.end_date)


@transaction.atomic
def admin_change_class(enrollment, school_class, *, actor):
    """Move an ACTIVE enrollment to another class of the SAME year. Grades,
    attendance and documents already recorded stay where they were made
    (history); the student follows the new class from now on."""
    require_role(actor, ADMIN_ROLES, school=enrollment.school)
    enrollment = (
        StudentEnrollment.objects.select_for_update()
        .select_related("academic_year", "school_class")
        .get(pk=enrollment.pk)
    )
    if enrollment.status != EnrollmentStatus.ACTIVE:
        raise ValidationError("This enrollment is closed.", code="enrollment_closed")
    _check_class_for(enrollment.student, school_class)
    if school_class.academic_year_id != enrollment.academic_year_id:
        raise ValidationError("The new class belongs to another academic year.", code="class_other_year")
    if school_class.pk == enrollment.school_class_id:
        raise ValidationError("The student is already in this class.", code="same_class")
    _check_room_left(school_class, moving=enrollment)
    old = _enrollment_data(enrollment)
    enrollment.school_class = school_class
    enrollment.save(update_fields=["school_class", "updated_at"])
    _audit_student("STUDENT_CLASS_CHANGED", actor, enrollment, old=old, new=_enrollment_data(enrollment))
    return enrollment


@transaction.atomic
def admin_withdraw_enrollment(enrollment, *, actor, end_date=None):
    """The student leaves the class during the year (status WITHDRAWN, end
    date). The enrollment stays in the history."""
    require_role(actor, ADMIN_ROLES, school=enrollment.school)
    enrollment = (
        StudentEnrollment.objects.select_for_update()
        .select_related("academic_year", "school_class")
        .get(pk=enrollment.pk)
    )
    if enrollment.status != EnrollmentStatus.ACTIVE:
        raise ValidationError("This enrollment is closed.", code="enrollment_closed")
    # Default: today — but never before the enrollment date (an enrollment
    # prepared for a year that has not started yet ends the day it starts).
    end_date = end_date or max(timezone.localdate(), enrollment.enrollment_date)
    if end_date < enrollment.enrollment_date:
        raise ValidationError("The withdrawal date is before the enrollment date.", code="withdraw_before_enrollment")
    old = _enrollment_data(enrollment)
    enrollment.status = EnrollmentStatus.WITHDRAWN
    enrollment.end_date = end_date
    enrollment.save(update_fields=["status", "end_date", "updated_at"])
    _audit_student("STUDENT_WITHDRAWN", actor, enrollment, old=old, new=_enrollment_data(enrollment))
    return enrollment


@transaction.atomic
def admin_set_photo(student, upload, *, actor):
    """Validate, normalise (JPEG, EXIF removed, at most 800 px) and store the
    photo under a random name in the default storage (no public route);
    the student card reads it from there. Previous files are kept."""
    from .photos import normalise_photo

    require_role(actor, ADMIN_ROLES, school=student.school)
    student = Student.objects.select_for_update().get(pk=student.pk)
    if student.status == StudentStatus.ARCHIVED:
        raise ValidationError("An archived student cannot be modified.", code="student_archived")
    content = normalise_photo(upload)
    old = student.photo.name if student.photo else None
    student.photo.save(content.name, content, save=False)
    student.save(update_fields=["photo", "updated_at"])
    _audit_student("STUDENT_PHOTO_SET", actor, student, old={"photo": old}, new={"photo": student.photo.name})
    return student


@transaction.atomic
def admin_remove_photo(student, *, actor):
    require_role(actor, ADMIN_ROLES, school=student.school)
    student = Student.objects.select_for_update().get(pk=student.pk)
    if student.photo:
        old = student.photo.name
        student.photo = None
        student.save(update_fields=["photo", "updated_at"])
        _audit_student("STUDENT_PHOTO_REMOVED", actor, student, old={"photo": old}, new={"photo": None})
    return student


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
