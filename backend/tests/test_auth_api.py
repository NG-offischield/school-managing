"""Authentication & session API (spec §6.2, §9)."""

import uuid
from datetime import timedelta

import pytest
from django.core import signing
from django.test import override_settings
from django.utils import timezone

from apps.accounts import services
from apps.accounts.models import SecurityEvent, SecurityEventType, User, UserDevice, UserSession
from apps.accounts.tokens import ACCESS_TOKEN_SALT

from .conftest import DB, DEVICE
from .factories import DEFAULT_PASSWORD, UserFactory

pytestmark = DB

LOGIN = "/api/v1/auth/login/"
REFRESH = "/api/v1/auth/refresh/"
ME = "/api/v1/auth/me/"


# --- Login ---------------------------------------------------------------------


def test_login_returns_tokens_in_envelope(api, user):
    response = api.post(
        LOGIN, {"identifier": user.username, "password": DEFAULT_PASSWORD, "device": DEVICE}, format="json"
    )
    body = response.json()
    assert response.status_code == 200
    assert body["success"] is True
    assert set(body["data"]) >= {"access_token", "refresh_token", "session_id", "access_expires_in"}


def test_login_with_email_case_insensitive(api, user):
    response = api.post(
        LOGIN, {"identifier": user.email.upper(), "password": DEFAULT_PASSWORD, "device": DEVICE}, format="json"
    )
    assert response.status_code == 200


def test_refresh_token_is_stored_hashed_only(login, user):
    tokens = login(user)
    session = UserSession.objects.get(pk=tokens["session_id"])
    assert session.refresh_token_hash != tokens["refresh_token"]
    assert len(session.refresh_token_hash) == 64  # sha256 hex


def test_device_identifier_is_not_stored_in_clear(login, user):
    login(user)
    device = UserDevice.objects.get(user=user)
    assert DEVICE["identifier"] not in device.device_identifier_hash


@pytest.mark.parametrize("identifier", ["unknown-user", "user-exists"])
def test_failed_login_is_generic_and_logged(api, user, identifier):
    """Wrong password and unknown account give the SAME answer (no enumeration),
    and both are recorded as security events."""
    ident = user.username if identifier == "user-exists" else identifier
    response = api.post(LOGIN, {"identifier": ident, "password": "wrong-password", "device": DEVICE}, format="json")

    assert response.status_code == 401
    # ADR 0007 format, French by default.
    assert response.json() == {
        "success": False,
        "error": {"code": "INVALID_CREDENTIALS", "message": "Identifiants incorrects."},
    }
    event = SecurityEvent.objects.get(event_type=SecurityEventType.LOGIN_FAILED)
    assert "wrong-password" not in str(event.metadata)  # password never logged


def test_inactive_user_cannot_log_in(api):
    user = UserFactory(is_active=False)
    response = api.post(
        LOGIN, {"identifier": user.username, "password": DEFAULT_PASSWORD, "device": DEVICE}, format="json"
    )
    assert response.status_code == 401


def test_login_validation_errors_are_structured(api):
    response = api.post(LOGIN, {"identifier": "x"}, format="json")
    body = response.json()
    assert response.status_code == 400
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "password" in body["error"]["details"] and "device" in body["error"]["details"]


def test_login_is_rate_limited(api, user):
    payload = {"identifier": user.username, "password": "wrong", "device": DEVICE}
    statuses = [api.post(LOGIN, payload, format="json").status_code for _ in range(11)]
    assert statuses[:10] == [401] * 10
    assert statuses[10] == 429


# --- Access token ------------------------------------------------------------------


def test_me_requires_authentication(api):
    response = api.get(ME)
    assert response.status_code == 401
    assert response.json()["success"] is False


def test_me_returns_identity_and_memberships(auth_api, membership):
    client, _ = auth_api(membership.user)
    data = client.get(ME).json()["data"]
    assert data["username"] == membership.user.username
    assert data["memberships"][0]["school_code"] == membership.school.code


def test_tampered_access_token_is_rejected(api, login, user):
    tokens = login(user)
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access_token']}x")
    assert api.get(ME).status_code == 401


def test_access_token_signed_with_another_salt_is_rejected(api, login, user):
    tokens = login(user)
    forged = signing.dumps({"sid": tokens["session_id"]}, salt=ACCESS_TOKEN_SALT + "-other")
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {forged}")
    assert api.get(ME).status_code == 401


