"""Tenant resolution & role permissions (spec §8)."""

import uuid

import pytest
from django.urls import path
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.test import APIClient
from rest_framework.views import APIView

from apps.accounts.models import MembershipStatus, RoleCode, SchoolMembership
from apps.core.models import SchoolConfiguration
from common.permissions import HasSchoolRole, IsSchoolMember
from common.tenancy import get_active_membership, scope_to_current_school

from .conftest import DB
from .factories import MembershipFactory, SchoolFactory, UserFactory, grant_role

pytestmark = [DB, pytest.mark.urls("tests.test_tenancy_permissions")]


# Throw-away views mounted only for these tests.
class WhereAmI(APIView):
    permission_classes = [IsSchoolMember]

    def get(self, request):
        return Response({"school": get_active_membership(request).school.code})


class AdminOnly(APIView):
    permission_classes = [HasSchoolRole]
    required_roles = {RoleCode.ADMIN, RoleCode.SUPER_ADMIN}

    def get(self, request):
        return Response({"ok": True})


class ForgotToDeclareRoles(APIView):
    permission_classes = [HasSchoolRole]

    def get(self, request):
        return Response({"ok": True})


class MemberList(APIView):
    """Stand-in for any future tenant-owned resource (students, invoices...),
    following the mandatory pattern: every query goes through
    scope_to_current_school()."""

    permission_classes = [IsSchoolMember]

    def get(self, request):
        members = scope_to_current_school(SchoolMembership.objects.all(), request)
        return Response(sorted(str(m.id) for m in members))


class MemberDetail(APIView):
    permission_classes = [IsSchoolMember]

    def get(self, request, pk):
        member = get_object_or_404(scope_to_current_school(SchoolMembership.objects.all(), request), pk=pk)
        return Response({"id": str(member.id), "school": member.school.code})


urlpatterns = [
    path("where/", WhereAmI.as_view()),
    path("admin-only/", AdminOnly.as_view()),
    path("misconfigured/", ForgotToDeclareRoles.as_view()),
    path("members/", MemberList.as_view()),
    path("members/<uuid:pk>/", MemberDetail.as_view()),
]


@pytest.fixture
def client_for():
    def _client(user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    return _client


def test_single_membership_is_resolved_automatically(client_for):
    membership = MembershipFactory()
    response = client_for(membership.user).get("/where/")
    assert response.json()["data"] == {"school": membership.school.code}


def test_user_without_membership_is_refused(client_for):
    assert client_for(UserFactory()).get("/where/").status_code == 403


@pytest.mark.parametrize("status", [MembershipStatus.PENDING, MembershipStatus.SUSPENDED, MembershipStatus.LEFT])
def test_non_active_membership_is_refused(client_for, status):
    membership = MembershipFactory(status=status)
    assert client_for(membership.user).get("/where/").status_code == 403


def test_suspended_school_is_refused(client_for):
    membership = MembershipFactory()
    membership.school.status = "SUSPENDED"
    membership.school.save()
    assert client_for(membership.user).get("/where/").status_code == 403


def test_header_cannot_select_a_school_the_user_does_not_belong_to(client_for):
    """Tenant isolation: knowing another school's code grants nothing."""
    membership = MembershipFactory()
    other_school = SchoolFactory()
    response = client_for(membership.user).get("/where/", HTTP_X_SCHOOL_CODE=other_school.code)
    assert response.status_code == 403


def test_multi_school_user_picks_school_with_header(client_for):
    user = UserFactory()
    MembershipFactory(user=user, is_primary_school=True)
    second = MembershipFactory(user=user)
    response = client_for(user).get("/where/", HTTP_X_SCHOOL_CODE=second.school.code)
    assert response.json()["data"] == {"school": second.school.code}


def test_role_is_required(client_for):
    membership = MembershipFactory()
    grant_role(membership, RoleCode.TEACHER)
    assert client_for(membership.user).get("/admin-only/").status_code == 403

    grant_role(membership, RoleCode.ADMIN)
    assert client_for(membership.user).get("/admin-only/").status_code == 200


def test_role_in_another_school_grants_nothing(client_for):
    """ADMIN in school A must not be ADMIN in school B."""
    user = UserFactory()
    admin_elsewhere = MembershipFactory(user=user)
    grant_role(admin_elsewhere, RoleCode.ADMIN)
    teacher_here = MembershipFactory(user=user, is_primary_school=True)
    grant_role(teacher_here, RoleCode.TEACHER)

    response = client_for(user).get("/admin-only/", HTTP_X_SCHOOL_CODE=teacher_here.school.code)
    assert response.status_code == 403


def test_view_without_declared_roles_fails_closed(client_for):
    membership = MembershipFactory()
    grant_role(membership, RoleCode.SUPER_ADMIN)
    assert client_for(membership.user).get("/misconfigured/").status_code == 403


# --- School A ≠ School B ----------------------------------------------------------


@pytest.fixture
def two_schools():
    """Two tenants, each with an ADMIN and one other member."""
    a_admin, b_admin = MembershipFactory(), MembershipFactory()
    grant_role(a_admin, RoleCode.ADMIN)
    grant_role(b_admin, RoleCode.ADMIN)
    a_other = MembershipFactory(school=a_admin.school)
    b_other = MembershipFactory(school=b_admin.school)
    return a_admin, a_other, b_admin, b_other


def test_schools_are_distinct_tenants(two_schools):
    a_admin, _, b_admin, _ = two_schools
    assert a_admin.school != b_admin.school
    # Each school owns its own configuration: changing A never affects B.
    SchoolConfiguration.objects.filter(school=a_admin.school).update(default_late_threshold_minutes=5)
    assert SchoolConfiguration.objects.get(school=b_admin.school).default_late_threshold_minutes == 15


def test_list_only_returns_current_school_rows(client_for, two_schools):
    a_admin, a_other, _, _ = two_schools
    response = client_for(a_admin.user).get("/members/")
    assert response.json()["data"] == sorted([str(a_admin.id), str(a_other.id)])


def test_changing_the_id_in_the_url_gives_no_access_to_school_b(client_for, two_schools):
    """Even an ADMIN of A gets 404 for B's object — the same answer as for an
    id that does not exist at all, so B's ids cannot even be confirmed."""
    a_admin, a_other, _, b_other = two_schools
    client = client_for(a_admin.user)

    assert client.get(f"/members/{a_other.id}/").status_code == 200
    foreign = client.get(f"/members/{b_other.id}/")
    unknown = client.get(f"/members/{uuid.uuid4()}/")
    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json() == unknown.json()


def test_school_header_cannot_switch_to_school_b(client_for, two_schools):
    a_admin, _, b_admin, b_other = two_schools
    response = client_for(a_admin.user).get(f"/members/{b_other.id}/", HTTP_X_SCHOOL_CODE=b_admin.school.code)
    assert response.status_code == 403


def test_second_school_needs_no_model_change(client_for):
    """Multi-tenant readiness: a second school is plain data. The same person
    can belong to both and sees each school's data only in that school."""
    user = UserFactory()
    in_a = MembershipFactory(user=user, is_primary_school=True)
    in_b = MembershipFactory(user=user)
    peer_b = MembershipFactory(school=in_b.school)
    client = client_for(user)

    assert client.get(f"/members/{peer_b.id}/").status_code == 404  # acting in A (primary)
    response = client.get(f"/members/{peer_b.id}/", HTTP_X_SCHOOL_CODE=in_b.school.code)
    assert response.json()["data"] == {"id": str(peer_b.id), "school": in_b.school.code}
    assert in_a.school != in_b.school
