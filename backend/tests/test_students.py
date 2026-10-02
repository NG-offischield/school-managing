"""Students, archiving and year-by-year enrollment history."""

from datetime import date, timedelta

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.academics.models import AcademicYearStatus
from apps.people import services
from apps.people.models import (
    EnrollmentStatus,
    HardDeleteForbidden,
    PromotionStatus,
    Student,
    StudentEnrollment,
    StudentStatus,
)

from .conftest import DB
from .factories import (
    AcademicYearFactory,
    LevelFactory,
    SchoolClassFactory,
    SchoolFactory,
    StudentFactory,
    admin_of,
    member_with_role,
)

pytestmark = DB


# --- Student -------------------------------------------------------------------


def test_create_student_with_distinct_identifiers(school):
    student = services.create_student(
        school,
        student_number="MAT001",
        registration_number="REG001",
        first_name="Awa",
        last_name="Nkomo",
        date_of_birth=date(2012, 1, 5),
        sex="F",
    )
    # Technical id (UUID) and business numbers are different things.
    assert str(student.id) not in (student.student_number, student.registration_number)


def test_birth_date_in_the_future_is_refused(school):
    with pytest.raises(ValidationError):
        services.create_student(
            school,
            student_number="A",
            registration_number="B",
            first_name="X",
            last_name="Y",
            date_of_birth=timezone.localdate() + timedelta(days=1),
            sex="M",
        )


def test_student_numbers_unique_per_school_only(school):
    StudentFactory(school=school, student_number="MAT1", registration_number="R1")
    StudentFactory(school=SchoolFactory(), student_number="MAT1", registration_number="R1")
    with pytest.raises(IntegrityError), transaction.atomic():
        StudentFactory(school=school, student_number="MAT1")
    with pytest.raises(IntegrityError), transaction.atomic():
        StudentFactory(school=school, registration_number="R1")


@pytest.mark.parametrize("field,value", [("sex", "X"), ("status", "DELETED"), ("height_cm", 0)])
def test_student_check_constraints(school, field, value):
    student = StudentFactory(school=school)
    with pytest.raises(IntegrityError), transaction.atomic():
        Student.objects.filter(pk=student.pk).update(**{field: value})


def test_students_are_never_hard_deleted(school):
    student = StudentFactory(school=school)
    with pytest.raises(HardDeleteForbidden):
        student.delete()
    with pytest.raises(HardDeleteForbidden):
        Student.objects.filter(pk=student.pk).delete()
    assert Student.objects.filter(pk=student.pk).exists()


def test_archive_student(school):
    student = services.archive_student(StudentFactory(school=school), actor=admin_of(school))
    assert student.status == StudentStatus.ARCHIVED and student.archived_at is not None


def test_archived_status_and_date_must_agree(school):
    student = StudentFactory(school=school)
    with pytest.raises(IntegrityError), transaction.atomic():
        Student.objects.filter(pk=student.pk).update(status=StudentStatus.ARCHIVED)  # no archived_at
    with pytest.raises(IntegrityError), transaction.atomic():
        Student.objects.filter(pk=student.pk).update(archived_at=timezone.now())  # still ACTIVE


def test_archiving_requires_an_admin_and_no_active_enrollment(school):
    student = StudentFactory(school=school)
    with pytest.raises(PermissionDenied):
        services.archive_student(student, actor=member_with_role(school, "TEACHER"))
    services.enroll_student(student, SchoolClassFactory(school=school))
    with pytest.raises(ValidationError) as exc:
        services.archive_student(student, actor=admin_of(school))
    assert exc.value.code == "active_enrollment"


# --- Enrollment history -----------------------------------------------------------


def two_years(school):
    y1 = AcademicYearFactory(school=school, name="2025-2026", start_date=date(2025, 9, 1), end_date=date(2026, 7, 31))
    y2 = AcademicYearFactory(school=school, name="2026-2027", start_date=date(2026, 9, 1), end_date=date(2027, 7, 31))
    return y1, y2


