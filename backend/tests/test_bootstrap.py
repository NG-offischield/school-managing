"""`bootstrap_school` management command (spec §9: no public admin signup)."""

import io

import pytest
from django.core.management import CommandError, call_command
from django.urls import get_resolver

from apps.accounts.models import (
    MembershipStatus,
    RoleCode,
    SchoolMembership,
    SecurityEvent,
    SecurityEventType,
    User,
)
from apps.core.models import School, SchoolBranding, SchoolConfiguration

from .conftest import DB
from .factories import UserFactory

pytestmark = DB

PASSWORD = "Bootstrap-Passw0rd-2026"
ARGS = [
    "--code=LYC-DLA",
    "--name=Lycée de Douala",
    "--city=Douala",
    "--address=Akwa",
    "--admin-username=admin",
    "--admin-email=Admin@Example.cm",
    "--admin-first-name=Jean",
    "--admin-last-name=Dupont",
]


@pytest.fixture
def env_password(monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", PASSWORD)


def run(*extra):
    out, err = io.StringIO(), io.StringIO()
    call_command("bootstrap_school", *ARGS, *extra, stdout=out, stderr=err)
    return out.getvalue() + err.getvalue()


def counts():
    return (School.objects.count(), User.objects.count(), SchoolMembership.objects.count())


def test_bootstrap_creates_school_configuration_and_super_admin(env_password, committed):
    with committed():
        output = run()

    school = School.objects.get(code="LYC-DLA")
    assert SchoolConfiguration.objects.filter(school=school).exists()
    assert SchoolBranding.objects.filter(school=school).exists()

    admin = User.objects.get(username="admin")
    assert admin.email == "admin@example.cm"
    assert admin.password.startswith("argon2") and admin.check_password(PASSWORD)

    membership = SchoolMembership.objects.get(user=admin, school=school)
    assert membership.status == MembershipStatus.ACTIVE and membership.is_primary_school
    assert membership.role_codes() == {RoleCode.SUPER_ADMIN}

    event = SecurityEvent.objects.get(event_type=SecurityEventType.BOOTSTRAP_COMPLETED)
    assert (event.user_id, event.school_id) == (admin.id, school.id)
    # The password appears nowhere: not in the output, not in the log.
    assert PASSWORD not in output
    assert PASSWORD not in str(event.metadata)


def test_second_run_is_refused_changes_nothing_and_is_logged(env_password):
    run()
    before = counts()

    with pytest.raises(CommandError, match="already has a school"):
        call_command("bootstrap_school", *[a.replace("LYC-DLA", "OTHER") for a in ARGS], stdout=io.StringIO())

    assert counts() == before
    rejected = SecurityEvent.objects.get(event_type=SecurityEventType.BOOTSTRAP_REJECTED)
    assert rejected.metadata == {"reason": "ALREADY_BOOTSTRAPPED", "requested_code": "OTHER"}


def test_existing_admin_username_or_email_is_refused(env_password):
    UserFactory(email="admin@example.cm")
    with pytest.raises(CommandError, match="already exists"):
        run()
    assert School.objects.count() == 0
    assert SecurityEvent.objects.get().metadata["reason"] == "ADMIN_ALREADY_EXISTS"


def test_weak_password_is_refused_and_nothing_is_created(monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "123")
    with pytest.raises(CommandError) as exc:
        run()
    assert "123" not in str(exc.value)
    assert counts() == (0, 0, 0)


def test_without_terminal_and_without_env_password_it_fails_instead_of_hanging(monkeypatch):
    monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)
    monkeypatch.setattr("sys.stdin", io.StringIO())  # not a TTY
    with pytest.raises(CommandError, match="No terminal"):
        run()
    assert counts() == (0, 0, 0)


def test_interactive_passwords_must_match(monkeypatch):
    monkeypatch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)

    class FakeTerminal(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr("sys.stdin", FakeTerminal())
    answers = iter([PASSWORD, PASSWORD + "x"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    with pytest.raises(CommandError, match="do not match"):
        run()
    assert counts() == (0, 0, 0)


def test_no_http_route_can_bootstrap_or_sign_up(api):
    """The only way to create the first admin is the command: no URL exists."""

    def walk(patterns, prefix=""):
        for p in patterns:
            if hasattr(p, "url_patterns"):
                yield from walk(p.url_patterns, prefix + str(p.pattern))
            else:
                yield prefix + str(p.pattern)

    api_routes = [r for r in walk(get_resolver().url_patterns) if r.startswith("api/")]
    assert not [r for r in api_routes if any(w in r for w in ("bootstrap", "signup", "register", "install"))]
    for path in ("/api/v1/bootstrap/", "/api/v1/auth/register/", "/api/v1/admin/signup/"):
        assert api.post(path, {}, format="json").status_code == 404
