"""Parents, children and the declared / verified link."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

from apps.people import services
from apps.people.models import ParentProfile, ParentStudent, RelationshipType, VerificationMethod

from .conftest import DB
from .factories import ParentFactory, SchoolFactory, StudentFactory, admin_of, member_with_role

pytestmark = DB


def test_parent_profile_requires_parent_role(school):
    with pytest.raises(ValidationError) as exc:
        services.create_parent_profile(member_with_role(school, "TEACHER"))
    assert exc.value.code == "role_missing"
    profile = services.create_parent_profile(member_with_role(school, "PARENT"), occupation="Infirmière")
    assert profile.school == school and profile.preferred_language == "fr"


def test_profile_school_must_match_its_membership_postgresql(school):
    """Composite FK (membership, school)."""
    foreign_membership = member_with_role(SchoolFactory(), "PARENT")
    with pytest.raises(IntegrityError), transaction.atomic():
        ParentProfile.objects.create(school=school, membership=foreign_membership)


def test_many_to_many_parents_and_children(school):
    mother, father = ParentFactory(school=school), ParentFactory(school=school)
    child1, child2 = StudentFactory(school=school), StudentFactory(school=school)
    for parent, rel in ((mother, RelationshipType.MOTHER), (father, RelationshipType.FATHER)):
        for child in (child1, child2):
            services.link_parent(parent, child, relationship_type=rel)
    assert mother.children_links.count() == 2
    assert child1.parent_links.count() == 2


def test_one_link_per_parent_and_child(school):
    parent, child = ParentFactory(school=school), StudentFactory(school=school)
    services.link_parent(parent, child, relationship_type=RelationshipType.MOTHER)
    with pytest.raises(IntegrityError), transaction.atomic():
        services.link_parent(parent, child, relationship_type=RelationshipType.TUTOR)


def test_new_link_is_declared_not_verified(school):
    link = services.link_parent(ParentFactory(school=school), StudentFactory(school=school), relationship_type="MOTHER")
    assert (link.identity_verified, link.verified_at, link.verification_method) == (False, None, None)


def test_financial_rights_require_verification_postgresql(school):
    parent, child = ParentFactory(school=school), StudentFactory(school=school)
    for right in ("can_pay", "can_view_financial_data"):
        with pytest.raises(IntegrityError), transaction.atomic():
            services.link_parent(parent, child, relationship_type="FATHER", **{right: True})


def test_verification_by_admin_unlocks_financial_rights(school):
    link = services.link_parent(ParentFactory(school=school), StudentFactory(school=school), relationship_type="MOTHER")
    services.verify_parent_link(
        link, actor=admin_of(school), method=VerificationMethod.ADMIN_IN_PERSON, reference="DOSSIER-2026-014"
    )
    link.can_pay = link.can_view_financial_data = True
    link.save()
    link.refresh_from_db()
    assert link.identity_verified and link.verified_at and link.verified_by is not None


def test_only_an_admin_of_this_school_verifies(school):
    link = services.link_parent(ParentFactory(school=school), StudentFactory(school=school), relationship_type="MOTHER")
    for actor in (member_with_role(school, "PARENT"), admin_of(SchoolFactory())):
        with pytest.raises(PermissionDenied):
            services.verify_parent_link(link, actor=actor, method=VerificationMethod.ID_DOCUMENT)


def test_half_verified_link_is_impossible_postgresql(school):
    link = services.link_parent(ParentFactory(school=school), StudentFactory(school=school), relationship_type="MOTHER")
    with pytest.raises(IntegrityError), transaction.atomic():
        ParentStudent.objects.filter(pk=link.pk).update(identity_verified=True)  # no method/date


def test_one_active_primary_contact_per_student(school):
    child = StudentFactory(school=school)
    services.link_parent(ParentFactory(school=school), child, relationship_type="MOTHER", is_primary_contact=True)
    with pytest.raises(IntegrityError), transaction.atomic():
        services.link_parent(ParentFactory(school=school), child, relationship_type="FATHER", is_primary_contact=True)
    # An inactive former primary contact does not block a new one.
    ParentStudent.objects.filter(student=child).update(active=False)
    services.link_parent(ParentFactory(school=school), child, relationship_type="TUTOR", is_primary_contact=True)


def test_link_across_schools_is_refused_by_postgresql(school):
    with pytest.raises(IntegrityError), transaction.atomic():
        ParentStudent.objects.create(
            school=school,
            parent=ParentFactory(school=school),
            student=StudentFactory(school=SchoolFactory()),
            relationship_type="MOTHER",
        )
