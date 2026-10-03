"""Academic core services: grades in, averages and report cards out.

Computation model (ADR 0009) — nothing assumes /20
------------------------------------------------------
1. A grade is first a FRACTION:            score / assessment.max_score
2. Average of a LEAF period for a subject: weighted mean of the fractions,
   weight = grade.coefficient_override or assessment.weight
3. Average of a PARENT period (Trimestre): plain mean of its children's
   averages (Séquence 1, Séquence 2) that exist. A university semester with no
   children is simply a leaf: both organisations work with the same code.
4. Expressed in a scale only at the end: fraction × scale.max_score, rounded
   ROUND_HALF_UP to the scale's decimals. Subject averages use the course's
   scale (course → subject default → school default); report cards use the
   school's DEFAULT scale.
5. General average = Σ(subject average × coefficient) / Σ coefficient over the
   subjects that have an average. Rank: competition ranking (1, 2, 2, 4)
   among the students of the class who have an average.

Permissions (spec §8): an administrator of the school may do everything; a
teacher only acts on assessments/grades of their own courses, and only while
the period is open. Every service receives the acting membership.
"""

from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.academics.models import AcademicPeriod, PeriodStatus, Subject
from apps.academics.services import default_grading_scale
from apps.people.models import EnrollmentStatus, QualificationStatus, StudentEnrollment
from common.permissions import ADMIN_ROLES, membership_has_role, require_role

from .models import (
    Assessment,
    AssessmentStatus,
    ClassPrincipalAssignment,
    Course,
    Grade,
    GradeChangeLog,
    ReportCard,
    ReportCardLine,
    ReportCardStatus,
)

# =============================================================================
# Permissions
# =============================================================================


def is_school_admin(membership, school):
    return membership is not None and membership.school_id == school.pk and membership_has_role(membership, ADMIN_ROLES)


def teaches(membership, course):
    """True if `membership` is the teacher of `course` (and still a TEACHER)."""
    return (
        membership is not None
        and course.teacher.employee.membership_id == membership.pk
        and membership_has_role(membership, {"TEACHER"})
    )


def require_course_access(membership, course):
    if not (is_school_admin(membership, course.school) or teaches(membership, course)):
        raise PermissionDenied("Only the course's teacher or a school administrator can do this.")


# =============================================================================
# Scales and rounding
# =============================================================================


def course_scale(course):
    """Scale of a course's averages: course → subject default → school default."""
    return course.grading_scale or course.subject.default_grading_scale or default_grading_scale(course.school)


def express(fraction, scale):
    """Express a 0..1 fraction in `scale`, rounded to its decimals (max 2,
    the precision of the stored averages)."""
    if fraction is None:
        return None
    places = min(scale.decimal_places, 2)
    quantum = Decimal(1).scaleb(-places)
    return (fraction * scale.max_score).quantize(quantum, rounding=ROUND_HALF_UP)


# =============================================================================
# Courses
# =============================================================================


def create_course(
    school_class, subject, teacher, *, actor, coefficient=Decimal("1.00"), weekly_hours=0, grading_scale=None
):
    """Assign a teacher to teach a subject in a class (administrators only).

    The teacher must hold a non-rejected qualification for the subject that is
    not waiting for review: the compatibility process (people phase) has to be
    completed before a course is assigned.
    """
    require_role(actor, ADMIN_ROLES, school=school_class.school)
    # Re-read from the database: the caller's instance may be stale (e.g.
    # deactivated meanwhile by another administrator).
    subject = Subject.objects.select_related("category").get(pk=subject.pk)
    if not (subject.active and subject.category.active):
        raise ValidationError("This subject (or its category) is inactive.", code="subject_inactive")
    qualification = teacher.qualifications.filter(subject=subject).first()
    if qualification is None or qualification.status in (QualificationStatus.PENDING, QualificationStatus.REJECTED):
        raise ValidationError(
            "The teacher has no accepted qualification for this subject.", code="teacher_not_qualified"
        )
    return Course.objects.create(
        school=school_class.school,
        school_class=school_class,
        subject=subject,
        teacher=teacher,
        academic_year=school_class.academic_year,
        coefficient=coefficient,
        weekly_hours=weekly_hours,
        grading_scale=grading_scale,
    )


# =============================================================================
# Assessments
# =============================================================================


