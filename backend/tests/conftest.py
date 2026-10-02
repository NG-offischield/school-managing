import pytest
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.accounts.system_roles import sync_system_roles
from common.db_routers import SECURITY_LOG_ALIAS

from .factories import DEFAULT_PASSWORD, MembershipFactory, SchoolFactory, UserFactory

# Every DB test is TRANSACTIONAL (ADR 0005): business data is really
# committed, exactly as in production, so the security_log connection can see
# it and its foreign keys are checked for real. A rollback-only test would hide
# precisely the cross-connection behaviour we need to verify. The database is
# flushed (TRUNCATE) after each test. Modules use: `pytestmark = DB`.
DB = pytest.mark.django_db(transaction=True, databases=["default", SECURITY_LOG_ALIAS])

DEVICE = {
    "identifier": "install-0001",
    "device_name": "Pixel de test",
    "device_type": "PHONE",
    "platform": "ANDROID",
    "android_sdk": 34,
    "app_version": "0.1.0",
}


@pytest.fixture(autouse=True)
def _clear_cache():
    # Throttle counters live in the cache: reset them so tests do not
    # rate-limit each other.
    from django.core.cache import cache

    cache.clear()


@pytest.fixture(autouse=True)
def _system_roles(request):
    """The flush after each transactional test also empties the roles seeded
    by migration 0002: put them back before each DB test, with the very
    function the migration uses."""
    if request.node.get_closest_marker("django_db") is not None:
        request.getfixturevalue("transactional_db")
        sync_system_roles(Role)


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def school(db):
    return SchoolFactory()


@pytest.fixture
def user(db):
    return UserFactory()


@pytest.fixture
def membership(school, user):
    return MembershipFactory(school=school, user=user, is_primary_school=True)


@pytest.fixture
def login(api):
    """Log `user` in through the real endpoint; returns the token payload."""

    def _login(user, password=DEFAULT_PASSWORD, device=None):
        response = api.post(
            "/api/v1/auth/login/",
            {"identifier": user.username, "password": password, "device": device or DEVICE},
            format="json",
        )
        assert response.status_code == 200, response.json()
        return response.json()["data"]

    return _login


@pytest.fixture
def auth_api(api, login):
    """APIClient already authenticated as the given user."""

    def _auth(user):
        tokens = login(user)
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access_token']}")
        return api, tokens

    return _auth