def test_expired_access_token_is_rejected(api, login, user):
    tokens = login(user)
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access_token']}")

    with override_settings(ACCESS_TOKEN_LIFETIME=timedelta(seconds=-1)):
        assert api.get(ME).status_code == 401


# --- Refresh / logout / revocation ---------------------------------------------------


def test_refresh_rotates_the_refresh_token(api, login, user):
    tokens = login(user)
    first = api.post(REFRESH, {"refresh_token": tokens["refresh_token"]}, format="json")
    assert first.status_code == 200
    new_refresh = first.json()["data"]["refresh_token"]
    assert new_refresh != tokens["refresh_token"]
    assert first.json()["data"]["session_id"] == tokens["session_id"]  # same family

    # The new one keeps working while no old token is replayed.
    assert api.post(REFRESH, {"refresh_token": new_refresh}, format="json").status_code == 200


def test_logout_revokes_access_immediately(auth_api, user):
    client, tokens = auth_api(user)
    assert client.post("/api/v1/auth/logout/").status_code == 200
    # Same, still-unexpired access token: refused because the session is revoked.
    assert client.get(ME).status_code == 401
    assert client.post(REFRESH, {"refresh_token": tokens["refresh_token"]}, format="json").status_code == 401


def test_user_can_revoke_another_of_their_sessions(auth_api, login, user):
    other = login(user, device={**DEVICE, "identifier": "install-0002", "device_name": "Tablette"})
    client, _ = auth_api(user)

    sessions = client.get("/api/v1/auth/sessions/").json()["data"]
    assert len(sessions) == 2

    response = client.post(f"/api/v1/auth/sessions/{other['session_id']}/revoke/")
    assert response.status_code == 200
    assert UserSession.objects.get(pk=other["session_id"]).revoked_at is not None


def test_user_cannot_revoke_someone_elses_session(auth_api, login, user):
    victim_tokens = login(UserFactory())
    client, _ = auth_api(user)
    response = client.post(f"/api/v1/auth/sessions/{victim_tokens['session_id']}/revoke/")
    assert response.status_code == 404
    assert UserSession.objects.get(pk=victim_tokens["session_id"]).revoked_at is None


def test_password_change_revokes_other_sessions_only(auth_api, login, user):
    other = login(user, device={**DEVICE, "identifier": "install-0002"})
    client, current = auth_api(user)

    response = client.post(
        "/api/v1/auth/password/change/",
        {"current_password": DEFAULT_PASSWORD, "new_password": "Nouveau-Mot-De-Passe-2026"},
        format="json",
    )
    assert response.status_code == 200
    assert UserSession.objects.get(pk=other["session_id"]).revoked_at is not None
    assert UserSession.objects.get(pk=current["session_id"]).revoked_at is None
    assert client.get(ME).status_code == 200


def test_password_change_enforces_strength(auth_api, user):
    client, _ = auth_api(user)
    response = client.post(
        "/api/v1/auth/password/change/",
        {"current_password": DEFAULT_PASSWORD, "new_password": "123"},
        format="json",
    )
    assert response.status_code == 400
    assert "new_password" in response.json()["error"]["details"]


def test_there_is_no_public_signup_endpoint(api):
    """Spec §9: no public admin signup."""
    assert api.post("/api/v1/auth/register/", {}, format="json").status_code == 404


# --- Expiration, reuse, inactive user ---------------------------------------------


def _rejection_reasons():
    return list(
        SecurityEvent.objects.filter(event_type=SecurityEventType.REFRESH_REJECTED).values_list(
            "metadata__reason", flat=True
        )
    )


def test_reused_refresh_token_compromises_and_revokes_its_family_only(api, login, user):
    """Theft scenario: attacker and victim both hold token T1. One of them
    refreshes first (gets T2); when T1 is replayed, the server knows a copy
    exists: refuse, log CRITICAL, revoke the whole session (T2 dies too).
    The user's other sessions are not affected."""
    stolen = login(user)
    other_device = login(user, device={**DEVICE, "identifier": "install-0002"})
    t2 = api.post(REFRESH, {"refresh_token": stolen["refresh_token"]}, format="json").json()["data"]

    replay = api.post(REFRESH, {"refresh_token": stolen["refresh_token"]}, format="json")
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"  # nothing more revealed

    # 1) the family is revoked: the newest refresh token and the access token are dead
    assert UserSession.objects.get(pk=stolen["session_id"]).revoked_at is not None
    assert api.post(REFRESH, {"refresh_token": t2["refresh_token"]}, format="json").status_code == 401
    assert api.get(ME, HTTP_AUTHORIZATION=f"Bearer {t2['access_token']}").status_code == 401
    # 2) the security event is CRITICAL and names the session
    event = SecurityEvent.objects.get(event_type=SecurityEventType.REFRESH_TOKEN_REUSE_DETECTED)
    assert (event.severity, event.user_id) == ("CRITICAL", user.id)
    assert event.metadata == {"session_id": stolen["session_id"], "session_was_active": True}
    # 3) the other session of the same user keeps working
    assert UserSession.objects.get(pk=other_device["session_id"]).revoked_at is None
    assert api.post(REFRESH, {"refresh_token": other_device["refresh_token"]}, format="json").status_code == 200


