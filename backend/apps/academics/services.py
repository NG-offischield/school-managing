"""Business services of the academic structure.

Rules that span several rows (a period inside its year, an active category
of the same school...) cannot be CHECK constraints: they live here.
Rules that fit in one row or in a relation are already enforced by
PostgreSQL (see models.py and the composite keys of migration 0002); the
services re-check some of them only to give a clear error message.

All functions raise django.core.exceptions.ValidationError with a stable
`code` when a rule is broken.
"""

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.services import snapshot
from common.permissions import ADMIN_ROLES, require_role

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
# Catalogue administration: pedagogical categories and subjects (ADR 0010)
# -----------------------------------------------------------------------------
#
# Every write:
# - checks the actor is ADMIN / SUPER_ADMIN *of the school of the data*;
# - checks the referenced rows belong to that school and are active;
# - is written to the AuditLog (ADMINISTRATIVE layer) in the same transaction.
# `code` is the stable identifier used by clients, compatibility rules and
# imports: it is set at creation and never changed. Rows are never deleted
# (PROTECT everywhere): they are deactivated, and reactivated if needed.

CATEGORY_FIELDS = ["code", "name", "description", "active"]
SUBJECT_FIELDS = ["code", "name", "category", "subject_type", "default_grading_scale", "active", "public_visible"]


def _normalise_code(code):
    code = (code or "").strip().upper()
    if not code:
        raise ValidationError("A code is required.", code="code_required")
    return code


def _audit(action, actor, entity, old=None, new=None):
    from apps.audit.models import AuditLayer
    from apps.audit.services import record_audit

    record_audit(action, actor=actor, entity=entity, old=old, new=new, layer=AuditLayer.ADMINISTRATIVE)


@transaction.atomic
def create_category(school, *, actor, code, name, description=None):
    require_role(actor, ADMIN_ROLES, school=school)
    code = _normalise_code(code)
    if PedagogicalCategory.objects.filter(school=school, code=code).exists():
        raise ValidationError(f"A category with code {code} already exists.", code="duplicate_code")
    category = PedagogicalCategory.objects.create(school=school, code=code, name=name.strip(), description=description)
    _audit("CATEGORY_CREATED", actor, category, new=snapshot(category, CATEGORY_FIELDS))
    return category


@transaction.atomic
def update_category(category, *, actor, **changes):
    """Editable: name, description (the code is immutable)."""
    require_role(actor, ADMIN_ROLES, school=category.school)
    category = PedagogicalCategory.objects.select_for_update().get(pk=category.pk)
    if "code" in changes and _normalise_code(changes["code"]) != category.code:
        raise ValidationError("The code of a category cannot be changed.", code="code_immutable")
    old = snapshot(category, CATEGORY_FIELDS)
    if "name" in changes:
        category.name = changes["name"].strip()
    if "description" in changes:
        category.description = changes["description"]
    category.save()
    _audit("CATEGORY_UPDATED", actor, category, old=old, new=snapshot(category, CATEGORY_FIELDS))
    return category


@transaction.atomic
def set_category_active(category, active, *, actor):
    """Deactivate / reactivate. A category still used by ACTIVE subjects
    cannot be deactivated (409): deactivate or move those subjects first."""
    require_role(actor, ADMIN_ROLES, school=category.school)
    category = PedagogicalCategory.objects.select_for_update().get(pk=category.pk)
    if not active and category.subjects.filter(active=True).exists():
        raise ValidationError("This category is still used by active subjects.", code="category_in_use")
    if category.active != active:
        old = snapshot(category, CATEGORY_FIELDS)
        category.active = active
        category.save(update_fields=["active", "updated_at"])
        action = "CATEGORY_ACTIVATED" if active else "CATEGORY_DEACTIVATED"
        _audit(action, actor, category, old=old, new=snapshot(category, CATEGORY_FIELDS))
    return category


def _check_category(school, category):
    if category is None:
        raise ValidationError("A subject must belong to a pedagogical category.", code="category_required")
    if category.school_id != school.pk:
        # The API never gets here (out-of-school ids are 404): defence in depth.
        raise ValidationError("The category belongs to another school.", code="category_other_school")
    if not category.active:
        raise ValidationError("This category is inactive.", code="category_inactive")


def _check_scale(school, scale):
    if scale is not None and (scale.school_id != school.pk or not scale.active):
        raise ValidationError("Invalid grading scale for this school.", code="grading_scale_invalid")


@transaction.atomic
def create_subject(
    school,
    *,
    actor,
    code,
    name,
    category,
    subject_type=SubjectType.THEORETICAL,
    default_grading_scale=None,
    public_visible=False,
):
    """Create a subject in exactly ONE existing, active category of the school."""
    require_role(actor, ADMIN_ROLES, school=school)
    code = _normalise_code(code)
    _check_category(school, category)
    _check_scale(school, default_grading_scale)
    if Subject.objects.filter(school=school, code=code).exists():
        raise ValidationError(f"A subject with code {code} already exists.", code="duplicate_code")
    subject = Subject.objects.create(
        school=school,
        code=code,
        name=name.strip(),
        category=category,
        subject_type=subject_type,
        default_grading_scale=default_grading_scale,
        public_visible=public_visible,
    )
    _audit("SUBJECT_CREATED", actor, subject, new=snapshot(subject, SUBJECT_FIELDS))
    return subject


@transaction.atomic
def update_subject(subject, *, actor, **changes):
    """Editable: name, category, subject_type, default_grading_scale,
    public_visible. Changing the category only affects FUTURE compatibility
    evaluations; existing qualifications keep their recorded result."""
    require_role(actor, ADMIN_ROLES, school=subject.school)
    subject = Subject.objects.select_for_update().get(pk=subject.pk)
    if "code" in changes and _normalise_code(changes["code"]) != subject.code:
        raise ValidationError("The code of a subject cannot be changed.", code="code_immutable")
    if "category" in changes:
        _check_category(subject.school, changes["category"])
    if "default_grading_scale" in changes:
        _check_scale(subject.school, changes["default_grading_scale"])
    old = snapshot(subject, SUBJECT_FIELDS)
    for field in ("category", "subject_type", "default_grading_scale", "public_visible"):
        if field in changes:
            setattr(subject, field, changes[field])
    if "name" in changes:
        subject.name = changes["name"].strip()
    subject.save()
    _audit("SUBJECT_UPDATED", actor, subject, old=old, new=snapshot(subject, SUBJECT_FIELDS))
    return subject


@transaction.atomic
def set_subject_active(subject, active, *, actor):
    """Deactivate / reactivate a subject. Deactivation is refused (409) while
    an active course of a planned/active year still teaches it. Reactivation
    requires an active category."""
    require_role(actor, ADMIN_ROLES, school=subject.school)
    subject = Subject.objects.select_for_update().get(pk=subject.pk)
    if (
        not active
        and subject.courses.filter(
            active=True, academic_year__status__in=[AcademicYearStatus.PLANNED, AcademicYearStatus.ACTIVE]
        ).exists()
    ):
        raise ValidationError("This subject is still taught in an active course.", code="subject_in_use")
    if active:
        _check_category(subject.school, subject.category)
    if subject.active != active:
        old = snapshot(subject, SUBJECT_FIELDS)
        subject.active = active
        subject.save(update_fields=["active", "updated_at"])
        action = "SUBJECT_ACTIVATED" if active else "SUBJECT_DEACTIVATED"
        _audit(action, actor, subject, old=old, new=snapshot(subject, SUBJECT_FIELDS))
    return subject
