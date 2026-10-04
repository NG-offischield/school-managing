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
from django.db.models import Q
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
    EmploymentStatus,
    EnrollmentStatus,
    GuardianProfile,
    ParentProfile,
    ParentStudent,
    ProfessionalStatus,
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
# Teachers administration (admin desktop: Gestion académique → Enseignants, ADR 0019)
# =============================================================================
# One teacher = User (the person, global) → SchoolMembership (this school,
# role TEACHER) → EmployeeProfile (HR: employee number = teacher number) →
# TeacherProfile (category, primary subject) → qualifications. Creation
# builds the whole chain in ONE transaction: a refusal at any step (number
# taken, e-mail used by another account, incompatible primary subject…)
# leaves nothing behind.
#
# Accounts: the user is created WITHOUT a usable password (Django's
# unusable password): no password is ever typed, generated or shown here,
# and the existing login stays the only authentication. Activating the
# account (first password) is a separate, later procedure.
#
# Compatibility stays the job of people/compatibility.py: these services
# call evaluate(); the client only displays its verdict.

TEACHER_USER_FIELDS = ("first_name", "last_name", "email", "phone")
TEACHER_EMPLOYEE_FIELDS = ("employee_number", "hire_date", "address", "employment_status")
TEACHER_PROFILE_FIELDS = (
    "pedagogical_category",
    "primary_subject",
    "professional_status",
    "qualification_summary",
    "bio",
)


def _teacher_snapshot(teacher):
    employee, user = teacher.employee, teacher.employee.membership.user
    return {
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "phone": user.phone,
        "employee_number": employee.employee_number,
        "hire_date": employee.hire_date,
        "address": employee.address,
        "employment_status": employee.employment_status,
        "pedagogical_category": str(teacher.pedagogical_category_id),
        "primary_subject": str(teacher.primary_subject_id),
        "professional_status": teacher.professional_status,
    }


def _audit_teacher(action, actor, entity, old=None, new=None):
    from apps.audit.models import AuditLayer
    from apps.audit.services import record_audit

    record_audit(action, actor=actor, entity=entity, old=old, new=new, layer=AuditLayer.ADMINISTRATIVE)


def _check_category(school, category):
    if category is None:
        raise ValidationError("Choose a pedagogical category.", code="category_required")
    if category.school_id != school.pk:
        raise ValidationError("The category belongs to another school.", code="category_other_school")
    if not category.active:
        raise ValidationError("This pedagogical category is inactive.", code="category_inactive")


def _check_subject(school, subject):
    if subject is None:
        raise ValidationError("Choose a subject.", code="subject_required")
    if subject.school_id != school.pk:
        raise ValidationError("The subject belongs to another school.", code="subject_other_school")
    if not subject.active:
        raise ValidationError("This subject is inactive.", code="subject_inactive")


def _unique_employee_number(school, number, exclude=None):
    taken = EmployeeProfile.objects.filter(school=school, employee_number__iexact=number)
    if exclude is not None:
        taken = taken.exclude(pk=exclude.pk)
    if taken.exists():
        raise ValidationError(
            f"The number {number} is already used by another employee.", code="duplicate_employee_number"
        )


def _email(value):
    value = (value or "").strip().lower()
    if not value or "@" not in value:
        raise ValidationError("A valid e-mail address is required.", code="email_required")
    return value


def _account_for(school, email, first_name, last_name, phone, actor):
    """The user + membership of the new teacher.

    - nobody uses the e-mail: a new user (unusable password) + ACTIVE membership;
    - the e-mail belongs to a member of THIS school without an employee
      profile (e.g. a parent who becomes a teacher): that membership is reused;
    - otherwise (account of another school, or already an employee here):
      refused (409) — another school's account is never attached silently.
    """
    from apps.accounts.models import MembershipStatus, SchoolMembership, User

    user = User.objects.filter(email__iexact=email).first() or User.objects.filter(username__iexact=email).first()
    if user is None:
        user = User.objects.create_user(
            username=email, email=email, password=None, first_name=first_name, last_name=last_name, phone=phone
        )
    membership = SchoolMembership.objects.filter(school=school, user=user).first()
    if membership is None:
        if user.memberships.exists():
            raise ValidationError("This e-mail address is already used by another account.", code="email_in_use")
        membership = SchoolMembership.objects.create(
            school=school,
            user=user,
            status=MembershipStatus.ACTIVE,
            joined_at=timezone.now(),
            is_primary_school=not user.memberships.filter(is_primary_school=True).exists(),
        )
    elif hasattr(membership, "employee_profile"):
        raise ValidationError("This person is already an employee of the school.", code="already_employee")
    _grant_teacher_role(membership, actor)
    return membership