def test_reuse_on_an_already_revoked_family_is_still_detected(api, login, user):
    tokens = login(user)
    api.post(REFRESH, {"refresh_token": tokens["refresh_token"]}, format="json")
    api.post(REFRESH, {"refresh_token": tokens["refresh_token"]}, format="json")  # revokes
    api.post(REFRESH, {"refresh_token": tokens["refresh_token"]}, format="json")  # again

    events = SecurityEvent.objects.filter(event_type=SecurityEventType.REFRESH_TOKEN_REUSE_DETECTED)
    assert sorted(e.metadata["session_was_active"] for e in events) == [False, True]


def test_unknown_refresh_token_is_rejected_without_revoking_anything(api, login, user):
    tokens = login(user)
    assert api.post(REFRESH, {"refresh_token": "never-issued"}, format="json").status_code == 401
    assert _rejection_reasons() == ["UNKNOWN_TOKEN"]
    assert UserSession.objects.get(pk=tokens["session_id"]).revoked_at is None


def test_expired_session_refuses_refresh_and_access(api, login, user):
    tokens = login(user)
    # Both columns together: the CHECK expires_at > created_at must still hold.
    UserSession.objects.filter(pk=tokens["session_id"]).update(
        created_at=timezone.now() - timedelta(days=31), expires_at=timezone.now() - timedelta(days=1)
    )
    assert api.post(REFRESH, {"refresh_token": tokens["refresh_token"]}, format="json").status_code == 401
    assert _rejection_reasons() == ["SESSION_EXPIRED"]
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access_token']}")
    assert api.get(ME).status_code == 401


def test_deactivated_user_loses_access_and_refresh(api, login, user):
    tokens = login(user)
    User.objects.filter(pk=user.pk).update(is_active=False)
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access_token']}")
    assert api.get(ME).status_code == 401
    assert api.post(REFRESH, {"refresh_token": tokens["refresh_token"]}, format="json").status_code == 401
    assert _rejection_reasons() == ["USER_INACTIVE"]


def test_revoked_session_refresh_is_logged_with_reason(api, login, user):
    tokens = login(user)
    UserSession.objects.filter(pk=tokens["session_id"]).update(revoked_at=timezone.now())
    assert api.post(REFRESH, {"refresh_token": tokens["refresh_token"]}, format="json").status_code == 401
    assert _rejection_reasons() == ["SESSION_REVOKED"]


# --- Multi-session, devices, global logout --------------------------------------


def test_sessions_are_independent(api, login, user):
    phone = login(user)
    tablet = login(user, device={**DEVICE, "identifier": "install-0002"})

    api.credentials(HTTP_AUTHORIZATION=f"Bearer {phone['access_token']}")
    assert api.post("/api/v1/auth/logout/").status_code == 200

    api.credentials(HTTP_AUTHORIZATION=f"Bearer {tablet['access_token']}")
    assert api.get(ME).status_code == 200


def test_device_is_tracked_and_reused(login, user):
    login(user)
    first_seen = UserDevice.objects.get(user=user).last_seen_at
    login(user, device={**DEVICE, "app_version": "0.2.0"})
    login(user, device={**DEVICE, "identifier": "install-0002", "device_name": "Tablette"})

    devices = UserDevice.objects.filter(user=user)
    assert devices.count() == 2
    phone = devices.get(device_name=DEVICE["device_name"])
    assert phone.sessions.count() == 2
    assert phone.app_version == "0.2.0"
    assert phone.last_seen_at > first_seen


REVOKE_ALL = "/api/v1/auth/sessions/revoke-all/"


