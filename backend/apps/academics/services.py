"""Business services of the academic structure.

Rules that span several rows (a period inside its year, the "category
required" school setting...) cannot be CHECK constraints: they live here.
Rules that fit in one row or in a relation are already enforced by
PostgreSQL (see models.py and the composite keys of migration 0002); the
services re-check some of them only to give a clear error message.

All functions raise django.core.exceptions.ValidationError with a stable
`code` when a rule is broken.
"""

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import (
    AcademicPeriod,
    AcademicYear,
    AcademicYearStatus,
    GradingScale,
    PedagogicalCategory,
    Subject,
    SubjectType,
)

# Initial pedagogical categories of a new school (configurable afterwards:
# they are ordinary rows, not code).
DEFAULT_CATEGORIES = [
    ("LITERARY", "Littéraire"),
    ("SCIENTIFIC", "Scientifique"),
    ("ARTISTIC", "Artistique"),
    ("ESF", "Économie sociale et familiale"),
    ("TECHNICAL", "Technique"),
]


# Initial grading scales (code, label, max, pass, is_default). Configurable.
DEFAULT_SCALES = [
    ("SUR20", "/20", 20, 10, True),
    ("SUR100", "/100", 100, 50, False),
    ("SUR60", "/60", 60, 30, False),
]


def seed_default_grading_scales(school):
    """Create the default scales if missing. Idempotent."""
    for code, label, max_score, pass_score, is_default in DEFAULT_SCALES:
        GradingScale.objects.get_or_create(
            school=school,
            code=code,
            defaults={"label": label, "max_score": max_score, "pass_score": pass_score, "is_default": is_default},
        )


def default_grading_scale(school):
    """The school's reference scale (report cards). Raises if not configured."""
    scale = GradingScale.objects.filter(school=school, is_default=True).first()
    if scale is None:
        raise ValidationError("The school has no default grading scale.", code="no_default_scale")
    return scale


def seed_default_categories(school):
    """Create the default categories if missing. Idempotent."""
    for code, name in DEFAULT_CATEGORIES:
        PedagogicalCategory.objects.get_or_create(school=school, code=code, defaults={"name": name})


# -----------------------------------------------------------------------------
# Academic years
# -----------------------------------------------------------------------------


def create_academic_year(school, *, name, start_date, end_date, status=AcademicYearStatus.PLANNED):
    """Overlaps and duplicate names are refused by PostgreSQL (IntegrityError)."""
    return AcademicYear.objects.create(
        school=school, name=name, start_date=start_date, end_date=end_date, status=status
    )


@transaction.atomic
def set_current_year(year):
    """Make `year` the single current year of its school (and ACTIVE).

    The previous current year is un-flagged in the same transaction; the
    partial unique index guarantees there is never a second current year,
    even with two administrators clicking at the same time.
    """
    if year.status in (AcademicYearStatus.CLOSED, AcademicYearStatus.ARCHIVED):
        raise ValidationError("A closed or archived year cannot become current.", code="year_closed")
    AcademicYear.objects.filter(school=year.school, is_current=True).exclude(pk=year.pk).update(is_current=False)
    year.status = AcademicYearStatus.ACTIVE
    year.is_current = True
    year.save(update_fields=["status", "is_current", "updated_at"])
    return year


# -----------------------------------------------------------------------------
# Academic periods
# -----------------------------------------------------------------------------


def create_period(academic_year, *, name, period_type, order_index, start_date, end_date, parent=None, **extra):
    """Create a period, optionally inside a parent period.

    Checked here (cross-row rules):
    - the period lies within its academic year;
    - a child lies within its parent and belongs to the same year.
    Checked by PostgreSQL: sibling order unique, siblings not overlapping,
    parent in the same year and school.
    """
    if start_date < academic_year.start_date or end_date > academic_year.end_date:
        raise ValidationError("The period must lie within its academic year.", code="period_outside_year")
    if parent is not None:
        if parent.academic_year_id != academic_year.id:
            raise ValidationError("The parent period belongs to another year.", code="parent_other_year")
        if start_date < parent.start_date or end_date > parent.end_date:
            raise ValidationError("The period must lie within its parent period.", code="period_outside_parent")
    return AcademicPeriod.objects.create(
        school=academic_year.school,
        academic_year=academic_year,
        parent_period=parent,
        name=name,
        period_type=period_type,
        order_index=order_index,
        start_date=start_date,
        end_date=end_date,
        **extra,
    )


# -----------------------------------------------------------------------------
# Subjects
# -----------------------------------------------------------------------------


def create_subject(school, *, code, name, category, subject_type=SubjectType.THEORETICAL, **extra):
    """Create a subject. The category is mandatory (NOT NULL in PostgreSQL)
    and must belong to the same school (composite FK)."""
    return Subject.objects.create(
        school=school, code=code, name=name, subject_type=subject_type, category=category, **extra
    )
