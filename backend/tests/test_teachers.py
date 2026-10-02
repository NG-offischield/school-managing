"""Teachers, qualifications, compatibility evaluation and audited overrides."""

from datetime import timedelta

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.academics.models import SubjectCompatibilityRule
from apps.people import services
from apps.people.compatibility import evaluate
from apps.people.models import (
    CompatibilityOverride,
    CompatibilityResult,
    EmployeeType,
    QualificationSource,
    QualificationStatus,
    TeacherProfile,
    TeacherSubjectQualification,
)

from .conftest import DB
from .factories import (
    CategoryFactory,
    EmployeeFactory,
    LevelFactory,
    SchoolFactory,
    SubjectFactory,
    admin_of,
    make_teacher,
    member_with_role,
)

pytestmark = DB


@pytest.fixture
def setup(school):
    """A scientific maths teacher, a literary subject and two levels."""
    sci, lit = CategoryFactory(school=school, code="SCIENTIFIC"), CategoryFactory(school=school, code="LITERARY")
    maths = SubjectFactory(school=school, code="MATH", category=sci)
    physics = SubjectFactory(school=school, code="PHYS", category=sci)
    french = SubjectFactory(school=school, code="FR", category=lit)
    teacher = make_teacher(school, category=sci, primary_subject=maths)
    return {
        "school": school,
        "teacher": teacher,
        "sci": sci,
        "maths": maths,
        "physics": physics,
        "french": french,
        "l6": LevelFactory(school=school, code="6E"),
        "tle": LevelFactory(school=school, code="TLE"),
        "admin": admin_of(school),
    }


def rule(s, subject, *, level=None, compatible=True, review=False, priority=0):
    return SubjectCompatibilityRule.objects.create(
        school=s["school"],
        pedagogical_category=s["sci"],
        subject=subject,
        level=level,
        compatible=compatible,
        requires_admin_review=review,
        priority=priority,
    )


# --- Teacher profile -------------------------------------------------------------


def test_teacher_number_is_the_unique_employee_number(school):
    teacher = make_teacher(school, number="ENS-001")
    assert teacher.teacher_number == "ENS-001"
    with pytest.raises(IntegrityError), transaction.atomic():
        EmployeeFactory(school=school, employee_number="ENS-001")
    make_teacher(SchoolFactory(), number="ENS-001")  # other school: fine


def test_teacher_requires_teacher_employee_and_role(school):
    staff_employee = EmployeeFactory(school=school, employee_type=EmployeeType.STAFF)
    with pytest.raises(ValidationError) as exc:
        services.create_teacher(
            staff_employee,
            pedagogical_category=CategoryFactory(school=school),
            primary_subject=SubjectFactory(school=school),
        )
    assert exc.value.code == "not_teacher_employee"


def test_primary_subject_is_recorded_as_a_qualification(setup):
    q = TeacherSubjectQualification.objects.get(teacher=setup["teacher"])
    assert (q.subject, q.status, q.computed_compatibility) == (
        setup["maths"],
        QualificationStatus.DECLARED,
        CompatibilityResult.COMPATIBLE,
    )


def test_teacher_with_category_of_another_school_is_refused_by_postgresql(school):
    employee = EmployeeFactory(school=school, employee_type=EmployeeType.TEACHER)
    other = SchoolFactory()
    with pytest.raises(IntegrityError), transaction.atomic():
        TeacherProfile.objects.create(
            school=school,
            employee=employee,
            pedagogical_category=CategoryFactory(school=other),
            primary_subject=SubjectFactory(school=school),
        )


# --- Compatibility evaluation ----------------------------------------------------


def test_no_rule_same_category_is_compatible(setup):
    assert evaluate(setup["teacher"], setup["physics"]).result == CompatibilityResult.COMPATIBLE


def test_no_rule_other_category_needs_review_never_silent(setup):
    assert evaluate(setup["teacher"], setup["french"]).result == CompatibilityResult.REQUIRES_REVIEW


@pytest.mark.parametrize(
    "compatible,review,expected",
    [
        (True, False, CompatibilityResult.COMPATIBLE),
        (True, True, CompatibilityResult.REQUIRES_REVIEW),
        (False, True, CompatibilityResult.REQUIRES_REVIEW),
        (False, False, CompatibilityResult.INCOMPATIBLE),
    ],
)
def test_rule_matrix(setup, compatible, review, expected):
    rule(setup, setup["french"], compatible=compatible, review=review)
    assert evaluate(setup["teacher"], setup["french"]).result == expected


def test_level_specific_rule_beats_general_rule(setup):
    rule(setup, setup["french"], compatible=True)  # all levels
    rule(setup, setup["french"], level=setup["tle"], compatible=False)  # not in Terminale
    t = setup["teacher"]
    assert evaluate(t, setup["french"], level=setup["l6"]).result == CompatibilityResult.COMPATIBLE
    assert evaluate(t, setup["french"], level=setup["tle"]).result == CompatibilityResult.INCOMPATIBLE


# --- Declaring and reviewing qualifications ---------------------------------------


def test_declare_compatible_subject_is_declared_pending_admin(setup):
    q = services.declare_qualification(setup["teacher"], setup["physics"])
    assert (q.status, q.verified) == (QualificationStatus.DECLARED, False)


