"""Academic structure: years, periods, levels, categories, subjects, rules, classes."""

from datetime import date

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.academics import services
from apps.academics.models import (
    AcademicPeriod,
    AcademicYear,
    AcademicYearStatus,
    PedagogicalCategory,
    PeriodType,
    SchoolClass,
    Subject,
    SubjectCompatibilityRule,
    SubjectType,
)
from apps.core.services import FirstAdmin, SchoolProvisioningService

from .conftest import DB
from .factories import (
    AcademicYearFactory,
    CategoryFactory,
    LevelFactory,
    SchoolClassFactory,
    SchoolFactory,
    SubjectFactory,
    admin_of,
)

pytestmark = DB


def db_rejects():
    """IntegrityError raised by PostgreSQL itself, inside a savepoint."""
    return pytest.raises(IntegrityError)


# =============================================================================
# AcademicYear
# =============================================================================


def make_year(school, name="2025-2026", start=date(2025, 9, 1), end=date(2026, 7, 31), **kw):
    return services.create_academic_year(school, name=name, start_date=start, end_date=end, **kw)


def test_several_historical_years_per_school(school):
    make_year(school, "2024-2025", date(2024, 9, 1), date(2025, 7, 31), status=AcademicYearStatus.CLOSED)
    make_year(school)
    assert AcademicYear.objects.for_school(school).count() == 2


def test_year_name_unique_per_school_but_not_globally(school):
    make_year(school)
    make_year(SchoolFactory())  # same name, other school: fine
    with db_rejects(), transaction.atomic():
        make_year(school, start=date(2030, 9, 1), end=date(2031, 7, 1))


def test_year_end_must_follow_start(school):
    with db_rejects(), transaction.atomic():
        make_year(school, start=date(2026, 9, 1), end=date(2026, 9, 1))


def test_years_of_a_school_cannot_overlap(school):
    """Exclusion constraint (btree_gist): two years sharing even one day are refused."""
    make_year(school)
    with db_rejects(), transaction.atomic():
        make_year(school, "2026-2027", date(2026, 7, 31), date(2027, 7, 31))
    # Same dates in ANOTHER school are fine.
    make_year(SchoolFactory())


def test_only_one_current_year_per_school(school):
    a = make_year(school, status=AcademicYearStatus.ACTIVE)
    b = make_year(school, "2026-2027", date(2026, 9, 1), date(2027, 7, 31), status=AcademicYearStatus.ACTIVE)
    AcademicYear.objects.filter(pk=a.pk).update(is_current=True)
    with db_rejects(), transaction.atomic():
        AcademicYear.objects.filter(pk=b.pk).update(is_current=True)


def test_current_year_must_be_active(school):
    year = make_year(school)  # PLANNED
    with db_rejects(), transaction.atomic():
        AcademicYear.objects.filter(pk=year.pk).update(is_current=True)


def test_set_current_year_switches_atomically(school):
    old = services.set_current_year(make_year(school))
    new = services.set_current_year(make_year(school, "2026-2027", date(2026, 9, 1), date(2027, 7, 31)))
    old.refresh_from_db()
    assert (old.is_current, new.is_current, new.status) == (False, True, AcademicYearStatus.ACTIVE)


def test_closed_year_cannot_become_current(school):
    year = make_year(school, status=AcademicYearStatus.CLOSED)
    with pytest.raises(ValidationError) as exc:
        services.set_current_year(year)
    assert exc.value.code == "year_closed"


# =============================================================================
# AcademicPeriod — flexible hierarchy
# =============================================================================


def test_secondary_school_trimesters_with_sequences(school):
    """Trimestre 1 ├── Séquence 1 └── Séquence 2"""
    year = make_year(school)
    t1 = services.create_period(
        year,
        name="Trimestre 1",
        period_type=PeriodType.TRIMESTER,
        order_index=1,
        start_date=date(2025, 9, 1),
        end_date=date(2025, 12, 20),
    )
    s1 = services.create_period(
        year,
        name="Séquence 1",
        period_type=PeriodType.SEQUENCE,
        order_index=1,
        start_date=date(2025, 9, 1),
        end_date=date(2025, 10, 31),
        parent=t1,
    )
    s2 = services.create_period(
        year,
        name="Séquence 2",
        period_type=PeriodType.SEQUENCE,
        order_index=2,
        start_date=date(2025, 11, 1),
        end_date=date(2025, 12, 20),
        parent=t1,
    )
    assert list(t1.children.order_by("order_index")) == [s1, s2]
    assert s1.parent_period == t1


