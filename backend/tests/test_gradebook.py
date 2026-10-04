"""Academic core: scales, courses, assessments, grades, history, averages,
report cards, evolution, period closing (models + PostgreSQL + services)."""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

from apps.academics import services as academics
from apps.academics.models import GradingScale, PeriodStatus, PeriodType
from apps.gradebook import services as gb
from apps.gradebook.models import (
    Assessment,
    AssessmentStatus,
    Course,
    Grade,
    GradeChangeLog,
    ReportCardLine,
    ReportCardStatus,
)
from apps.people import services as people

from .conftest import DB
from .factories import (
    AcademicYearFactory,
    SchoolClassFactory,
    SchoolFactory,
    StudentFactory,
    SubjectFactory,
    make_teacher,
    member_with_role,
)
from .gradebook_world import make_world

pytestmark = DB

D = Decimal


@pytest.fixture
def w(school):
    return make_world(school)


def rejected():
    return pytest.raises(IntegrityError)


# =============================================================================
# Grading scales
# =============================================================================


def test_default_scales_20_100_60_with_one_default(school):
    scales = {s.code: s for s in GradingScale.objects.for_school(school)}
    assert {c: (s.max_score, s.is_default) for c, s in scales.items()} == {
        "SUR20": (D(20), True),
        "SUR100": (D(100), False),
        "SUR60": (D(60), False),
    }


@pytest.mark.parametrize(
    "fields",
    [{"max_score": 0}, {"pass_score": 25}, {"pass_score": -1}, {"decimal_places": 5}],
)
def test_scale_check_constraints(school, fields):
    with rejected(), transaction.atomic():
        GradingScale.objects.create(school=school, code="X", label="X", **{"max_score": 20, **fields})


def test_only_one_default_scale_and_it_must_be_active(school):
    with rejected(), transaction.atomic():
        GradingScale.objects.create(school=school, code="X", label="X", max_score=10, is_default=True)
    with rejected(), transaction.atomic():
        GradingScale.objects.filter(school=school, is_default=True).update(active=False)


# =============================================================================
# Courses
# =============================================================================


def test_course_unique_and_positive_coefficient(w):
    with rejected(), transaction.atomic():
        Course.objects.create(
            school=w.school, school_class=w.klass, subject=w.maths, teacher=w.tm, academic_year=w.year
        )
    with rejected(), transaction.atomic():
        Course.objects.filter(pk=w.course_maths.pk).update(coefficient=0)


def test_course_class_must_belong_to_course_year_postgresql(w):
    other_year = AcademicYearFactory(school=w.school)
    with rejected(), transaction.atomic():
        Course.objects.create(
            school=w.school, school_class=w.klass, subject=w.french, teacher=w.tm, academic_year=other_year
        )


def test_course_mixing_schools_is_refused_postgresql(w):
    foreign_subject = SubjectFactory(school=SchoolFactory())
    with rejected(), transaction.atomic():
        Course.objects.create(
            school=w.school, school_class=w.klass, subject=foreign_subject, teacher=w.tm, academic_year=w.year
        )


def test_course_requires_admin_and_an_accepted_qualification(w):
    klass2 = SchoolClassFactory(school=w.school, academic_year=w.year)
    with pytest.raises(PermissionDenied):
        gb.create_course(klass2, w.maths, w.tm, actor=w.tm_member)
    # The maths teacher declared french -> PENDING review -> cannot teach it yet.
    people.declare_qualification(w.tm, w.french)
    with pytest.raises(ValidationError) as exc:
        gb.create_course(klass2, w.french, w.tm, actor=w.admin)
    assert exc.value.code == "teacher_not_qualified"


# =============================================================================
# Assessments
# =============================================================================


def test_assessment_constraints_postgresql(w):
    a = w.assess()
    for field, value in (("max_score", 0), ("weight", 0), ("assessment_type", "QUIZ")):
        with rejected(), transaction.atomic():
            Assessment.objects.filter(pk=a.pk).update(**{field: value})


def test_assessment_period_and_course_in_same_year_postgresql(w):
    other_year = AcademicYearFactory(school=w.school)
    with rejected(), transaction.atomic():
        Assessment.objects.create(
            school=w.school,
            course=w.course_maths,
            academic_period=w.s1,
            academic_year=other_year,
            name="x",
            assessment_type="EXAM",
            max_score=20,
        )


def test_assessment_must_be_in_an_open_leaf_period(w):
    with pytest.raises(ValidationError) as exc:
        w.assess(period=w.t1)  # Trimestre has children
    assert exc.value.code == "period_not_leaf"
    gb.close_period(w.s2, actor=w.admin)
    with pytest.raises(ValidationError) as exc:
        w.assess(period=w.s2)
    assert exc.value.code == "period_not_open"


