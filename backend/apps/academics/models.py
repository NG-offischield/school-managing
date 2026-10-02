"""Academic structure of a school (spec §4.4).

How the pieces fit together
---------------------------

    School
     ├── AcademicYear  (2025-2026, 2026-2027 ... historical years are kept)
     │     └── AcademicPeriod  (hierarchical: Trimestre 1 → Séquence 1, 2 ...)
     ├── Level         (6e, 5e ... Tle, or L1, L2 ... ordered, configurable)
     ├── PedagogicalCategory (LITERARY, SCIENTIFIC ... configurable)
     │     └── Subject (THEORETICAL / PRACTICAL)
     ├── SubjectCompatibilityRule (category × subject × [level] → allowed?)
     └── SchoolClass   (3e A for 2025-2026: a level + a year)

Every model belongs to exactly one School (TenantModel). Relations between
two tenant-owned rows are additionally protected in PostgreSQL by composite
foreign keys (common.migration_operations.EnforceSameValue): the database
itself refuses e.g. a subject of school A in a category of school B.
"""

import uuid

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateRangeField, RangeBoundary, RangeOperators
from django.db import models
from django.db.models import F, Func, Q, Value
from django.db.models.functions import Coalesce

from common.models import TenantModel


class DateRange(Func):
    """SQL `daterange(start, end, '[]')`: both bounds included."""

    function = "DATERANGE"
    output_field = DateRangeField()


def _inclusive_range(start, end):
    return DateRange(start, end, RangeBoundary(inclusive_lower=True, inclusive_upper=True))


# =============================================================================
# Academic years
# =============================================================================


class AcademicYearStatus(models.TextChoices):
    PLANNED = "PLANNED", "Planifiée"  # being prepared (classes, fees...)
    ACTIVE = "ACTIVE", "En cours"
    CLOSED = "CLOSED", "Clôturée"  # results frozen, kept for history
    ARCHIVED = "ARCHIVED", "Archivée"


class AcademicYear(TenantModel):
    """A school year, e.g. "2025-2026".

    Why it exists: almost everything a school records is *year-scoped*
    (classes, enrollments, grades, fees). Years are never deleted, so history
    stays queryable ("which class was this student in in 2024-2025?").

    Rules enforced by PostgreSQL:
    - names are unique per school;
    - end_date > start_date;
    - at most ONE current year per school (partial unique index);
    - the current year must be ACTIVE;
    - two years of the same school never overlap in time (exclusion
      constraint on the date range, needs the btree_gist extension).
    """

    name = models.CharField(max_length=30)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(
        max_length=20, choices=AcademicYearStatus.choices, default=AcademicYearStatus.PLANNED, db_index=True
    )
    # The year used by default in screens and new records. Changed only
    # through services.set_current_year(), which keeps it unique.
    is_current = models.BooleanField(default=False)

    class Meta:
        ordering = ["-start_date"]
        constraints = [
            models.UniqueConstraint(fields=["school", "name"], name="academic_year_school_name_unique"),
            models.CheckConstraint(condition=Q(end_date__gt=F("start_date")), name="academic_year_dates_ordered"),
            models.CheckConstraint(
                condition=Q(status__in=AcademicYearStatus.values), name="academic_year_status_valid"
            ),
            models.UniqueConstraint(
                fields=["school"], condition=Q(is_current=True), name="academic_year_one_current_per_school"
            ),
            models.CheckConstraint(
                condition=Q(is_current=False) | Q(status=AcademicYearStatus.ACTIVE),
                name="academic_year_current_is_active",
            ),
            ExclusionConstraint(
                name="academic_year_no_overlap",
                expressions=[
                    ("school", RangeOperators.EQUAL),
                    (_inclusive_range("start_date", "end_date"), RangeOperators.OVERLAPS),
                ],
            ),
        ]

    def __str__(self):
        return self.name


# =============================================================================
# Academic periods (hierarchical)
# =============================================================================


class PeriodType(models.TextChoices):
    """Kinds of periods. The *hierarchy* is not hard-coded: any period may
    have a parent, so both organisations below are possible:

        Secondary school (Cameroon)        University
        Trimestre 1                        Semestre 1
          ├── Séquence 1                   Semestre 2
          └── Séquence 2
    """

    SEMESTER = "SEMESTER", "Semestre"
    TRIMESTER = "TRIMESTER", "Trimestre"
    TERM = "TERM", "Terme"
    QUARTER = "QUARTER", "Quadrimestre"
    SEQUENCE = "SEQUENCE", "Séquence"
    OTHER = "OTHER", "Autre"


