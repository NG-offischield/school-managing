"""Academic core (spec §4.4): from teaching assignment to report card.

    Course (class × subject × teacher × year, coefficient, scale)
      └── Assessment (in a LEAF period: Séquence 1, or Semestre 1)
            └── Grade (one per student; score <= max_score)
                  └── GradeChangeLog (immutable history of corrections)
    ReportCard (student × period, frozen once VALIDATED)
      └── ReportCardLine (one per subject: average, coefficient, weighted)

Database guarantees (besides CHECK / UNIQUE):
- every relation stays inside one school (composite FKs, migration 0002);
- a course's class belongs to the course's year; an assessment's period and
  course belong to the assessment's year;
- a grade carries a copy of its assessment's max_score, kept equal by a
  composite FK with ON UPDATE CASCADE, so `score <= max_score` is a plain
  CHECK — and lowering an assessment's max_score below an existing score is
  refused;
- grades can only be written while their assessment AND period are OPEN, and
  GradeChangeLog rows can never be modified or deleted (triggers, migration
  0003).
"""

from decimal import Decimal

from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Round
from django.utils import timezone

from common.models import TenantModel

# =============================================================================
# Course
# =============================================================================


class Course(TenantModel):
    """A teaching assignment: who teaches which subject to which class, in
    which year, with which coefficient (spec §4.4).

    It is also the *teacher's scope*: a teacher may enter grades only for
    assessments of their own courses, and sees only students enrolled in the
    classes of their courses.
    """

    school_class = models.ForeignKey("academics.SchoolClass", on_delete=models.PROTECT, related_name="courses")
    subject = models.ForeignKey("academics.Subject", on_delete=models.PROTECT, related_name="courses")
    teacher = models.ForeignKey("people.TeacherProfile", on_delete=models.PROTECT, related_name="courses")
    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT, related_name="courses")
    # Scale of this course's averages; NULL -> subject default -> school default.
    grading_scale = models.ForeignKey(
        "academics.GradingScale", on_delete=models.SET_NULL, blank=True, null=True, related_name="courses"
    )
    coefficient = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("1.00"))
    weekly_hours = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school_class", "subject", "academic_year", "teacher"], name="course_unique"
            ),
            models.CheckConstraint(condition=Q(coefficient__gt=0), name="course_coefficient_positive"),
            models.CheckConstraint(condition=Q(weekly_hours__gte=0), name="course_weekly_hours_not_negative"),
        ]

    def __str__(self):
        return f"{self.subject} — {self.school_class}"


# =============================================================================
# Assessment
# =============================================================================


class AssessmentType(models.TextChoices):
    TEST = "TEST", "Interrogation"
    EXAM = "EXAM", "Devoir / examen"
    HOMEWORK = "HOMEWORK", "Devoir maison"
    ORAL = "ORAL", "Oral"
    PRACTICAL = "PRACTICAL", "Travaux pratiques"
    PROJECT = "PROJECT", "Projet"
    OTHER = "OTHER", "Autre"


class AssessmentStatus(models.TextChoices):
    OPEN = "OPEN", "Ouverte"  # grades can be entered and corrected
    CLOSED = "CLOSED", "Clôturée"  # frozen (also when its period is closed)


class Assessment(TenantModel):
    """An assessment event of a course in one LEAF period.

    `max_score` is the assessment's own scale (a test may be /10 even if the
    course is /20): grades are converted, nothing assumes /20.
    `weight` is its weight inside the period average.

    `academic_year` is an addition to the spec (ADR 0009): it lets PostgreSQL
    check, with composite keys, that the period and the course belong to the
    same academic year.
    """

    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="assessments")
    academic_period = models.ForeignKey(
        "academics.AcademicPeriod", on_delete=models.PROTECT, related_name="assessments"
    )
    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT, related_name="assessments")
    name = models.CharField(max_length=120)
    assessment_type = models.CharField(max_length=30, choices=AssessmentType.choices)
    max_score = models.DecimalField(max_digits=8, decimal_places=2)
    weight = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("1.00"))
    assessment_date = models.DateField(blank=True, null=True)
    status = models.CharField(
        max_length=20, choices=AssessmentStatus.choices, default=AssessmentStatus.OPEN, db_index=True
    )
    created_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )

    class Meta:
        ordering = ["academic_period__order_index", "assessment_date", "created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(max_score__gt=0), name="assessment_max_score_positive"),
            models.CheckConstraint(condition=Q(weight__gt=0), name="assessment_weight_positive"),
            models.CheckConstraint(
                condition=Q(assessment_type__in=AssessmentType.values), name="assessment_type_valid"
            ),
            models.CheckConstraint(condition=Q(status__in=AssessmentStatus.values), name="assessment_status_valid"),
        ]

    def __str__(self):
        return f"{self.name} ({self.course})"


# =============================================================================
# Grade and its history
# =============================================================================