def _require_open(period):
    if period.status != PeriodStatus.OPEN:
        raise ValidationError("This academic period is not open.", code="period_not_open")


def create_assessment(
    course, period, *, actor, name, assessment_type, max_score, weight=Decimal("1.00"), assessment_date=None
):
    require_course_access(actor, course)
    if not course.active:
        raise ValidationError("This course is inactive.", code="course_inactive")
    if period.academic_year_id != course.academic_year_id:
        raise ValidationError("The period belongs to another academic year.", code="period_other_year")
    if period.children.exists():
        # Assessments live in leaf periods (Séquence, or Semestre without
        # children); parent periods are computed from their children.
        raise ValidationError("Assessments must be attached to a leaf period.", code="period_not_leaf")
    _require_open(period)
    return Assessment.objects.create(
        school=course.school,
        course=course,
        academic_period=period,
        academic_year=course.academic_year,
        name=name,
        assessment_type=assessment_type,
        max_score=max_score,
        weight=weight,
        assessment_date=assessment_date,
        created_by=actor,
    )


# =============================================================================
# Grades
# =============================================================================


def _check_grade_writable(assessment):
    if assessment.status != AssessmentStatus.OPEN:
        raise ValidationError("This assessment is closed.", code="assessment_closed")
    _require_open(assessment.academic_period)


def _check_score(assessment, score):
    score = Decimal(str(score))
    if score < 0 or score > assessment.max_score:
        raise ValidationError(f"The score must be between 0 and {assessment.max_score}.", code="score_out_of_range")
    return score


def _check_enrolled(assessment, student):
    enrolled = StudentEnrollment.objects.filter(
        student=student,
        school_class_id=assessment.course.school_class_id,
        academic_year_id=assessment.academic_year_id,
    ).exclude(status=EnrollmentStatus.WITHDRAWN)
    if not enrolled.exists():
        raise ValidationError("The student is not enrolled in this course's class.", code="student_not_enrolled")


def enter_grade(assessment, student, score, *, actor, comment=None, coefficient_override=None):
    require_course_access(actor, assessment.course)
    _check_grade_writable(assessment)
    _check_enrolled(assessment, student)
    return Grade.objects.create(
        school=assessment.school,
        assessment=assessment,
        student=student,
        score=_check_score(assessment, score),
        max_score=assessment.max_score,
        coefficient_override=coefficient_override,
        comment=comment,
        entered_by=actor,
    )


@transaction.atomic
def enter_grades_bulk(assessment, entries, *, actor):
    """All-or-nothing entry of several grades: one invalid line rejects the
    whole batch (no half-entered assessment)."""
    return [
        enter_grade(
            assessment,
            entry["student"],
            entry["score"],
            actor=actor,
            comment=entry.get("comment"),
            coefficient_override=entry.get("coefficient_override"),
        )
        for entry in entries
    ]


class StaleGrade(ValidationError):
    pass


@transaction.atomic
def update_grade(grade, new_score, *, actor, reason, expected_score=None):
    """Correct a grade, recording an immutable GradeChangeLog entry.

    - a reason is mandatory;
    - the row is locked (SELECT ... FOR UPDATE) so two simultaneous
      corrections are serialised;
    - optimistic check (spec §6 concurrency): if the client sends the score
      it last saw (`expected_score`) and it no longer matches, the update is
      refused instead of silently overwriting a newer value.
    """
    if not reason or not str(reason).strip():
        raise ValidationError("A reason is required to change a grade.", code="reason_required")
    grade = (
        Grade.objects.select_for_update()
        .select_related("assessment__course__teacher__employee", "assessment__academic_period")
        .get(pk=grade.pk)
    )
    require_course_access(actor, grade.assessment.course)
    _check_grade_writable(grade.assessment)
    if expected_score is not None and Decimal(str(expected_score)) != grade.score:
        raise StaleGrade("The grade was changed by someone else in the meantime.", code="stale_grade")
    new_score = _check_score(grade.assessment, new_score)
    if new_score == grade.score:
        return grade
    GradeChangeLog.objects.create(
        school=grade.school,
        grade=grade,
        changed_by=actor,
        old_score=grade.score,
        new_score=new_score,
        reason=str(reason).strip(),
    )
    grade.score = new_score
    grade.save(update_fields=["score", "updated_at"])
    return grade


