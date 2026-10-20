"""Public demonstration safeguards (config/settings/demo.py, ADR 0033): the
shared demonstration accounts are read-only, the administrator never shares
their password, and the demo settings keep the production hardening."""

import importlib

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import SchoolMembership
from apps.accounts.services import ClientContext, login
from apps.website.isbree_seed import seed

from .conftest import DB, DEVICE
from .factories import DEFAULT_PASSWORD, member_with_role

pytestmark = DB
DEMO = "parent.demo@isbree.test"
WITH_MIDDLEWARE = [*settings.MIDDLEWARE, "common.demo.DemoReadOnlyMiddleware"]


def bearer(member):
    issued = login(member.user.username, DEFAULT_PASSWORD, DEVICE, ClientContext())
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {issued.access_token}")
    return api


@override_settings(MIDDLEWARE=WITH_MIDDLEWARE, DEMO_READ_ONLY_ACCOUNTS=[DEMO])
def test_demo_accounts_read_but_never_write(school):
    demo = member_with_role(school, "PARENT")
    demo.user.email = DEMO
    demo.user.save(update_fields=["email"])
    api = bearer(demo)
    assert api.get("/api/v1/auth/me/").status_code == 200  # reading is unchanged
    for path, body in (
        ("/api/v1/auth/password/change/", {"current_password": DEFAULT_PASSWORD, "new_password": "Autre-Secret-2026"}),
        ("/api/v1/auth/sessions/revoke-all/", {}),
        ("/api/v1/parents/link-requests/", {}),
    ):
        response = api.post(path, body, format="json")
        assert response.status_code == 403 and response.json()["error"]["code"] == "DEMO_READ_ONLY", path
    demo.user.refresh_from_db()
    assert demo.user.check_password(DEFAULT_PASSWORD)  # the shared password did not change
    assert api.post("/api/v1/auth/logout/").status_code == 200  # signing out stays possible


@override_settings(MIDDLEWARE=WITH_MIDDLEWARE, DEMO_READ_ONLY_ACCOUNTS=[DEMO])
def test_other_accounts_are_not_affected(school):
    other = member_with_role(school, "PARENT")
    response = bearer(other).post("/api/v1/auth/sessions/revoke-all/")
    assert response.status_code == 200
    # Without a valid token, the usual 401 (the middleware never authenticates anyone).
    assert APIClient().post("/api/v1/auth/sessions/revoke-all/").status_code == 401


@override_settings(ISBREE_PUBLIC_DEMO=True)
def test_public_demo_requires_a_distinct_administrator_password():
    shared = "Demo-Partage-2026-Solide"
    with pytest.raises(ImproperlyConfigured):
        seed(password=shared)
    with pytest.raises(ImproperlyConfigured):
        seed(password=shared, admin_password=shared)
    result = seed(password=shared, admin_password="Admin-Prive-2026-Solide")
    admin = result.admin.user
    assert admin.check_password("Admin-Prive-2026-Solide") and not admin.check_password(shared)


DEMO_LOGINS = [
    "parent.demo@isbree.test",
    "enseignant.demo@isbree.test",
    "personnel.demo@isbree.test",
    "gardien.demo@isbree.test",
]


def test_the_published_password_opens_the_demo_accounts_even_after_it_changed():
    """The portal publishes ISBREE_DEMO_PASSWORD. Accounts created with an
    earlier value used to keep it (every published login refused with 401):
    in the public demo, the seed aligns them; the administrator is never touched."""
    first, new, admin_password = "Demo-Ancien-2026-Solide", "Demo-Nouveau-2026-Solide", "Admin-Prive-2026-Solide"
    with override_settings(ISBREE_PUBLIC_DEMO=True):
        seed(password=first, admin_password=admin_password, demo=True)
        result = seed(password=new, admin_password=admin_password, demo=True)
    for email in DEMO_LOGINS:
        issued = login(email, new, DEVICE, ClientContext())  # the real login service
        assert issued.access_token, email
    assert result.admin.user.check_password(admin_password)
    assert sum("mot de passe partagé aligné" in line for line in result.created) == 4

    # Outside the public demo, an existing password is never changed by the seed.
    seed(password="Demo-Autre-2026-Solide", demo=True)
    assert all(SchoolMembership.objects.get(user__email=email).user.check_password(new) for email in DEMO_LOGINS)


def test_demo_settings_keep_the_production_hardening():
    demo = importlib.import_module("config.settings.demo")
    assert demo.DEBUG is False and demo.SESSION_COOKIE_SECURE and demo.SECURE_SSL_REDIRECT
    assert demo.ISBREE_PUBLIC_DEMO is True
    assert demo.MIDDLEWARE[-1] == "common.demo.DemoReadOnlyMiddleware"
    assert "parent.demo@isbree.test" in demo.DEMO_READ_ONLY_ACCOUNTS
    assert settings.DEMO_READ_ONLY_ACCOUNTS == [] and settings.ISBREE_PUBLIC_DEMO is False  # off elsewhere