class Grade(TenantModel):
    """One student's score on one assessment.

    `max_score` is a copy of the assessment's max_score (addition to the spec,
    ADR 0009) maintained by PostgreSQL (composite FK, ON UPDATE CASCADE): it
    makes "score <= max_score" a database CHECK.

    `coefficient_override`: when set, replaces the assessment's weight for this
    student's grade (e.g. a make-up exam counted differently).
    """

    assessment = models.ForeignKey(Assessment, on_delete=models.PROTECT, related_name="grades")
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT, related_name="grades")
    score = models.DecimalField(max_digits=8, decimal_places=2)
    max_score = models.DecimalField(max_digits=8, decimal_places=2)
    coefficient_override = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    comment = models.TextField(blank=True, null=True)
    # PROTECT: who entered a grade is part of its history.
    entered_by = models.ForeignKey("accounts.SchoolMembership", on_delete=models.PROTECT, related_name="+")
    entered_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["assessment", "student"], name="grade_assessment_student_unique"),
            models.CheckConstraint(condition=Q(score__gte=0), name="grade_score_not_negative"),
            models.CheckConstraint(condition=Q(score__lte=F("max_score")), name="grade_score_within_max"),
            models.CheckConstraint(
                condition=Q(coefficient_override__isnull=True) | Q(coefficient_override__gt=0),
                name="grade_coefficient_override_positive",
            ),
        ]

    def __str__(self):
        return f"{self.student} — {self.assessment}: {self.score}/{self.max_score}"


class GradeChangeLog(TenantModel):
    """Immutable history of grade corrections (spec §9: "Grade changes create
    immutable change history"). Written by services.update_grade in the same
    transaction as the change; a trigger forbids UPDATE and DELETE."""

    grade = models.ForeignKey(Grade, on_delete=models.PROTECT, related_name="changes")
    changed_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )
    old_score = models.DecimalField(max_digits=8, decimal_places=2)
    new_score = models.DecimalField(max_digits=8, decimal_places=2)
    reason = models.TextField(blank=True, null=True)
    changed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["changed_at"]

    def __str__(self):
        return f"{self.grade}: {self.old_score} → {self.new_score}"


# =============================================================================
# Report cards
# =============================================================================


class ReportCardStatus(models.TextChoices):
    DRAFT = "DRAFT", "Brouillon"  # recomputed at will
    VALIDATED = "VALIDATED", "Validé"  # frozen official result


class ReportCard(TenantModel):
    """Official result of a student for one period (sequence, trimester,
    semester...). Recomputed while DRAFT, frozen once VALIDATED.

    Additions to the spec (ADR 0009): `validated_at`, and `scale_max_score`, a
    snapshot of the reference scale used, so a frozen card stays readable even
    if the school changes its scales later.
    """

    student = models.ForeignKey("people.Student", on_delete=models.PROTECT, related_name="report_cards")
    academic_period = models.ForeignKey(
        "academics.AcademicPeriod", on_delete=models.PROTECT, related_name="report_cards"
    )
    status = models.CharField(
        max_length=20, choices=ReportCardStatus.choices, default=ReportCardStatus.DRAFT, db_index=True
    )
    general_average = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    scale_max_score = models.DecimalField(max_digits=8, decimal_places=2)
    rank = models.PositiveIntegerField(blank=True, null=True)
    class_size = models.PositiveIntegerField(blank=True, null=True)
    generated_at = models.DateTimeField(blank=True, null=True)
    validated_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )
    validated_at = models.DateTimeField(blank=True, null=True)
    # PDF rendering belongs to the reports phase.
    pdf_path = models.FileField(upload_to="report_cards/", blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["student", "academic_period"], name="report_card_student_period_unique"),
            models.CheckConstraint(condition=Q(status__in=ReportCardStatus.values), name="report_card_status_valid"),
            models.CheckConstraint(condition=Q(scale_max_score__gt=0), name="report_card_scale_positive"),
            models.CheckConstraint(
                condition=Q(general_average__isnull=True)
                | (Q(general_average__gte=0) & Q(general_average__lte=F("scale_max_score"))),
                name="report_card_average_within_scale",
            ),
            models.CheckConstraint(
                condition=Q(status=ReportCardStatus.DRAFT) | Q(validated_at__isnull=False),
                name="report_card_validation_dated",
            ),
            models.CheckConstraint(
                condition=Q(rank__isnull=True) | (Q(rank__gte=1) & Q(rank__lte=F("class_size"))),
                name="report_card_rank_within_class",
            ),
        ]

    def __str__(self):
        return f"Bulletin {self.student} — {self.academic_period}"


class ReportCardLine(TenantModel):
    """Frozen per-subject line: average (in the reference scale),
    coefficient, weighted average = average × coefficient (CHECK)."""

    report_card = models.ForeignKey(ReportCard, on_delete=models.CASCADE, related_name="lines")
    subject = models.ForeignKey("academics.Subject", on_delete=models.PROTECT, related_name="+")
    average = models.DecimalField(max_digits=8, decimal_places=2)
    coefficient = models.DecimalField(max_digits=6, decimal_places=2)
    weighted_average = models.DecimalField(max_digits=10, decimal_places=2)
    teacher_name_snapshot = models.CharField(max_length=250, blank=True, null=True)
    appreciation = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["subject__name"]
        constraints = [
            models.UniqueConstraint(fields=["report_card", "subject"], name="report_card_line_subject_unique"),
            models.CheckConstraint(condition=Q(average__gte=0), name="report_card_line_average_not_negative"),
            models.CheckConstraint(condition=Q(coefficient__gt=0), name="report_card_line_coefficient_positive"),
            models.CheckConstraint(
                condition=Q(weighted_average=Round(F("average") * F("coefficient"), 2)),
                name="report_card_line_weighted_consistent",
            ),
        ]

    def __str__(self):
        return f"{self.report_card} — {self.subject}"