def test_only_the_course_teacher_or_admin_creates_assessments(w):
    with pytest.raises(PermissionDenied):
        gb.create_assessment(w.course_maths, w.s1, actor=w.tf_member, name="x", assessment_type="EXAM", max_score=D(20))
    gb.create_assessment(w.course_maths, w.s1, actor=w.admin, name="x", assessment_type="EXAM", max_score=D(20))


# =============================================================================
# Grades: database guarantees
# =============================================================================


def test_score_cannot_exceed_max_score_postgresql(w):
    a, s = w.assess(max_score=20), w.students[0]
    with rejected(), transaction.atomic():
        Grade.objects.create(
            school=w.school, assessment=a, student=s, score=D(21), max_score=D(20), entered_by=w.tm_member
        )
    with rejected(), transaction.atomic():
        Grade.objects.create(
            school=w.school, assessment=a, student=s, score=D(-1), max_score=D(20), entered_by=w.tm_member
        )


def test_grade_max_score_must_equal_assessment_max_score_postgresql(w):
    """Composite FK (assessment, max_score): lying about max_score is refused."""
    a = w.assess(max_score=20)
    with rejected(), transaction.atomic():
        Grade.objects.create(
            school=w.school, assessment=a, student=w.students[0], score=D(30), max_score=D(40), entered_by=w.tm_member
        )


def test_max_score_change_cascades_and_cannot_go_below_a_score(w):
    a = w.assess(max_score=20)
    g = w.grade(a, w.students[0], 18)
    Assessment.objects.filter(pk=a.pk).update(max_score=40)  # ON UPDATE CASCADE
    g.refresh_from_db()
    assert g.max_score == D(40)
    with rejected(), transaction.atomic():
        Assessment.objects.filter(pk=a.pk).update(max_score=10)  # 18 > 10


def test_one_grade_per_student_and_assessment(w):
    a = w.assess()
    w.grade(a, w.students[0], 10)
    with rejected(), transaction.atomic():
        w.grade(a, w.students[0], 12)


def test_trigger_forbids_any_grade_write_when_period_closed(w):
    """Even raw ORM writes, bypassing services, are refused by PostgreSQL."""
    a = w.assess()
    g = w.grade(a, w.students[0], 10)
    gb.close_period(w.t1, actor=w.admin)
    with rejected(), transaction.atomic():
        Grade.objects.filter(pk=g.pk).update(score=11)
    with rejected(), transaction.atomic():
        Grade.objects.filter(pk=g.pk).delete()
    with rejected(), transaction.atomic():
        Grade.objects.create(
            school=w.school, assessment=a, student=w.students[1], score=1, max_score=a.max_score, entered_by=w.admin
        )


def test_grade_mixing_schools_is_refused_postgresql(w):
    a = w.assess()
    with rejected(), transaction.atomic():
        Grade.objects.create(
            school=w.school,
            assessment=a,
            student=StudentFactory(school=SchoolFactory()),
            score=1,
            max_score=a.max_score,
            entered_by=w.tm_member,
        )


# =============================================================================
# Grades: services, permissions, history
# =============================================================================


def test_grade_entry_rules(w):
    a = w.assess(max_score=10)
    with pytest.raises(ValidationError) as exc:
        w.grade(a, w.students[0], 11)
    assert exc.value.code == "score_out_of_range"
    with pytest.raises(ValidationError) as exc:
        w.grade(a, StudentFactory(school=w.school), 5)
    assert exc.value.code == "student_not_enrolled"
    with pytest.raises(PermissionDenied):
        gb.enter_grade(a, w.students[0], D(5), actor=w.tf_member)  # not their course
    with pytest.raises(PermissionDenied):
        gb.enter_grade(a, w.students[0], D(5), actor=member_with_role(w.school, "PARENT"))


def test_bulk_entry_is_all_or_nothing(w):
    a = w.assess(max_score=20)
    entries = [{"student": w.students[0], "score": D(12)}, {"student": w.students[1], "score": D(25)}]
    with pytest.raises(ValidationError):
        gb.enter_grades_bulk(a, entries, actor=w.tm_member)
    assert not Grade.objects.filter(assessment=a).exists()


def test_update_grade_writes_immutable_history(w):
    g = w.grade(w.assess(), w.students[0], 9)
    gb.update_grade(g, D("11.5"), actor=w.tm_member, reason="Correction après vérification de copie")
    log = GradeChangeLog.objects.get(grade=g)
    assert (log.old_score, log.new_score, log.changed_by) == (D(9), D("11.5"), w.tm_member)
    with rejected(), transaction.atomic():
        GradeChangeLog.objects.filter(pk=log.pk).update(new_score=20)
    with rejected(), transaction.atomic():
        GradeChangeLog.objects.filter(pk=log.pk).delete()