# =============================================================================
# Period closing
# =============================================================================


def _descendants(period):
    result, frontier = [], [period]
    while frontier:
        children = list(AcademicPeriod.objects.filter(parent_period__in=frontier))
        result.extend(children)
        frontier = children
    return result


@transaction.atomic
def close_period(period, *, actor):
    """Close a period, its sub-periods and their assessments: grades become
    read-only (also enforced by a PostgreSQL trigger)."""
    require_role(actor, ADMIN_ROLES, school=period.school)
    periods = [period, *_descendants(period)]
    AcademicPeriod.objects.filter(pk__in=[p.pk for p in periods]).update(status=PeriodStatus.CLOSED)
    Assessment.objects.filter(academic_period__in=periods).update(status=AssessmentStatus.CLOSED)
    period.status = PeriodStatus.CLOSED
    return period


@transaction.atomic
def reopen_period(period, *, actor):
    """Reopen a period for corrections. Refused if a VALIDATED report card
    exists for it: an official result must not change underneath."""
    require_role(actor, ADMIN_ROLES, school=period.school)
    periods = [period, *_descendants(period)]
    ancestors_and_self = [period]
    parent = period.parent_period
    while parent is not None:
        ancestors_and_self.append(parent)
        parent = parent.parent_period
    if ReportCard.objects.filter(
        academic_period__in=[*periods, *ancestors_and_self], status=ReportCardStatus.VALIDATED
    ).exists():
        raise ValidationError("A validated report card exists for this period.", code="report_card_validated")
    AcademicPeriod.objects.filter(pk__in=[p.pk for p in periods]).update(status=PeriodStatus.OPEN)
    Assessment.objects.filter(academic_period__in=periods).update(status=AssessmentStatus.OPEN)
    period.status = PeriodStatus.OPEN
    return period


# =============================================================================
# Averages
# =============================================================================


def _leaf_fraction(student_id, course_ids, period):
    grades = Grade.objects.filter(
        student_id=student_id, assessment__course_id__in=course_ids, assessment__academic_period=period
    ).select_related("assessment")
    total_weight = Decimal(0)
    total = Decimal(0)
    for grade in grades:
        weight = grade.coefficient_override or grade.assessment.weight
        total += weight * grade.score / grade.assessment.max_score
        total_weight += weight
    return total / total_weight if total_weight else None


def subject_fraction(student_id, course_ids, period):
    """Average of a student for a set of courses (same subject) over a
    period, as a 0..1 fraction; None when there is no grade at all."""
    children = list(period.children.all())
    if not children:
        return _leaf_fraction(student_id, course_ids, period)
    child_fractions = [f for f in (subject_fraction(student_id, course_ids, c) for c in children) if f is not None]
    return sum(child_fractions) / len(child_fractions) if child_fractions else None


@dataclass
class SubjectLine:
    subject: object
    course_ids: list
    coefficient: Decimal
    teacher_names: str


def class_subject_lines(school_class):
    """The subjects taught in a class, one line per subject (several courses
    of the same subject are pooled; their coefficients must agree)."""
    by_subject = defaultdict(list)
    for course in Course.objects.filter(school_class=school_class, active=True).select_related(
        "subject", "teacher__employee__membership__user"
    ):
        by_subject[course.subject].append(course)
    lines = []
    for subject, courses in by_subject.items():
        coefficients = {c.coefficient for c in courses}
        if len(coefficients) > 1:
            raise ValidationError(
                f"Courses of {subject} in {school_class} have different coefficients.", code="coefficient_conflict"
            )
        lines.append(
            SubjectLine(
                subject=subject,
                course_ids=[c.pk for c in courses],
                coefficient=coefficients.pop(),
                teacher_names=", ".join(sorted(c.teacher.employee.membership.user.full_name for c in courses)),
            )
        )
    return sorted(lines, key=lambda line: line.subject.name)


def general_average(lines_with_averages):
    """Σ(average × coefficient) / Σ coefficient; None if no subject average."""
    rows = [(avg, coef) for avg, coef in lines_with_averages if avg is not None]
    total_coef = sum(coef for _, coef in rows)
    if not total_coef:
        return None
    return sum(avg * coef for avg, coef in rows) / total_coef