class PeriodStatus(models.TextChoices):
    PLANNED = "PLANNED", "Planifiée"
    OPEN = "OPEN", "Ouverte"  # grades can be entered (later phase)
    CLOSED = "CLOSED", "Clôturée"


# Stand-in for "no parent" so that top-level periods are compared with each
# other by the exclusion constraint (NULL is never equal to NULL in SQL).
_NO_PARENT = uuid.UUID(int=0)


class AcademicPeriod(TenantModel):
    """A slice of an academic year: semester, trimester, sequence...

    Why a single self-referencing model instead of `Trimester` + `Sequence`
    tables: schools organise their year differently (2 semesters, 3
    trimesters of 2 sequences, ...). `parent_period` expresses any tree.

    Rules enforced by PostgreSQL:
    - end_date >= start_date; a period is not its own parent;
    - unique order among siblings (same year, same parent);
    - siblings never overlap in time (exclusion constraint);
    - the year belongs to the same school, and a child period belongs to the
      same year as its parent (composite foreign keys, migration 0002).
    Rules enforced by services (they span several rows): dates inside the
    year and inside the parent period; no cycles deeper than one level.
    """

    academic_year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name="periods")
    # SET_NULL as in the spec: removing a parent keeps its children (they
    # become top-level) rather than deleting graded periods by cascade.
    parent_period = models.ForeignKey("self", on_delete=models.SET_NULL, blank=True, null=True, related_name="children")
    name = models.CharField(max_length=100)
    period_type = models.CharField(max_length=30, choices=PeriodType.choices, db_index=True)
    order_index = models.PositiveIntegerField()
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=20, choices=PeriodStatus.choices, default=PeriodStatus.OPEN, db_index=True)

    class Meta:
        ordering = ["academic_year", "order_index"]
        constraints = [
            models.CheckConstraint(condition=Q(end_date__gte=F("start_date")), name="period_dates_ordered"),
            models.CheckConstraint(condition=Q(period_type__in=PeriodType.values), name="period_type_valid"),
            models.CheckConstraint(condition=Q(status__in=PeriodStatus.values), name="period_status_valid"),
            models.CheckConstraint(condition=~Q(parent_period=F("id")), name="period_not_own_parent"),
            models.UniqueConstraint(
                fields=["academic_year", "parent_period", "order_index"],
                nulls_distinct=False,
                name="period_sibling_order_unique",
            ),
            ExclusionConstraint(
                name="period_siblings_no_overlap",
                expressions=[
                    ("academic_year", RangeOperators.EQUAL),
                    (
                        Coalesce("parent_period", Value(_NO_PARENT, output_field=models.UUIDField())),
                        RangeOperators.EQUAL,
                    ),
                    (_inclusive_range("start_date", "end_date"), RangeOperators.OVERLAPS),
                ],
            ),
        ]

    def __str__(self):
        return self.name


# =============================================================================
# Levels
# =============================================================================


class Level(TenantModel):
    """An academic level: 6e, 5e ... Tle, or L1, L2 ... (configurable).

    `order_index` gives the progression used by promotions (5e comes after 6e).
    `cycle` groups levels into school-defined contexts (COLLEGE, LYCEE,
    TECHNICAL, UNIVERSITY ...): free text so future structures need no code
    change. (`cycle` is an addition to spec §4.4, see ADR 0008.)
    """

    code = models.CharField(max_length=30)
    name = models.CharField(max_length=100)
    cycle = models.CharField(max_length=40, blank=True, default="")
    order_index = models.PositiveIntegerField(default=0)
    # Optional prefix used to build class names ("6" for "6e A") — spec field.
    first_character = models.CharField(max_length=5, blank=True, null=True)
    active = models.BooleanField(default=True)
    public_visible = models.BooleanField(default=False)

    class Meta:
        ordering = ["order_index", "code"]
        constraints = [
            models.UniqueConstraint(fields=["school", "code"], name="level_school_code_unique"),
        ]

    def __str__(self):
        return self.name


# =============================================================================
# Pedagogical categories and subjects
# =============================================================================


class PedagogicalCategory(TenantModel):
    """Family of teaching profiles: LITERARY, SCIENTIFIC, ARTISTIC, ESF,
    TECHNICAL ... The list is data, not code: each school can add, rename or
    deactivate categories. Defaults are created when a school is provisioned
    (services.DEFAULT_CATEGORIES).

    Used by: Subject (the subject's family) and TeacherProfile (the
    teacher's training), compared by SubjectCompatibilityRule.
    """

    code = models.CharField(max_length=40)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, null=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        verbose_name_plural = "pedagogical categories"
        constraints = [
            models.UniqueConstraint(fields=["school", "code"], name="pedagogical_category_school_code_unique"),
        ]

    def __str__(self):
        return self.code


