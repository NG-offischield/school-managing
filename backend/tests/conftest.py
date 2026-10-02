import pytest
from django.db import connections
from rest_framework.test import APIClient

from common.db_routers import SECURITY_LOG_ALIAS

from .factories import DEFAULT_PASSWORD, MembershipFactory, SchoolFactory, UserFactory

# Every DB test may touch the security log, which goes through its own
# connection (ADR 0005). Modules use: `pytestmark = DB`.
DB = pytest.mark.django_db(databases=["default", SECURITY_LOG_ALIAS])

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


def _purge_security_log():
    with connections[SECURITY_LOG_ALIAS].cursor() as cursor:
        cursor.execute("DELETE FROM accounts_securityevent")


@pytest.fixture(autouse=True)
def _isolate_security_log(request, django_db_blocker):
    """The security_log connection is a test *mirror*: Django does not wrap it
    in the per-test rollback, so its rows are really committed (that is the
    very property under test). Purge them around each DB test so tests stay
    independent."""
    marker = request.node.get_closest_marker("django_db")
    if marker is None:
        yield
        return
    with django_db_blocker.unblock():
        _purge_security_log()
    yield
    with django_db_blocker.unblock():
        _purge_security_log()


@pytest.fixture
def committed(django_capture_on_commit_callbacks):
    """Run on_commit callbacks (success security events) at the end of the
    block, as a real commit would. Tests run inside a transaction that is
    never committed, so they would otherwise never fire."""
    return lambda: django_capture_on_commit_callbacks(execute=True)


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