def test_university_semesters_without_children(school):
    year = make_year(school)
    for i, (start, end) in enumerate([(date(2025, 9, 1), date(2026, 1, 31)), (date(2026, 2, 1), date(2026, 7, 31))], 1):
        services.create_period(
            year, name=f"Semestre {i}", period_type=PeriodType.SEMESTER, order_index=i, start_date=start, end_date=end
        )
    assert AcademicPeriod.objects.filter(academic_year=year, parent_period__isnull=True).count() == 2


def test_period_must_lie_in_its_year_and_parent(school):
    year = make_year(school)
    with pytest.raises(ValidationError) as exc:
        services.create_period(
            year,
            name="X",
            period_type=PeriodType.TERM,
            order_index=1,
            start_date=date(2025, 8, 1),
            end_date=date(2025, 10, 1),
        )
    assert exc.value.code == "period_outside_year"
    t1 = services.create_period(
        year,
        name="T1",
        period_type=PeriodType.TRIMESTER,
        order_index=1,
        start_date=date(2025, 9, 1),
        end_date=date(2025, 12, 20),
    )
    with pytest.raises(ValidationError) as exc:
        services.create_period(
            year,
            name="S",
            period_type=PeriodType.SEQUENCE,
            order_index=1,
            start_date=date(2025, 12, 1),
            end_date=date(2026, 1, 15),
            parent=t1,
        )
    assert exc.value.code == "period_outside_parent"


def _raw_period(year, **kw):
    defaults = dict(
        school=year.school,
        academic_year=year,
        name="P",
        period_type=PeriodType.TERM,
        order_index=1,
        start_date=date(2025, 9, 1),
        end_date=date(2025, 10, 1),
    )
    return AcademicPeriod.objects.create(**{**defaults, **kw})


def test_sibling_periods_cannot_overlap_or_share_order(school):
    year = make_year(school)
    _raw_period(year)
    with db_rejects(), transaction.atomic():  # same order among top-level siblings
        _raw_period(year, start_date=date(2025, 11, 1), end_date=date(2025, 12, 1))
    with db_rejects(), transaction.atomic():  # overlapping top-level siblings
        _raw_period(year, order_index=2, start_date=date(2025, 9, 15), end_date=date(2025, 11, 1))


def test_child_periods_may_overlap_their_parent(school):
    year = make_year(school)
    parent = _raw_period(year, end_date=date(2025, 12, 1))
    _raw_period(year, parent_period=parent, start_date=date(2025, 9, 1), end_date=date(2025, 10, 1))


def test_parent_from_another_year_is_refused_by_postgresql(school):
    """Composite FK (parent_period, academic_year)."""
    year = make_year(school)
    other_year = make_year(school, "2026-2027", date(2026, 9, 1), date(2027, 7, 31))
    parent = _raw_period(other_year, start_date=date(2026, 9, 1), end_date=date(2026, 12, 1))
    with db_rejects(), transaction.atomic():
        _raw_period(year, parent_period=parent)


def test_period_cannot_be_its_own_parent(school):
    period = _raw_period(make_year(school))
    with db_rejects(), transaction.atomic():
        AcademicPeriod.objects.filter(pk=period.pk).update(parent_period=period)


def test_period_type_is_constrained(school):
    with db_rejects(), transaction.atomic():
        _raw_period(make_year(school), period_type="WEEK")


# =============================================================================
# Levels
# =============================================================================


def test_levels_are_ordered_and_support_several_cycles(school):
    LevelFactory(school=school, code="2NDE", order_index=5, cycle="LYCEE")
    LevelFactory(school=school, code="6E", order_index=1, cycle="COLLEGE")
    LevelFactory(school=school, code="F1", order_index=2, cycle="TECHNICAL")
    assert [lv.code for lv in school_levels(school)] == ["6E", "F1", "2NDE"]


def school_levels(school):
    from apps.academics.models import Level

    return Level.objects.for_school(school)


def test_level_code_unique_per_school(school):
    LevelFactory(school=school, code="6E")
    LevelFactory(school=SchoolFactory(), code="6E")
    with db_rejects(), transaction.atomic():
        LevelFactory(school=school, code="6E")


# =============================================================================
# Pedagogical categories & subjects
# =============================================================================