def competition_ranks(values):
    """{key: rank} with ties sharing a rank: 15, 14, 14, 12 -> 1, 2, 2, 4."""
    ordered = sorted(values.items(), key=lambda kv: kv[1], reverse=True)
    ranks, previous, rank = {}, None, 0
    for position, (key, value) in enumerate(ordered, start=1):
        if value != previous:
            rank, previous = position, value
        ranks[key] = rank
    return ranks


# =============================================================================
# Report cards
# =============================================================================


@dataclass
class ClassResults:
    """Live results of a class for a period, in the school's default scale.
    Single source for report cards AND the class dashboard, so both always
    show the same numbers."""

    scale: object
    subject_lines: list
    # student pk -> (student, [(SubjectLine, average)], general average or None)
    students: dict
    ranks: dict  # student pk -> rank (students with an average only)


def compute_class_results(school_class, period):
    if period.academic_year_id != school_class.academic_year_id:
        raise ValidationError("The period belongs to another academic year.", code="period_other_year")
    scale = default_grading_scale(school_class.school)
    subject_lines = class_subject_lines(school_class)
    students = [
        e.student
        for e in StudentEnrollment.objects.filter(school_class=school_class)
        .exclude(status=EnrollmentStatus.WITHDRAWN)
        .select_related("student")
        .order_by("student__last_name", "student__first_name")
    ]
    computed = {}
    for student in students:
        lines = []
        for line in subject_lines:
            average = express(subject_fraction(student.pk, line.course_ids, period), scale)
            if average is not None:
                lines.append((line, average))
        avg = general_average((a, line.coefficient) for line, a in lines)
        computed[student.pk] = (student, lines, express(avg / scale.max_score, scale) if avg is not None else None)
    ranks = competition_ranks({pk: avg for pk, (_, _, avg) in computed.items() if avg is not None})
    return ClassResults(scale=scale, subject_lines=subject_lines, students=computed, ranks=ranks)


@transaction.atomic
def generate_report_cards(school_class, period, *, actor):
    """(Re)compute DRAFT report cards of every student of the class for the
    period. Validated cards are frozen and never recomputed."""
    require_role(actor, ADMIN_ROLES, school=school_class.school)
    results = compute_class_results(school_class, period)
    scale, computed, ranks = results.scale, results.students, results.ranks
    now = timezone.now()
    cards = []
    for pk, (student, lines, avg) in computed.items():
        card = ReportCard.objects.filter(student=student, academic_period=period).first()
        if card is not None and card.status == ReportCardStatus.VALIDATED:
            cards.append(card)
            continue
        if card is None:
            card = ReportCard(school=school_class.school, student=student, academic_period=period)
        card.general_average = avg
        card.scale_max_score = scale.max_score
        card.rank = ranks.get(pk)
        card.class_size = len(ranks) if pk in ranks else None
        card.generated_at = now
        card.save()
        card.lines.all().delete()
        ReportCardLine.objects.bulk_create(
            ReportCardLine(
                school=card.school,
                report_card=card,
                subject=line.subject,
                average=average,
                coefficient=line.coefficient,
                weighted_average=(average * line.coefficient).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                teacher_name_snapshot=line.teacher_names[:250],
            )
            for line, average in lines
        )
        cards.append(card)
    return cards


def validate_report_card(card, *, actor):
    """Freeze a report card (spec §6.6 POST report-cards/{id}/validate/).
    Only for a CLOSED period: validated results must not move afterwards."""
    require_role(actor, ADMIN_ROLES, school=card.school)
    if card.status == ReportCardStatus.VALIDATED:
        raise ValidationError("This report card is already validated.", code="already_validated")
    if card.academic_period.status != PeriodStatus.CLOSED:
        raise ValidationError("Close the period before validating its report cards.", code="period_not_closed")
    card.status = ReportCardStatus.VALIDATED
    card.validated_by = actor
    card.validated_at = timezone.now()
    card.save(update_fields=["status", "validated_by", "validated_at", "updated_at"])
    return card


# =============================================================================
# Evolution
# =============================================================================