def test_update_grade_rules(w):
    g = w.grade(w.assess(), w.students[0], 9)
    with pytest.raises(ValidationError) as exc:
        gb.update_grade(g, D(10), actor=w.tm_member, reason=" ")
    assert exc.value.code == "reason_required"
    with pytest.raises(gb.StaleGrade):
        gb.update_grade(g, D(10), actor=w.tm_member, reason="x", expected_score=D(8))
    with pytest.raises(PermissionDenied):
        gb.update_grade(g, D(10), actor=w.tf_member, reason="x")
    gb.close_period(w.t1, actor=w.admin)
    with pytest.raises(ValidationError) as exc:
        gb.update_grade(g, D(10), actor=w.admin, reason="x")
    assert exc.value.code == "assessment_closed"


# =============================================================================
# Averages (no hard-coded /20)
# =============================================================================


def test_weighted_leaf_average_with_mixed_assessment_scales(w):
    s = w.students[0]
    w.grade(w.assess(max_score=20, weight=1), s, 15)  # 0.75
    w.grade(w.assess(max_score=10, weight=2), s, 8)  # 0.80 (weight 2)
    fraction = gb.subject_fraction(s.pk, [w.course_maths.pk], w.s1)
    assert gb.express(fraction, GradingScale.objects.get(school=w.school, code="SUR20")) == D("15.67")
    assert gb.express(fraction, GradingScale.objects.get(school=w.school, code="SUR100")) == D("78.33")
    assert gb.express(fraction, GradingScale.objects.get(school=w.school, code="SUR60")) == D("47.00")


def test_coefficient_override_replaces_the_assessment_weight(w):
    s = w.students[0]
    w.grade(w.assess(weight=1), s, 20)
    w.grade(w.assess(weight=1), s, 0, coefficient_override=D(3))
    assert gb.subject_fraction(s.pk, [w.course_maths.pk], w.s1) == D("0.25")


def test_trimester_is_the_mean_of_its_sequences(w):
    s = w.students[0]
    w.grade(w.assess(period=w.s1), s, 16)  # 0.8
    w.grade(w.assess(period=w.s2), s, 10)  # 0.5
    assert gb.subject_fraction(s.pk, [w.course_maths.pk], w.t1) == D("0.65")


def test_university_semesters_without_children(school):
    """Same code, flat organisation: a semester is a leaf period."""
    w = make_world(school)
    # The world year has trimesters; build a separate, flat, university-like year.
    year = academics.create_academic_year(school, name="U-2027", start_date=date(2027, 9, 1), end_date=date(2028, 7, 1))
    sem = academics.create_period(
        year,
        name="Semestre 1",
        period_type=PeriodType.SEMESTER,
        order_index=1,
        start_date=date(2027, 9, 1),
        end_date=date(2028, 1, 31),
    )
    klass = SchoolClassFactory(school=school, academic_year=year)
    course = gb.create_course(klass, w.maths, w.tm, actor=w.admin)
    student = StudentFactory(school=school)
    people.enroll_student(student, klass)
    a = gb.create_assessment(course, sem, actor=w.tm_member, name="Partiel", assessment_type="EXAM", max_score=D(100))
    gb.enter_grade(a, student, D(64), actor=w.tm_member)
    assert gb.express(gb.subject_fraction(student.pk, [course.pk], sem), gb.course_scale(course)) == D("12.80")


def test_no_grade_means_no_average_not_zero(w):
    assert gb.subject_fraction(w.students[0].pk, [w.course_maths.pk], w.t1) is None


def test_competition_ranking():
    assert gb.competition_ranks({"a": 15, "b": 14, "c": 14, "d": 12}) == {"a": 1, "b": 2, "c": 2, "d": 4}


# =============================================================================
# Report cards
# =============================================================================


def fill_t1(w):
    """s0: maths 16 & 10 -> 13.00 ; french 10 -> 10.00 ; general (13*4+10*2)/6 = 12.00
    s1: maths 12 -> 12.00 ; french 14 -> 14.00 ; general (48+28)/6 = 12.67
    s2: no grade at all."""
    a1, a2 = w.assess(period=w.s1), w.assess(period=w.s2)
    f1 = w.assess(course=w.course_french, period=w.s1)
    s0, s1, _ = w.students
    w.grade(a1, s0, 16)
    w.grade(a2, s0, 10)
    w.grade(f1, s0, 10)
    w.grade(a1, s1, 12)
    w.grade(f1, s1, 14)


