"""Identity, roles and memberships (spec §4.2)."""

from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.utils import timezone

from apps.accounts.models import MembershipRole, Role, RoleCode, SchoolMembership, User, UserDevice, UserSession

from .conftest import DB
from .factories import MembershipFactory, SchoolFactory, UserFactory, grant_role

pytestmark = DB


def test_system_roles_are_seeded_by_migration():
    codes = set(Role.objects.filter(system_role=True).values_list("code", flat=True))
    assert codes == set(RoleCode.values)


def test_password_is_hashed_with_argon2_never_plaintext():
    user = UserFactory(password="Une-Phrase-Secrete-42")
    assert user.password.startswith("argon2")
    assert "Une-Phrase-Secrete-42" not in user.password
    assert user.check_password("Une-Phrase-Secrete-42")


def test_email_is_normalised_and_unique_case_insensitively():
    user = UserFactory(email="Jean.Dupont@Example.CM")
    assert user.email == "jean.dupont@example.cm"
    with pytest.raises(IntegrityError), transaction.atomic():
        UserFactory(email="JEAN.DUPONT@example.cm")


def test_username_is_unique_case_insensitively():
    UserFactory(username="Admin")
    with pytest.raises(IntegrityError), transaction.atomic():
        UserFactory(username="admin")


def test_one_membership_per_user_and_school():
    membership = MembershipFactory()
    with pytest.raises(IntegrityError), transaction.atomic():
        MembershipFactory(school=membership.school, user=membership.user)


def test_same_user_can_join_several_schools():
    """Multi-tenant readiness: one identity, several memberships."""
    user = UserFactory()
    MembershipFactory(user=user, school=SchoolFactory())
    MembershipFactory(user=user, school=SchoolFactory())
    assert user.memberships.count() == 2


def test_only_one_primary_school_per_user():
    user = UserFactory()
    MembershipFactory(user=user, is_primary_school=True)
    with pytest.raises(IntegrityError), transaction.atomic():
        MembershipFactory(user=user, is_primary_school=True)


def test_membership_cannot_end_before_it_started():
    membership = MembershipFactory()
    with pytest.raises(IntegrityError), transaction.atomic():
        SchoolMembership.objects.filter(pk=membership.pk).update(left_at=membership.joined_at - timedelta(days=1))


def test_role_assigned_once_per_membership():
    membership = MembershipFactory()
    grant_role(membership, RoleCode.TEACHER)
    with pytest.raises(IntegrityError), transaction.atomic():
        grant_role(membership, RoleCode.TEACHER)


def test_role_codes_only_returns_active_roles():
    membership = MembershipFactory()
    grant_role(membership, RoleCode.TEACHER)
    MembershipRole.objects.create(membership=membership, role=Role.objects.get(code=RoleCode.STAFF), active=False)
    assert membership.role_codes() == {RoleCode.TEACHER}


def test_session_must_expire_after_creation():
    user = UserFactory()
    device = UserDevice.objects.create(
        user=user, device_name="d", device_type="PHONE", platform="ANDROID", device_identifier_hash="h"
    )
    now = timezone.now()
    with pytest.raises(IntegrityError), transaction.atomic():
        UserSession.objects.create(
            user=user, device=device, refresh_token_hash="x", created_at=now, expires_at=now - timedelta(seconds=1)
        )


def test_user_with_history_cannot_be_hard_deleted():
    """PROTECT: deleting a user referenced by a membership is refused."""
    membership = MembershipFactory()
    with pytest.raises(ProtectedError), transaction.atomic():
        User.objects.filter(pk=membership.user.pk).delete()