def test_declare_subject_needing_review_is_pending(setup):
    q = services.declare_qualification(setup["teacher"], setup["french"])
    assert q.status == QualificationStatus.PENDING


def test_incompatible_subject_is_refused_and_nothing_stored(setup):
    rule(setup, setup["french"], compatible=False)
    with pytest.raises(services.IncompatibleSubject):
        services.declare_qualification(setup["teacher"], setup["french"])
    assert not TeacherSubjectQualification.objects.filter(subject=setup["french"]).exists()


def test_admin_verifies_or_rejects(setup):
    q = services.declare_qualification(setup["teacher"], setup["french"])
    with pytest.raises(PermissionDenied):
        services.verify_qualification(q, actor=member_with_role(setup["school"], "TEACHER"))
    services.verify_qualification(q, actor=setup["admin"])
    q.refresh_from_db()
    assert (q.status, q.verified, q.verified_by) == (QualificationStatus.VERIFIED, True, setup["admin"])

    other = services.declare_qualification(setup["teacher"], setup["physics"])
    with pytest.raises(ValidationError):
        services.reject_qualification(other, actor=setup["admin"], reason="")
    services.reject_qualification(other, actor=setup["admin"], reason="Diplôme non fourni")
    assert other.status == QualificationStatus.REJECTED


def test_verified_flag_and_status_cannot_disagree_postgresql(setup):
    q = TeacherSubjectQualification.objects.get(teacher=setup["teacher"])
    with pytest.raises(IntegrityError), transaction.atomic():
        TeacherSubjectQualification.objects.filter(pk=q.pk).update(verified=True)
    with pytest.raises(IntegrityError), transaction.atomic():
        TeacherSubjectQualification.objects.filter(pk=q.pk).update(status=QualificationStatus.VERIFIED)


def test_one_qualification_per_teacher_and_subject(setup):
    with pytest.raises(IntegrityError), transaction.atomic():
        services.declare_qualification(setup["teacher"], setup["maths"])  # already the primary subject


# --- Overrides ----------------------------------------------------------------------


def test_override_allows_an_incompatible_subject_with_full_audit(setup):
    rule(setup, setup["french"], compatible=False)
    override = services.grant_compatibility_override(
        setup["teacher"],
        setup["french"],
        actor=setup["admin"],
        reason="Pénurie d'enseignants de français",
        expires_at=timezone.now() + timedelta(days=180),
    )
    # actor + reason + timestamp + scope (spec §9)
    assert (override.approved_by, override.level) == (setup["admin"], None)
    assert override.reason and override.created_at

    q = services.declare_qualification(setup["teacher"], setup["french"])
    assert (q.computed_compatibility, q.source, q.status) == (
        CompatibilityResult.OVERRIDDEN,
        QualificationSource.OVERRIDE,
        QualificationStatus.DECLARED,
    )


def test_override_scope_limited_to_its_level(setup):
    rule(setup, setup["french"], compatible=False)
    services.grant_compatibility_override(
        setup["teacher"], setup["french"], actor=setup["admin"], reason="6e uniquement", level=setup["l6"]
    )
    t = setup["teacher"]
    assert evaluate(t, setup["french"], level=setup["l6"]).result == CompatibilityResult.OVERRIDDEN
    assert evaluate(t, setup["french"], level=setup["tle"]).result == CompatibilityResult.INCOMPATIBLE


def test_expired_override_no_longer_applies(setup):
    rule(setup, setup["french"], compatible=False)
    override = services.grant_compatibility_override(
        setup["teacher"],
        setup["french"],
        actor=setup["admin"],
        reason="Temporaire",
        expires_at=timezone.now() + timedelta(days=1),
    )
    later = override.expires_at + timedelta(seconds=1)
    assert evaluate(setup["teacher"], setup["french"], now=later).result == CompatibilityResult.INCOMPATIBLE


def test_override_requires_admin_and_reason(setup):
    with pytest.raises(PermissionDenied):
        services.grant_compatibility_override(
            setup["teacher"], setup["french"], actor=member_with_role(setup["school"], "TEACHER"), reason="x"
        )
    with pytest.raises(ValidationError):
        services.grant_compatibility_override(setup["teacher"], setup["french"], actor=setup["admin"], reason="  ")


@pytest.mark.parametrize("bad", [{"reason": ""}, {"expires_at_offset": -1}])
def test_override_constraints_postgresql(setup, bad):
    fields = dict(
        school=setup["school"],
        teacher=setup["teacher"],
        subject=setup["french"],
        approved_by=setup["admin"],
        reason=bad.get("reason", "ok"),
    )
    if "expires_at_offset" in bad:
        fields["expires_at"] = timezone.now() - timedelta(days=1)
    with pytest.raises(IntegrityError), transaction.atomic():
        CompatibilityOverride.objects.create(**fields)


def test_override_approved_by_admin_of_other_school_refused_postgresql(setup):
    with pytest.raises(IntegrityError), transaction.atomic():
        CompatibilityOverride.objects.create(
            school=setup["school"],
            teacher=setup["teacher"],
            subject=setup["french"],
            approved_by=admin_of(SchoolFactory()),
            reason="x",
        )