def test_enrollment_history_across_years(school):
    """2025-2026 → 3e A (PROMOTED), 2026-2027 → 2nde C (PENDING)."""
    y1, y2 = two_years(school)
    c3a = SchoolClassFactory(school=school, name="3e A", academic_year=y1, level=LevelFactory(school=school, code="3E"))
    c2c = SchoolClassFactory(
        school=school, name="2nde C", academic_year=y2, level=LevelFactory(school=school, code="2NDE")
    )
    student = StudentFactory(school=school)
    admin = admin_of(school)

    first = services.enroll_student(student, c3a, enrollment_date=date(2025, 9, 2))
    services.decide_promotion(first, PromotionStatus.PROMOTED, actor=admin, note="Moyenne 13,4")
    services.enroll_student(student, c2c, enrollment_date=date(2026, 9, 2))

    history = list(
        StudentEnrollment.objects.filter(student=student)
        .order_by("academic_year__start_date")
        .values_list("academic_year__name", "school_class__name", "promotion_status", "status")
    )
    assert history == [
        ("2025-2026", "3e A", PromotionStatus.PROMOTED, EnrollmentStatus.COMPLETED),
        ("2026-2027", "2nde C", PromotionStatus.PENDING, EnrollmentStatus.ACTIVE),
    ]
    first.refresh_from_db()
    assert first.decision_by == admin and first.decision_date is not None


def test_one_enrollment_per_student_and_year(school):
    student, year = StudentFactory(school=school), AcademicYearFactory(school=school)
    services.enroll_student(student, SchoolClassFactory(school=school, academic_year=year))
    with pytest.raises(IntegrityError), transaction.atomic():
        services.enroll_student(student, SchoolClassFactory(school=school, academic_year=year))


def test_class_must_belong_to_the_enrollment_year_postgresql(school):
    y1, y2 = two_years(school)
    with pytest.raises(IntegrityError), transaction.atomic():
        StudentEnrollment.objects.create(
            school=school,
            student=StudentFactory(school=school),
            academic_year=y1,
            school_class=SchoolClassFactory(school=school, academic_year=y2),
            enrollment_date=date(2025, 9, 1),
        )


def test_enrollment_mixing_schools_is_refused_by_postgresql(school):
    klass = SchoolClassFactory(school=school)
    with pytest.raises(IntegrityError), transaction.atomic():
        StudentEnrollment.objects.create(
            school=school,
            student=StudentFactory(school=SchoolFactory()),
            academic_year=klass.academic_year,
            school_class=klass,
            enrollment_date=date(2025, 9, 1),
        )


def test_cannot_enroll_inactive_student_or_into_closed_year(school):
    archived = services.archive_student(StudentFactory(school=school), actor=admin_of(school))
    with pytest.raises(ValidationError):
        services.enroll_student(archived, SchoolClassFactory(school=school))
    closed = AcademicYearFactory(school=school, status=AcademicYearStatus.CLOSED)
    with pytest.raises(ValidationError):
        services.enroll_student(StudentFactory(school=school), SchoolClassFactory(school=school, academic_year=closed))


@pytest.mark.parametrize("status", list(PromotionStatus))
def test_every_promotion_status_is_supported(school, status):
    enrollment = services.enroll_student(StudentFactory(school=school), SchoolClassFactory(school=school))
    if status == PromotionStatus.PENDING:
        with pytest.raises(ValidationError):
            services.decide_promotion(enrollment, status, actor=admin_of(school))
    else:
        assert services.decide_promotion(enrollment, status, actor=admin_of(school)).promotion_status == status


def test_promotion_is_a_human_admin_decision(school):
    enrollment = services.enroll_student(StudentFactory(school=school), SchoolClassFactory(school=school))
    with pytest.raises(PermissionDenied):
        services.decide_promotion(enrollment, PromotionStatus.PROMOTED, actor=member_with_role(school, "TEACHER"))
    # An admin of ANOTHER school is nobody here: refused by the service (and
    # the composite FK on decision_by would refuse it in the database too).
    with pytest.raises(PermissionDenied):
        services.decide_promotion(enrollment, PromotionStatus.PROMOTED, actor=admin_of(SchoolFactory()))


def test_decided_promotion_must_be_dated_postgresql(school):
    enrollment = services.enroll_student(StudentFactory(school=school), SchoolClassFactory(school=school))
    with pytest.raises(IntegrityError), transaction.atomic():
        StudentEnrollment.objects.filter(pk=enrollment.pk).update(promotion_status=PromotionStatus.PROMOTED)