def test_revoke_all_endpoint_revokes_every_session_including_current(api, login, user):
    sessions = [login(user, device={**DEVICE, "identifier": f"install-{i}"}) for i in range(3)]
    other_user_tokens = login(UserFactory())

    api.credentials(HTTP_AUTHORIZATION=f"Bearer {sessions[0]['access_token']}")
    response = api.post(REVOKE_ALL)
    assert response.status_code == 200
    assert response.json()["data"] == {"revoked_count": 3}

    for tokens in sessions:
        api.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access_token']}")
        assert api.get(ME).status_code == 401
        assert api.post(REFRESH, {"refresh_token": tokens["refresh_token"]}, format="json").status_code == 401
    # Another user's session is untouched.
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {other_user_tokens['access_token']}")
    assert api.get(ME).status_code == 200

    event = SecurityEvent.objects.get(event_type=SecurityEventType.ALL_SESSIONS_REVOKED)
    assert (event.user_id, event.severity) == (user.id, "INFO")
    assert event.metadata == {"revoked_count": 3, "initiated_by": "SELF"}


def test_revoke_all_requires_authentication(api):
    response = api.post(REVOKE_ALL)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


def test_administrative_revocation_is_recorded_with_its_actor(login, user):
    """Prepared for the future admin endpoint: the service records who acted."""
    login(user)
    admin = UserFactory()
    assert services.revoke_all_sessions(user, actor=admin) == 1
    event = SecurityEvent.objects.get(event_type=SecurityEventType.ALL_SESSIONS_REVOKED)
    assert event.severity == "WARNING"
    assert event.metadata == {"revoked_count": 1, "initiated_by": "ADMIN", "actor_id": str(admin.id)}


def test_global_logout_can_keep_current_session(login, user):
    keep = login(user)
    login(user, device={**DEVICE, "identifier": "install-0002"})
    current = UserSession.objects.get(pk=keep["session_id"])
    assert services.revoke_all_sessions(user, except_session=current) == 1
    current.refresh_from_db()
    assert current.revoked_at is None


# --- Success logging ---------------------------------------------------------------


def test_successes_are_logged_after_commit(api, user):
    tokens = api.post(
        LOGIN, {"identifier": user.username, "password": DEFAULT_PASSWORD, "device": DEVICE}, format="json"
    ).json()["data"]
    tokens = api.post(REFRESH, {"refresh_token": tokens["refresh_token"]}, format="json").json()["data"]
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access_token']}")
    api.post("/api/v1/auth/logout/")

    events = list(SecurityEvent.objects.order_by("created_at").values_list("event_type", "user_id"))
    assert events == [
        (SecurityEventType.LOGIN_SUCCEEDED, user.id),
        (SecurityEventType.TOKEN_REFRESHED, user.id),
        (SecurityEventType.LOGOUT, user.id),
    ]
    login_event = SecurityEvent.objects.get(event_type=SecurityEventType.LOGIN_SUCCEEDED)
    assert login_event.metadata["session_id"] == tokens["session_id"]
    assert login_event.ip_address == "127.0.0.1"


# --- Error scenarios ----------------------------------------------------------------


@pytest.mark.parametrize(
    "header",
    ["Bearer", "Bearer a b", "Bearer not-a-signed-token", "Basic dXNlcjpwYXNz"],
)
def test_malformed_authorization_headers_are_rejected(api, header):
    response = api.get(ME, HTTP_AUTHORIZATION=header)
    assert response.status_code == 401
    assert response.json()["success"] is False


def test_signed_token_with_invalid_session_id_is_rejected(api):
    for sid in ["not-a-uuid", str(uuid.uuid4())]:
        token = signing.dumps({"sid": sid}, salt=ACCESS_TOKEN_SALT)
        assert api.get(ME, HTTP_AUTHORIZATION=f"Bearer {token}").status_code == 401


def test_refresh_errors(api):
    assert api.post(REFRESH, {}, format="json").status_code == 400
    garbage = api.post(REFRESH, {"refresh_token": "garbage"}, format="json")
    assert garbage.status_code == 401
    assert garbage.json()["error"] == {
        "code": "INVALID_REFRESH_TOKEN",
        "message": "Jeton de renouvellement invalide ou expiré.",
    }


def test_wrong_http_method_uses_error_envelope(api):
    response = api.get(LOGIN)
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


def test_unknown_device_platform_is_a_validation_error(api, user):
    response = api.post(
        LOGIN,
        {"identifier": user.username, "password": DEFAULT_PASSWORD, "device": {**DEVICE, "platform": "SYMBIAN"}},
        format="json",
    )
    assert response.status_code == 400
    assert "device" in response.json()["error"]["details"]