def test_report_cards_lines_general_average_and_rank(w):
    fill_t1(w)
    cards = {c.student_id: c for c in gb.generate_report_cards(w.klass, w.t1, actor=w.admin)}
    s0, s1, s2 = w.students
    c0, c1, c2 = cards[s0.pk], cards[s1.pk], cards[s2.pk]

    lines = {line.subject.code: line for line in c0.lines.all()}
    assert (lines["MATH"].average, lines["MATH"].coefficient, lines["MATH"].weighted_average) == (
        D("13.00"),
        D(4),
        D("52.00"),
    )
    assert lines["FR"].teacher_name_snapshot  # snapshot kept for the frozen card
    assert (c0.general_average, c1.general_average, c2.general_average) == (D("12.00"), D("12.67"), None)
    assert (c1.rank, c0.rank, c2.rank) == (1, 2, None)
    assert c0.class_size == 2 and c0.scale_max_score == D(20) and c0.status == ReportCardStatus.DRAFT


def test_report_card_uses_the_school_default_scale(w):
    fill_t1(w)
    GradingScale.objects.filter(school=w.school, code="SUR20").update(is_default=False)
    GradingScale.objects.filter(school=w.school, code="SUR100").update(is_default=True)
    card = next(c for c in gb.generate_report_cards(w.klass, w.t1, actor=w.admin) if c.student == w.students[0])
    assert (card.general_average, card.scale_max_score) == (D("60.00"), D(100))


def test_weighted_average_consistency_is_a_database_check(w):
    fill_t1(w)
    card = gb.generate_report_cards(w.klass, w.t1, actor=w.admin)[0]
    line = card.lines.first()
    with rejected(), transaction.atomic():
        ReportCardLine.objects.filter(pk=line.pk).update(weighted_average=D("1.00"))


def test_validation_requires_closed_period_and_freezes_the_card(w):
    fill_t1(w)
    card = next(c for c in gb.generate_report_cards(w.klass, w.t1, actor=w.admin) if c.student == w.students[0])
    with pytest.raises(ValidationError) as exc:
        gb.validate_report_card(card, actor=w.admin)
    assert exc.value.code == "period_not_closed"
    with pytest.raises(PermissionDenied):
        gb.validate_report_card(card, actor=w.tm_member)

    gb.close_period(w.t1, actor=w.admin)
    gb.validate_report_card(card, actor=w.admin)
    frozen_average = card.general_average
    # Regeneration leaves validated cards untouched...
    regenerated = next(c for c in gb.generate_report_cards(w.klass, w.t1, actor=w.admin) if c.pk == card.pk)
    assert (regenerated.status, regenerated.general_average) == (ReportCardStatus.VALIDATED, frozen_average)
    # ...and the period cannot be reopened under a validated result.
    with pytest.raises(ValidationError) as exc:
        gb.reopen_period(w.s1, actor=w.admin)
    assert exc.value.code == "report_card_validated"


def test_conflicting_coefficients_for_one_subject_are_refused(w):
    second_teacher = make_teacher(w.school, category=w.maths.category, primary_subject=w.maths)
    with pytest.raises(ValidationError) as exc:  # refused at creation since ADR 0020
        gb.create_course(w.klass, w.maths, second_teacher, actor=w.admin, coefficient=D(3))
    assert exc.value.code == "course_coefficient_conflict"
    # Defence in depth: a conflicting row written around the service is still caught by report cards.
    from apps.gradebook.models import Course

    Course.objects.create(
        school=w.school,
        school_class=w.klass,
        subject=w.maths,
        teacher=second_teacher,
        academic_year=w.year,
        coefficient=D(3),
    )
    with pytest.raises(ValidationError) as exc:
        gb.generate_report_cards(w.klass, w.t1, actor=w.admin)
    assert exc.value.code == "coefficient_conflict"


# =============================================================================
# Period closing & evolution
# =============================================================================


def test_closing_a_trimester_closes_its_sequences_and_assessments(w):
    a = w.assess(period=w.s2)
    gb.close_period(w.t1, actor=w.admin)
    for period in (w.t1, w.s1, w.s2):
        period.refresh_from_db()
        assert period.status == PeriodStatus.CLOSED
    a.refresh_from_db()
    assert a.status == AssessmentStatus.CLOSED
    gb.reopen_period(w.t1, actor=w.admin)
    a.refresh_from_db()
    assert a.status == AssessmentStatus.OPEN
    with pytest.raises(PermissionDenied):
        gb.close_period(w.t1, actor=w.tm_member)


def test_student_evolution_period_by_period(w):
    fill_t1(w)
    evolution = {p["period"]: p for p in gb.student_evolution(w.students[0], w.year)}
    assert evolution["Séquence 1"]["general_average"] == D("14.00")  # (16*4 + 10*2) / 6
    assert evolution["Séquence 2"]["general_average"] == D("10.00")  # maths only
    assert evolution["Trimestre 1"]["general_average"] == D("12.00")
    assert {s["subject"] for s in evolution["Trimestre 1"]["subjects"]} == {"MATH", "FR"}