def _grant_teacher_role(membership, actor):
    """The role comes from the role catalog (system role TEACHER): never a
    free role name."""
    from apps.accounts.models import MembershipRole, Role, RoleCode

    assignment, created = MembershipRole.objects.get_or_create(
        membership=membership,
        role=Role.objects.get(code=RoleCode.TEACHER),
        defaults={"assigned_by": actor, "active": True},
    )
    if not created and not assignment.active:
        assignment.active = True
        assignment.assigned_by = actor
        assignment.save(update_fields=["active", "assigned_by", "updated_at"])


@transaction.atomic
def admin_create_teacher(
    school,
    *,
    actor,
    first_name,
    last_name,
    email,
    employee_number,
    pedagogical_category,
    primary_subject,
    phone=None,
    hire_date=None,
    address=None,
    qualification_summary=None,
    bio=None,
):
    require_role(actor, ADMIN_ROLES, school=school)
    first_name, last_name = _text(first_name, "first_name", required=True), _text(last_name, "last_name", required=True)
    email = _email(email)
    employee_number = _text(employee_number, "employee_number", required=True)
    _check_category(school, pedagogical_category)
    _check_subject(school, primary_subject)
    _unique_employee_number(school, employee_number)
    membership = _account_for(school, email, first_name, last_name, _text(phone, "phone") or None, actor)
    employee = create_employee(
        membership,
        employee_number=employee_number,
        employee_type=EmployeeType.TEACHER,
        hire_date=hire_date,
        address=_text(address, "address") or None,
    )
    # create_teacher declares the primary subject through the compatibility
    # engine: an incompatible primary subject rolls everything back.
    teacher = create_teacher(
        employee,
        pedagogical_category=pedagogical_category,
        primary_subject=primary_subject,
        qualification_summary=_text(qualification_summary, "qualification_summary") or None,
        bio=_text(bio, "bio") or None,
    )
    _audit_teacher("TEACHER_CREATED", actor, teacher, new=_teacher_snapshot(teacher))
    return teacher


ACTIVE_TEACHING = (ProfessionalStatus.ACTIVE,)


def _teaching_load(teacher):
    """What still needs the teacher: active courses of open years and
    sessions still to come (the planning relies on an active teacher)."""
    from apps.gradebook.models import Course
    from apps.scheduling.models import SessionStatus, TeachingSession

    courses = Course.objects.filter(
        teacher=teacher, active=True, academic_year__status__in=(AcademicYearStatus.PLANNED, AcademicYearStatus.ACTIVE)
    ).count()
    sessions = TeachingSession.objects.filter(
        teacher=teacher, status=SessionStatus.SCHEDULED, date__gte=timezone.localdate()
    ).count()
    return courses, sessions


def _check_can_stop_teaching(teacher):
    courses, sessions = _teaching_load(teacher)
    if courses or sessions:
        raise ValidationError(
            f"The teacher still has {courses} active course(s) and {sessions} session(s) to come.",
            code="teacher_in_use",
            params={"courses": courses, "sessions": sessions},
        )