class SubjectType(models.TextChoices):
    # Taught in any classroom: mathematics, history, geography, SVTEEHB...
    THEORETICAL = "THEORETICAL", "Théorique"
    # Needs a dedicated place or equipment: sport, laboratory, workshop...
    # (room constraints arrive with the scheduling phase; nothing is imposed
    # on theoretical subjects).
    PRACTICAL = "PRACTICAL", "Pratique"


class Subject(TenantModel):
    """A taught subject (catalogue of the school).

    `category` is nullable: a subject belongs to a pedagogical category when
    the school's rule requires it (SchoolConfiguration.subject_category_required,
    checked by services.create_subject). Deviation from spec §4.4, where the
    column is NOT NULL — see ADR 0008.
    """

    code = models.CharField(max_length=30)
    name = models.CharField(max_length=120)
    category = models.ForeignKey(
        PedagogicalCategory, on_delete=models.PROTECT, blank=True, null=True, related_name="subjects"
    )
    subject_type = models.CharField(
        max_length=20, choices=SubjectType.choices, default=SubjectType.THEORETICAL, db_index=True
    )
    active = models.BooleanField(default=True)
    public_visible = models.BooleanField(default=False)
    # Spec field `default_grading_scale` (FK GradingScale) arrives with the
    # grades phase, together with GradingScale itself (ADR 0008).

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["school", "code"], name="subject_school_code_unique"),
            models.CheckConstraint(condition=Q(subject_type__in=SubjectType.values), name="subject_type_valid"),
        ]

    def __str__(self):
        return self.name


class SubjectCompatibilityRule(TenantModel):
    """Compatibility matrix: may a teacher of `pedagogical_category` teach
    `subject` (optionally only at `level`)?

    The rule gives a *recommendation*, never the final decision (spec §15):

        compatible  requires_admin_review   meaning
        ----------  ---------------------   --------------------------------
        True        False                   compatible
        True        True                    compatible, but an admin reviews
        False       True                    incompatible, admin may accept
        False       False                   incompatible: refused (an audited
                                            CompatibilityOverride is the only
                                            way around it)

    A rule with `level` set is more specific than one with level NULL (all
    levels); `priority` breaks remaining ties. The algorithm lives in
    apps/people/compatibility.py.
    """

    pedagogical_category = models.ForeignKey(
        PedagogicalCategory, on_delete=models.PROTECT, related_name="compatibility_rules"
    )
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="compatibility_rules")
    level = models.ForeignKey(
        Level, on_delete=models.PROTECT, blank=True, null=True, related_name="compatibility_rules"
    )
    compatible = models.BooleanField(default=True)
    requires_admin_review = models.BooleanField(default=False)
    priority = models.PositiveSmallIntegerField(default=0)

    class Meta:
        constraints = [
            # nulls_distinct=False: only ONE "all levels" rule per pair.
            models.UniqueConstraint(
                fields=["school", "pedagogical_category", "subject", "level"],
                nulls_distinct=False,
                name="compatibility_rule_unique",
            ),
        ]

    def __str__(self):
        return f"{self.pedagogical_category} × {self.subject} ({self.level or 'tous niveaux'})"


# =============================================================================
# Classes
# =============================================================================


class SchoolClass(TenantModel):
    """A class (section) for one academic year: "3e A — 2025-2026".

    Why it is year-scoped: next year "3e A" is a different group of students.
    A student's class is therefore never stored on Student; it is the
    StudentEnrollment of the year (apps/people).

    Not in the phase list but required: StudentEnrollment.school_class is
    mandatory in the spec. `main_room` (FK Room) arrives with the scheduling
    phase (ADR 0008).
    """

    name = models.CharField(max_length=80, db_index=True)
    level = models.ForeignKey(Level, on_delete=models.PROTECT, related_name="classes")
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name="classes")
    capacity = models.PositiveIntegerField(blank=True, null=True)
    active = models.BooleanField(default=True)
    public_visible = models.BooleanField(default=False)

    class Meta:
        ordering = ["level__order_index", "name"]
        verbose_name_plural = "school classes"
        constraints = [
            models.UniqueConstraint(fields=["school", "name", "academic_year"], name="class_school_name_year_unique"),
            models.CheckConstraint(
                condition=Q(capacity__isnull=True) | Q(capacity__gt=0), name="class_capacity_positive"
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.academic_year})"
