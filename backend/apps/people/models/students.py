"""Students and their yearly enrollments (spec §4.4)."""

from django.db import models
from django.db.models import F, Q

from common.models import TenantModel, TenantQuerySet


class StudentStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Actif"
    SUSPENDED = "SUSPENDED", "Suspendu"
    LEFT = "LEFT", "Parti"  # left the school (transfer, dropout...)
    GRADUATED = "GRADUATED", "Diplômé"
    ARCHIVED = "ARCHIVED", "Archivé"


class Sex(models.TextChoices):
    MALE = "M", "Masculin"
    FEMALE = "F", "Féminin"


class HardDeleteForbidden(Exception):
    """Raised when code tries to physically delete a student."""


class StudentQuerySet(TenantQuerySet):
    def delete(self):
        raise HardDeleteForbidden("Students are archived (services.archive_student), never deleted.")


class Student(TenantModel):
    """Master record of a pupil — the person, independent of any year.

    Identifiers (three different things, on purpose):
    - `id` (UUID): technical key, never shown to users, never guessable;
    - `student_number`: the school's matricule, printed on cards/reports;
    - `registration_number`: the administrative registration number.
    Both business numbers are unique *per school* (ADR 0003).

    What is NOT here: the class. A class is year-specific, so it lives in
    StudentEnrollment; Student keeps only what does not change every year.

    Archiving instead of deleting: grades, payments and attendance will
    reference the student for years. `delete()` is therefore forbidden (Python
    side) and every FK to Student is PROTECT (database side). Use
    services.archive_student(), which sets status=ARCHIVED + archived_at.
    """

    student_number = models.CharField(max_length=50, db_index=True)
    registration_number = models.CharField(max_length=50, db_index=True)
    first_name = models.CharField(max_length=120, db_index=True)
    last_name = models.CharField(max_length=120, db_index=True)
    date_of_birth = models.DateField()
    sex = models.CharField(max_length=10, choices=Sex.choices)
    photo = models.ImageField(upload_to="students/photos/", blank=True, null=True)
    birth_place = models.CharField(max_length=160, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    height_cm = models.PositiveIntegerField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=StudentStatus.choices, default=StudentStatus.ACTIVE, db_index=True)
    archived_at = models.DateTimeField(blank=True, null=True)

    objects = StudentQuerySet.as_manager()

    class Meta:
        ordering = ["last_name", "first_name"]
        constraints = [
            models.UniqueConstraint(fields=["school", "student_number"], name="student_school_number_unique"),
            models.UniqueConstraint(
                fields=["school", "registration_number"], name="student_school_registration_unique"
            ),
            models.CheckConstraint(condition=Q(status__in=StudentStatus.values), name="student_status_valid"),
            models.CheckConstraint(condition=Q(sex__in=Sex.values), name="student_sex_valid"),
            # Archived <=> archived_at set: the two can never disagree.
            models.CheckConstraint(
                condition=(Q(status=StudentStatus.ARCHIVED) & Q(archived_at__isnull=False))
                | (~Q(status=StudentStatus.ARCHIVED) & Q(archived_at__isnull=True)),
                name="student_archived_consistent",
            ),
            models.CheckConstraint(
                condition=Q(height_cm__isnull=True) | Q(height_cm__gt=0), name="student_height_positive"
            ),
        ]

    def delete(self, *args, **kwargs):
        raise HardDeleteForbidden("Students are archived (services.archive_student), never deleted.")

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def __str__(self):
        return f"{self.full_name} ({self.student_number})"


class EnrollmentStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "En cours"
    COMPLETED = "COMPLETED", "Terminée"  # the year ended normally
    WITHDRAWN = "WITHDRAWN", "Retirée"  # left during the year


class PromotionStatus(models.TextChoices):
    """End-of-year decision. The software may *suggest* (once grades exist),
    but the decision is recorded only by a human (services.decide_promotion)."""

    PENDING = "PENDING", "En attente"
    PROMOTED = "PROMOTED", "Admis"
    REPEATING = "REPEATING", "Redouble"
    REDIRECTED = "REDIRECTED", "Réorienté"
    LEFT = "LEFT", "Parti"
    GRADUATED = "GRADUATED", "Diplômé"
    OTHER = "OTHER", "Autre"


class StudentEnrollment(TenantModel):
    """One student in one class for one academic year.

    This is the history the spec asks for (§5: "class membership is
    year-scoped, not a permanent student attribute"):

        2025-2026 → 3e A   (promotion_status = PROMOTED)
        2026-2027 → 2nde C (promotion_status = PENDING)

    Rules enforced by PostgreSQL:
    - one enrollment per student and per year;
    - end_date >= enrollment_date;
    - a decided promotion has a decision date;
    - student, class and year belong to the enrollment's school, and the class
      belongs to the enrollment's year (composite foreign keys, ADR 0008).
    """

    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="enrollments")
    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT, related_name="enrollments")
    school_class = models.ForeignKey("academics.SchoolClass", on_delete=models.PROTECT, related_name="enrollments")
    enrollment_date = models.DateField()
    end_date = models.DateField(blank=True, null=True)
    status = models.CharField(
        max_length=20, choices=EnrollmentStatus.choices, default=EnrollmentStatus.ACTIVE, db_index=True
    )
    promotion_status = models.CharField(max_length=20, choices=PromotionStatus.choices, default=PromotionStatus.PENDING)
    # Who decided. SET_NULL: the decision survives if that admin leaves.
    decision_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )
    decision_date = models.DateTimeField(blank=True, null=True)
    decision_note = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["-academic_year__start_date"]
        constraints = [
            models.UniqueConstraint(fields=["student", "academic_year"], name="enrollment_student_year_unique"),
            models.CheckConstraint(
                condition=Q(end_date__isnull=True) | Q(end_date__gte=F("enrollment_date")),
                name="enrollment_dates_ordered",
            ),
            models.CheckConstraint(condition=Q(status__in=EnrollmentStatus.values), name="enrollment_status_valid"),
            models.CheckConstraint(
                condition=Q(promotion_status__in=PromotionStatus.values), name="enrollment_promotion_status_valid"
            ),
            models.CheckConstraint(
                condition=Q(promotion_status=PromotionStatus.PENDING) | Q(decision_date__isnull=False),
                name="enrollment_decision_dated",
            ),
        ]

    def __str__(self):
        return f"{self.student} → {self.school_class}"