@transaction.atomic
def admin_update_teacher(teacher, *, actor, **changes):
    """Identity (user), HR (employee) and teaching profile. Leaving the
    "active" state (status change) follows the same rule as deactivation."""
    require_role(actor, ADMIN_ROLES, school=teacher.school)
    teacher = TeacherProfile.objects.select_for_update().select_related("employee__membership__user").get(pk=teacher.pk)
    employee, user = teacher.employee, teacher.employee.membership.user
    school = teacher.school
    old = _teacher_snapshot(teacher)
    for name in ("first_name", "last_name"):
        if name in changes:
            setattr(user, name, _text(changes[name], name, required=True))
    if "phone" in changes:
        user.phone = _text(changes["phone"], "phone") or None
    if "email" in changes:
        email = _email(changes["email"])
        from apps.accounts.models import User

        if User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).exclude(pk=user.pk).exists():
            raise ValidationError("This e-mail address is already used by another account.", code="email_in_use")
        user.email = email
    if "employee_number" in changes:
        number = _text(changes["employee_number"], "employee_number", required=True)
        _unique_employee_number(school, number, exclude=employee)
        employee.employee_number = number
    for name in ("hire_date",):
        if name in changes:
            setattr(employee, name, changes[name])
    if "address" in changes:
        employee.address = _text(changes["address"], "address") or None
    if "pedagogical_category" in changes:
        _check_category(school, changes["pedagogical_category"])
        teacher.pedagogical_category = changes["pedagogical_category"]
    if "primary_subject" in changes and changes["primary_subject"] != teacher.primary_subject:
        subject = changes["primary_subject"]
        _check_subject(school, subject)
        existing = teacher.qualifications.filter(subject=subject).first()
        if existing is None:
            teacher.primary_subject = subject
            declare_qualification(teacher, subject, source=QualificationSource.ADMIN)  # engine decides
        elif existing.status == QualificationStatus.REJECTED:
            raise ValidationError("This subject's qualification was rejected.", code="qualification_rejected")
        teacher.primary_subject = subject
    for name in ("qualification_summary", "bio"):
        if name in changes:
            setattr(teacher, name, _text(changes[name], name) or None)
    stops = False
    if "professional_status" in changes:
        if changes["professional_status"] not in ProfessionalStatus.values:
            raise ValidationError("Unknown status.", code="status_invalid")
        stops |= changes["professional_status"] not in ACTIVE_TEACHING
        teacher.professional_status = changes["professional_status"]
    if "employment_status" in changes:
        if changes["employment_status"] not in EmploymentStatus.values:
            raise ValidationError("Unknown status.", code="status_invalid")
        stops |= changes["employment_status"] != EmploymentStatus.ACTIVE
        employee.employment_status = changes["employment_status"]
    if stops:
        _check_can_stop_teaching(teacher)
    user.save()
    employee.save()
    teacher.save()
    _audit_teacher("TEACHER_UPDATED", actor, teacher, old=old, new=_teacher_snapshot(teacher))
    return teacher


@transaction.atomic
def admin_set_teacher_active(teacher, active, *, actor):
    """Deactivate = stop teaching (professional status INACTIVE). Refused
    (409 teacher_in_use) while courses or future sessions still need the
    teacher. Nothing is deleted: courses, sessions, grades, payroll and the
    account history stay. Reactivation needs an ACTIVE employment."""
    require_role(actor, ADMIN_ROLES, school=teacher.school)
    teacher = TeacherProfile.objects.select_for_update().select_related("employee").get(pk=teacher.pk)
    old = _teacher_snapshot(teacher)
    if active:
        if teacher.employee.employment_status != EmploymentStatus.ACTIVE:
            raise ValidationError("The employment is not active.", code="employment_not_active")
        teacher.professional_status = ProfessionalStatus.ACTIVE
    else:
        _check_can_stop_teaching(teacher)
        teacher.professional_status = ProfessionalStatus.INACTIVE
    teacher.save(update_fields=["professional_status", "updated_at"])
    _audit_teacher(
        "TEACHER_ACTIVATED" if active else "TEACHER_DEACTIVATED",
        actor,
        teacher,
        old=old,
        new=_teacher_snapshot(teacher),
    )
    return teacher


def _qualification_data(qualification):
    return {
        "subject": str(qualification.subject_id),
        "subject_code": qualification.subject.code,
        "status": qualification.status,
        "computed_compatibility": qualification.computed_compatibility,
    }