def test_provisioned_school_gets_default_categories_which_stay_configurable():
    school = (
        SchoolProvisioningService()
        .provision(
            code="P1",
            name="P",
            city="Douala",
            address="x",
            admin=FirstAdmin("boss", "boss@example.cm", "B", "O", "Very-Strong-Pass-2026"),
        )
        .school
    )
    codes = set(PedagogicalCategory.objects.for_school(school).values_list("code", flat=True))
    assert codes == {"LITERARY", "SCIENTIFIC", "ARTISTIC", "ESF", "TECHNICAL"}
    # Configurable: just data.
    CategoryFactory(school=school, code="SPORTS")
    PedagogicalCategory.objects.filter(school=school, code="ESF").update(active=False)


def test_category_code_unique_per_school(school):
    CategoryFactory(school=school, code="SCI")
    with db_rejects(), transaction.atomic():
        CategoryFactory(school=school, code="SCI")


def test_subject_category_is_mandatory_in_postgresql(school):
    """NOT NULL in the database: no runtime setting can bypass it."""
    with db_rejects(), transaction.atomic():
        Subject.objects.create(school=school, code="MATH", name="Mathématiques", category=None)
    subject = SubjectFactory(school=school)
    with db_rejects(), transaction.atomic():
        Subject.objects.filter(pk=subject.pk).update(category=None)


def test_subject_has_exactly_one_category(school):
    sci = CategoryFactory(school=school, code="SCIENTIFIC")
    subject = services.create_subject(
        school, actor=admin_of(school), code="EPS", name="Sport", category=sci, subject_type=SubjectType.PRACTICAL
    )
    assert subject.category == sci and sci.subjects.get() == subject


def test_theoretical_and_practical_subjects(school):
    admin = admin_of(school)
    sci = CategoryFactory(school=school, code="SCIENTIFIC")
    for code in ("MATH", "HIST", "GEO", "SVTEEHB"):
        services.create_subject(school, actor=admin, code=code, name=code, category=sci)
    for code in ("EPS", "LABO", "ATELIER"):
        services.create_subject(
            school, actor=admin, code=code, name=code, category=sci, subject_type=SubjectType.PRACTICAL
        )
    assert Subject.objects.for_school(school).filter(subject_type=SubjectType.THEORETICAL).count() == 4
    with db_rejects(), transaction.atomic():
        SubjectFactory(school=school, subject_type="ONLINE")


def test_subject_code_unique_per_school(school):
    SubjectFactory(school=school, code="MATH")
    SubjectFactory(school=SchoolFactory(), code="MATH")
    with db_rejects(), transaction.atomic():
        SubjectFactory(school=school, code="MATH")


def test_subject_category_of_another_school_is_refused_by_postgresql(school):
    foreign_category = CategoryFactory(school=SchoolFactory())
    with db_rejects(), transaction.atomic():
        Subject.objects.create(school=school, code="X", name="X", category=foreign_category)


# =============================================================================
# Compatibility rules
# =============================================================================


def test_one_rule_per_category_subject_level_including_all_levels(school):
    category, subject, level = (
        CategoryFactory(school=school),
        SubjectFactory(school=school),
        LevelFactory(school=school),
    )

    def rule(**kw):
        return SubjectCompatibilityRule.objects.create(
            school=school, pedagogical_category=category, subject=subject, **kw
        )

    rule()  # all levels
    rule(level=level)  # specific level: allowed alongside
    with db_rejects(), transaction.atomic():
        rule()  # second "all levels" rule (NULL level treated as equal)
    with db_rejects(), transaction.atomic():
        rule(level=level)


def test_rule_mixing_schools_is_refused_by_postgresql(school):
    other = SchoolFactory()
    with db_rejects(), transaction.atomic():
        SubjectCompatibilityRule.objects.create(
            school=school, pedagogical_category=CategoryFactory(school=school), subject=SubjectFactory(school=other)
        )


# =============================================================================
# Classes
# =============================================================================


def test_class_name_unique_per_school_and_year(school):
    year = AcademicYearFactory(school=school)
    level = LevelFactory(school=school)
    SchoolClassFactory(school=school, name="3e A", academic_year=year, level=level)
    SchoolClassFactory(school=school, name="3e A", level=level)  # another year: fine
    with db_rejects(), transaction.atomic():
        SchoolClassFactory(school=school, name="3e A", academic_year=year, level=level)


def test_class_with_level_of_another_school_is_refused_by_postgresql(school):
    with db_rejects(), transaction.atomic():
        SchoolClass.objects.create(
            school=school,
            name="X",
            level=LevelFactory(school=SchoolFactory()),
            academic_year=AcademicYearFactory(school=school),
        )
