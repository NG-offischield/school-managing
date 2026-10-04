"""API client and authentication against the fake backend."""

import pytest

from school_admin.api.errors import (
    ApiError,
    Conflict,
    Forbidden,
    NetworkError,
    NotFound,
    Unauthorized,
    ValidationFailed,
)
from school_admin.auth.session import NotAnAdministrator
from school_admin.config import DEFAULT_API_URL, load_config

from .conftest import DEVICE
from .fake_backend import PASSWORD, FakeBackend, fail


def test_login_uses_backend_tokens_and_never_keeps_the_password(auth, api, backend, vault):
    identity = auth.login("admin", PASSWORD)
    assert (identity.username, identity.school_code, identity.is_admin) == ("admin", "TEST01", True)
    assert api.access_token.startswith("acc-")
    assert backend.login_bodies[-1]["device"] == DEVICE
    # Nothing holds the password: not the client, not the stores.
    held = [api.access_token, auth.store.load(), vault.load(), repr(vars(auth)), repr(vars(api))]
    assert not any(PASSWORD in str(value) for value in held)
    assert vault.load() is None  # "rester connecté" not ticked -> nothing persisted


def test_wrong_credentials(auth):
    with pytest.raises(Unauthorized) as exc:
        auth.login("admin", "wrong")
    assert exc.value.message == "Identifiants invalides." and not auth.authenticated
    with pytest.raises(ApiError):
        auth.login("  ", "")


def test_non_admin_accounts_are_refused(api, vault):
    from school_admin.auth.session import AuthService

    teacher_backend = FakeBackend(roles=("TEACHER",))
    import httpx

    from school_admin.api import ApiClient

    client = ApiClient("http://testserver/api/v1/", transport=httpx.MockTransport(teacher_backend))
    with pytest.raises(NotAnAdministrator):
        AuthService(client, DEVICE).login("admin", PASSWORD)
    assert client.access_token is None and teacher_backend.revoked  # session revoked server-side


def test_remembered_session_and_logout(auth, api, backend, vault):
    auth.login("admin", PASSWORD, remember=True)
    remembered = vault.load()
    assert remembered.startswith("ref-")
    api.access_token = None
    restored = auth.restore()  # next launch
    assert restored.username == "admin" and vault.load() != remembered  # rotated
    auth.logout()
    assert api.access_token is None and vault.load() is None
    assert backend.revoked  # the server revoked the session
    assert auth.restore() is None


def test_logout_offline_still_forgets_everything(logged_in, api, backend):
    backend.offline = True
    logged_in.logout()
    assert api.access_token is None and not logged_in.authenticated


def test_expired_access_token_is_refreshed_once(logged_in, api, backend):
    backend.expire_access_tokens()
    assert api.get("school/")["code"] == "TEST01"
    assert backend.calls.count(("POST", "auth/refresh/")) == 1


def test_revoked_session_raises_unauthorized(logged_in, api, backend):
    backend.expire_access_tokens()
    backend.revoked |= backend.refresh_tokens
    with pytest.raises(Unauthorized):
        api.get("school/")
    assert api.access_token is None


@pytest.mark.parametrize(
    ("status", "code", "error"),
    [
        (400, "VALIDATION_ERROR", ValidationFailed),
        (403, "PERMISSION_DENIED", Forbidden),
        (404, "NOT_FOUND", NotFound),
        (409, "CONFLICT", Conflict),
    ],
)
def test_error_mapping(logged_in, api, backend, status, code, error):
    backend.forced[("GET", "school/")] = fail(status, code, "Message serveur", {"rule": "duplicate_code"})
    with pytest.raises(error) as exc:
        api.get("school/")
    assert (exc.value.status, exc.value.code, exc.value.message) == (status, code, "Message serveur")
    assert exc.value.rule == "duplicate_code"


def test_offline_and_timeout(logged_in, api, backend):
    backend.offline = True
    with pytest.raises(NetworkError) as exc:
        api.get("school/")
    assert "injoignable" in exc.value.message


def test_pagination_follows_every_page(logged_in, api, backend):
    for i in range(130):
        backend.add_category(f"C{i:03d}", f"Catégorie {i}")
    assert len(api.list_all("pedagogical-categories/")) == 130
    assert api.count("teachers/") == 9  # meta.count, without downloading the rows
    rows, total = api.page("students/", page=2, page_size=3)  # one server page at a time
    assert (len(rows), total) == (1, 4)


def test_configuration_sources(tmp_path):
    assert load_config(env={}, directory=tmp_path).api_url == DEFAULT_API_URL
    (tmp_path / "desktop.json").write_text('{"api_url": "https://ecole.lan/api/v1"}', encoding="utf-8")
    config = load_config(env={}, directory=tmp_path)
    assert config.api_url == "https://ecole.lan/api/v1/" and not config.insecure_transport
    env_config = load_config(env={"SCHOOL_ADMIN_API_URL": "http://192.168.1.10:8000/api/v1/"}, directory=tmp_path)
    assert env_config.api_url.startswith("http://192.168.1.10") and env_config.insecure_transport