@transaction.atomic
def admin_add_qualification(teacher, subject, *, actor, level=None, notes=None):
    """Administrative entry of a subject, judged by the compatibility engine:
    COMPATIBLE / OVERRIDDEN -> DECLARED, REQUIRES_REVIEW -> PENDING,
    INCOMPATIBLE -> refused (400 incompatible_subject; an override may then
    be granted). A previously rejected qualification is re-evaluated."""
    require_role(actor, ADMIN_ROLES, school=teacher.school)
    _check_subject(teacher.school, subject)
    existing = teacher.qualifications.filter(subject=subject).first()
    if existing is not None and existing.status != QualificationStatus.REJECTED:
        raise ValidationError("The teacher already has this subject.", code="already_qualified")
    if existing is not None:  # rejected before: judged again, same row (unique per teacher and subject)
        evaluation = evaluate(teacher, subject, level)
        if evaluation.result == CompatibilityResult.INCOMPATIBLE:
            raise IncompatibleSubject(
                "This subject is incompatible with the teacher's pedagogical category.", code="incompatible_subject"
            )
        old = _qualification_data(existing)
        existing.status = (
            QualificationStatus.PENDING
            if evaluation.result == CompatibilityResult.REQUIRES_REVIEW
            else QualificationStatus.DECLARED
        )
        existing.source = (
            QualificationSource.OVERRIDE
            if evaluation.result == CompatibilityResult.OVERRIDDEN
            else QualificationSource.ADMIN
        )
        existing.computed_compatibility = evaluation.result
        existing.verified, existing.verified_by, existing.verified_at = False, None, None
        existing.notes = _text(notes, "notes") or None
        existing.save()
        _audit_teacher("QUALIFICATION_ADDED", actor, existing, old=old, new=_qualification_data(existing))
        return existing
    qualification = declare_qualification(
        teacher, subject, level=level, source=QualificationSource.ADMIN, notes=_text(notes, "notes") or None
    )
    _audit_teacher("QUALIFICATION_ADDED", actor, qualification, new=_qualification_data(qualification))
    return qualification


@transaction.atomic
def admin_verify_qualification(qualification, *, actor):
    old = _qualification_data(qualification)
    qualification = verify_qualification(qualification, actor=actor)
    _audit_teacher("QUALIFICATION_VERIFIED", actor, qualification, old=old, new=_qualification_data(qualification))
    return qualification


@transaction.atomic
def admin_reject_qualification(qualification, *, actor, reason):
    """Refuse or withdraw a subject. Refused for the primary subject and while
    an active course of an open year uses it (409 qualification_in_use):
    courses already given keep their history."""
    from apps.gradebook.models import Course

    require_role(actor, ADMIN_ROLES, school=qualification.school)
    teacher = qualification.teacher
    if qualification.subject_id == teacher.primary_subject_id:
        raise ValidationError("The primary subject cannot be withdrawn.", code="primary_subject_qualification")
    in_use = Course.objects.filter(
        teacher=teacher,
        subject=qualification.subject,
        active=True,
        academic_year__status__in=(AcademicYearStatus.PLANNED, AcademicYearStatus.ACTIVE),
    ).exists()
    if in_use:
        raise ValidationError("An active course uses this qualification.", code="qualification_in_use")
    old = _qualification_data(qualification)
    qualification = reject_qualification(qualification, actor=actor, reason=_text(reason, "reason"))
    _audit_teacher("QUALIFICATION_REJECTED", actor, qualification, old=old, new=_qualification_data(qualification))
    return qualification


@transaction.atomic
def admin_grant_override(teacher, subject, *, actor, reason, level=None, expires_at=None):
    """grant_compatibility_override + checks + audit (ADMIN/SUPER_ADMIN only:
    spec §9 "overrides carry actor + reason + timestamp + scope")."""
    require_role(actor, ADMIN_ROLES, school=teacher.school)
    _check_subject(teacher.school, subject)
    if level is not None and level.school_id != teacher.school_id:
        raise ValidationError("The level belongs to another school.", code="level_other_school")
    if expires_at is not None and expires_at <= timezone.now():
        raise ValidationError("The expiry must be in the future.", code="expiry_past")
    override = grant_compatibility_override(
        teacher, subject, actor=actor, reason=reason, level=level, expires_at=expires_at
    )
    _audit_teacher(
        "COMPATIBILITY_OVERRIDE_GRANTED",
        actor,
        override,
        new={"subject": str(subject.pk), "level": str(level.pk) if level else None, "reason": override.reason},
    )
    return override


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