def student_evolution(student, academic_year):
    """Period-by-period evolution of a student over a year (spec §6.6
    GET students/{id}/evolution/): general average and per-subject averages
    for every period of the year, in the school's default scale."""
    enrollment = StudentEnrollment.objects.filter(student=student, academic_year=academic_year).first()
    if enrollment is None:
        return []
    scale = default_grading_scale(student.school)
    subject_lines = class_subject_lines(enrollment.school_class)
    evolution = []
    for period in AcademicPeriod.objects.filter(academic_year=academic_year).order_by("start_date", "order_index"):
        subjects = []
        for line in subject_lines:
            average = express(subject_fraction(student.pk, line.course_ids, period), scale)
            if average is not None:
                subjects.append({"subject": line.subject.code, "average": average, "coefficient": line.coefficient})
        avg = general_average((s["average"], s["coefficient"]) for s in subjects)
        evolution.append(
            {
                "period_id": str(period.pk),
                "period": period.name,
                "parent_period_id": str(period.parent_period_id) if period.parent_period_id else None,
                "general_average": express(avg / scale.max_score, scale) if avg is not None else None,
                "scale_max_score": scale.max_score,
                "subjects": subjects,
            }
        )
    return evolution


# =============================================================================
# Class principal & class dashboard
# =============================================================================


@transaction.atomic
def assign_class_principal(school_class, teacher, *, actor, start_date=None):
    """Make `teacher` the principal teacher of the class. The previous one is
    ended (history kept); at most one active principal (PostgreSQL)."""
    require_role(actor, ADMIN_ROLES, school=school_class.school)
    if teacher.school_id != school_class.school_id:
        raise PermissionDenied("This teacher belongs to another school.")
    start = start_date or timezone.localdate()
    for previous in ClassPrincipalAssignment.objects.select_for_update().filter(school_class=school_class, active=True):
        previous.active = False
        previous.end_date = max(start, previous.start_date)
        previous.save(update_fields=["active", "end_date", "updated_at"])
    return ClassPrincipalAssignment.objects.create(
        school=school_class.school, school_class=school_class, teacher=teacher, start_date=start, assigned_by=actor
    )


def current_principal(school_class):
    assignment = ClassPrincipalAssignment.objects.filter(school_class=school_class, active=True).select_related(
        "teacher__employee__membership__user"
    )
    return assignment.first()


def can_view_class_dashboard(membership, school_class):
    """Admins of the school, or the class's ACTIVE principal teacher."""
    if is_school_admin(membership, school_class.school):
        return True
    principal = current_principal(school_class)
    return (
        principal is not None
        and principal.teacher.employee.membership_id == membership.pk
        and membership_has_role(membership, {"TEACHER"})
    )


def class_dashboard(school_class, period, *, actor):
    """Read-only overview of a class for a period (spec §6.4 dashboard):
    per-subject class averages, per-student general averages and ranks, and
    the students below SchoolConfiguration.low_average_threshold (expressed in
    the school's default scale)."""
    if not can_view_class_dashboard(actor, school_class):
        raise PermissionDenied("Only an administrator or the class's principal teacher can see this dashboard.")
    results = compute_class_results(school_class, period)
    threshold = school_class.school.configuration.low_average_threshold
    principal = current_principal(school_class)

    subjects = []
    for line in results.subject_lines:
        averages = [avg for _, lines, _ in results.students.values() for sl, avg in lines if sl is line]
        subjects.append(
            {
                "subject": line.subject.code,
                "subject_name": line.subject.name,
                "coefficient": line.coefficient,
                "teachers": line.teacher_names,
                "class_average": express(sum(averages) / len(averages) / results.scale.max_score, results.scale)
                if averages
                else None,
                "graded_students": len(averages),
            }
        )
    students = [
        {
            "id": str(pk),
            "name": student.full_name,
            "general_average": avg,
            "rank": results.ranks.get(pk),
            "below_threshold": avg is not None and avg < threshold,
        }
        for pk, (student, _, avg) in results.students.items()
    ]
    general = [s["general_average"] for s in students if s["general_average"] is not None]
    return {
        "school_class": {"id": str(school_class.pk), "name": school_class.name},
        "academic_period": {"id": str(period.pk), "name": period.name, "status": period.status},
        "principal": principal.teacher.employee.membership.user.full_name if principal else None,
        "scale_max_score": results.scale.max_score,
        "low_average_threshold": threshold,
        "student_count": len(students),
        "class_general_average": express(sum(general) / len(general) / results.scale.max_score, results.scale)
        if general
        else None,
        "subjects": subjects,
        "students": students,
    }
