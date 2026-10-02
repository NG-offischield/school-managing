"""API error format and localisation (ADR 0007)."""

import pytest
from django.urls import include, path
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import School
from common.errors import ERROR_MESSAGES, ErrorCode
from common.permissions import IsSchoolMember

from .conftest import DB, DEVICE
from .factories import UserFactory

pytestmark = [DB, pytest.mark.urls("tests.test_api_errors")]


class Explodes(APIView):
    """Writes to the database, then crashes with an unexpected error."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        School.objects.create(code="HALF", name="Half-done", city="x", address="x")
        raise RuntimeError("internal detail that must not leak")


class MembersOnly(APIView):
    permission_classes = [IsSchoolMember]

    def get(self, request):
        return Response({})


urlpatterns = [
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("explodes/", Explodes.as_view()),
    path("members-only/", MembersOnly.as_view()),
]

LOGIN = "/api/v1/auth/login/"
BAD_LOGIN = {"identifier": "nobody", "password": "x", "device": DEVICE}


def test_every_code_has_a_message_and_codes_are_stable_english():
    assert set(ERROR_MESSAGES) == set(ErrorCode)
    for code in ErrorCode:
        assert code.value == code.name and code.value.isascii() and code.value.isupper()


def test_error_body_shape_is_exactly_success_and_error(api):
    body = api.post(LOGIN, BAD_LOGIN, format="json").json()
    assert set(body) == {"success", "error"}
    assert body["success"] is False
    assert set(body["error"]) == {"code", "message"}


def test_messages_are_french_by_default(api):
    error = api.post(LOGIN, BAD_LOGIN, format="json").json()["error"]
    assert error == {"code": "INVALID_CREDENTIALS", "message": "Identifiants incorrects."}


def test_messages_switch_to_english_but_code_does_not(api):
    error = api.post(LOGIN, BAD_LOGIN, format="json", HTTP_ACCEPT_LANGUAGE="en").json()["error"]
    assert error == {"code": "INVALID_CREDENTIALS", "message": "Invalid credentials."}


def test_unsupported_language_falls_back_to_french(api):
    error = api.post(LOGIN, BAD_LOGIN, format="json", HTTP_ACCEPT_LANGUAGE="de").json()["error"]
    assert error["message"] == "Identifiants incorrects."


def test_validation_details_are_localised_too(api):
    fr = api.post(LOGIN, {}, format="json").json()["error"]
    en = api.post(LOGIN, {}, format="json", HTTP_ACCEPT_LANGUAGE="en").json()["error"]
    assert fr["code"] == en["code"] == "VALIDATION_ERROR"
    assert fr["details"]["password"] == ["Ce champ est obligatoire."]
    assert en["details"]["password"] == ["This field is required."]


def test_rate_limit_gives_retry_after(api):
    for _ in range(10):
        api.post(LOGIN, BAD_LOGIN, format="json")
    response = api.post(LOGIN, BAD_LOGIN, format="json")
    assert response.status_code == 429
    error = response.json()["error"]
    assert error["code"] == "RATE_LIMITED"
    assert error["details"]["retry_after"] > 0
    assert "Retry-After" in response.headers


def test_not_authenticated_keeps_401_and_www_authenticate(api):
    response = api.get("/api/v1/auth/me/")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


def test_invalid_access_token_code(api):
    response = api.get("/api/v1/auth/me/", HTTP_AUTHORIZATION="Bearer forged")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_ACCESS_TOKEN"


def test_no_active_membership_code(api):
    api.force_authenticate(UserFactory())
    response = api.get("/members-only/")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "NO_ACTIVE_MEMBERSHIP"


def test_not_found_code(api):
    api.force_authenticate(UserFactory())
    response = api.post("/api/v1/auth/sessions/00000000-0000-0000-0000-000000000000/revoke/")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_unexpected_error_is_json_rolls_back_and_leaks_nothing(api):
    response = api.post("/explodes/")
    assert response.status_code == 500
    assert response.json() == {
        "success": False,
        "error": {"code": "SERVER_ERROR", "message": "Une erreur inattendue s'est produite."},
    }
    assert "internal detail" not in response.content.decode()
    # The half-done write of the failed request was rolled back, not committed.
    assert not School.objects.filter(code="HALF").exists()
