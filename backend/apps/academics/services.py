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
    SchoolClass,
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


# =============================================================================
# Classes (admin desktop: Gestion académique → Classes)
# =============================================================================
# A class is identified by its NAME inside its school and academic year
# (spec §4.4, UNIQUE(school, name, academic_year) in PostgreSQL); there is no
# separate code. The year is fixed at creation: enrollments, courses and
# sessions hang on (class, year), so moving a class to another year would
# break them. The main room is delegated to the planning service, which
# owns the room rules (same school, active, capacity vs enrolled pupils).

CLASS_FIELDS = ["name", "level", "academic_year", "capacity", "main_room", "active", "public_visible"]
OPEN_YEAR_STATUSES = (AcademicYearStatus.PLANNED, AcademicYearStatus.ACTIVE)


def _class_name(name):
    name = (name or "").strip()
    if not name:
        raise ValidationError("A class name is required.", code="name_required")
    return name


def _check_level(school, level):
    if level is None:
        raise ValidationError("A class must belong to a level.", code="level_required")
    if level.school_id != school.pk:
        # The API never gets here (out-of-school ids are 404): defence in depth.
        raise ValidationError("The level belongs to another school.", code="level_other_school")
    if not level.active:
        raise ValidationError("This level is inactive.", code="level_inactive")


def _check_year(school, year):
    if year is None:
        raise ValidationError("A class must belong to an academic year.", code="academic_year_required")
    if year.school_id != school.pk:
        raise ValidationError("The academic year belongs to another school.", code="academic_year_other_school")
    if year.status not in OPEN_YEAR_STATUSES:
        raise ValidationError("This academic year is closed.", code="year_closed")


def _check_capacity(capacity):
    if capacity is not None and capacity <= 0:
        raise ValidationError("The capacity must be positive.", code="invalid_capacity")


def _unique_class_name(school, year, name, exclude=None):
    duplicates = SchoolClass.objects.filter(school=school, academic_year=year, name__iexact=name)
    if exclude is not None:
        duplicates = duplicates.exclude(pk=exclude.pk)
    if duplicates.exists():
        raise ValidationError(
            f"A class named {name} already exists for this academic year.", code="duplicate_class_name"
        )


def _set_main_room(school_class, room, actor):
    # Lazy import: scheduling depends on academics, not the other way round.
    from apps.scheduling.services import set_class_main_room

    return set_class_main_room(school_class, room, actor=actor)


@transaction.atomic
def create_class(school, *, actor, name, level, academic_year, capacity=None, main_room=None, public_visible=False):
    require_role(actor, ADMIN_ROLES, school=school)
    name = _class_name(name)
    _check_level(school, level)
    _check_year(school, academic_year)
    _check_capacity(capacity)
    _unique_class_name(school, academic_year, name)
    school_class = SchoolClass.objects.create(
        school=school,
        name=name,
        level=level,
        academic_year=academic_year,
        capacity=capacity,
        public_visible=public_visible,
    )
    if main_room is not None:
        school_class = _set_main_room(school_class, main_room, actor)
    _audit("CLASS_CREATED", actor, school_class, new=snapshot(school_class, CLASS_FIELDS))
    return school_class


@transaction.atomic
def update_class(school_class, *, actor, **changes):
    """Editable: name, level, capacity, main_room, public_visible. The academic
    year is fixed at creation (409 class_year_immutable)."""
    require_role(actor, ADMIN_ROLES, school=school_class.school)
    school_class = SchoolClass.objects.select_for_update().get(pk=school_class.pk)
    school = school_class.school
    if "academic_year" in changes and changes["academic_year"] != school_class.academic_year:
        raise ValidationError("The academic year of a class cannot be changed.", code="class_year_immutable")
    if school_class.academic_year.status not in OPEN_YEAR_STATUSES:
        raise ValidationError("This academic year is closed.", code="year_closed")
    old = snapshot(school_class, CLASS_FIELDS)
    if "name" in changes:
        name = _class_name(changes["name"])
        _unique_class_name(school, school_class.academic_year, name, exclude=school_class)
        school_class.name = name
    if "level" in changes and changes["level"] != school_class.level:
        _check_level(school, changes["level"])
        school_class.level = changes["level"]
    if "capacity" in changes:
        _check_capacity(changes["capacity"])
        school_class.capacity = changes["capacity"]
    if "public_visible" in changes:
        school_class.public_visible = bool(changes["public_visible"])
    school_class.save()
    if "main_room" in changes and changes["main_room"] != school_class.main_room:
        school_class = _set_main_room(school_class, changes["main_room"], actor)
    _audit("CLASS_UPDATED", actor, school_class, old=old, new=snapshot(school_class, CLASS_FIELDS))
    return school_class


@transaction.atomic
def set_class_active(school_class, active, *, actor):
    """Deactivate / reactivate. Deactivation is refused (409 class_in_use)
    while pupils are actively enrolled or an active course still runs in the
    class (planning and grades rely on an active class). Reactivation needs
    an open year and an active level."""
    require_role(actor, ADMIN_ROLES, school=school_class.school)
    school_class = SchoolClass.objects.select_for_update().get(pk=school_class.pk)
    if not active:
        from apps.people.models import EnrollmentStatus

        if school_class.enrollments.filter(status=EnrollmentStatus.ACTIVE).exists():
            raise ValidationError("Pupils are still enrolled in this class.", code="class_in_use")
        if school_class.courses.filter(active=True).exists():
            raise ValidationError("Active courses still run in this class.", code="class_in_use")
    else:
        _check_year(school_class.school, school_class.academic_year)
        _check_level(school_class.school, school_class.level)
    if school_class.active != active:
        old = snapshot(school_class, CLASS_FIELDS)
        school_class.active = active
        school_class.save(update_fields=["active", "updated_at"])
        _audit(
            "CLASS_ACTIVATED" if active else "CLASS_DEACTIVATED",
            actor,
            school_class,
            old=old,
            new=snapshot(school_class, CLASS_FIELDS),
        )
    return school_class
