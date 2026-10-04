"""Account lifecycle (ADR 0024): activation codes for accounts created by the
administration, first password, disabling. Security properties: hashed
single-use codes, expiry, revocation, one generic answer (no enumeration),
school isolation, permissions, throttling, audit, no clear password / code."""

import json
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.throttling import ScopedRateThrottle

from apps.accounts import activation
from apps.accounts.models import AccountActivation, MembershipStatus, SecurityEvent, SecurityEventType, User
from apps.accounts.models import SchoolMembership as SchoolMembershipModel
from apps.audit.models import AuditLog

from .conftest import DB, DEVICE
from .factories import CategoryFactory, SchoolFactory, SubjectFactory, member_with_role
from .planning_world import make_planning_world
from .test_classes_api import as_, data, error
from .test_teachers_admin_api import TEACHERS, payload

pytestmark = DB

CHECK = "/api/v1/auth/activation/check/"
COMPLETE = "/api/v1/auth/activation/complete/"
STRONG = "Ecole-2026!Tableau-Noir"


@pytest.fixture
def w(school):
    """The teachers-administration world (same as test_teachers_admin_api)."""
    w = make_planning_world(school)
    w.sci = w.maths.category
    w.physics = SubjectFactory(school=school, code="PHY", name="Physique", category=w.sci)
    w.music = SubjectFactory(
        school=school, code="MUS", name="Musique", category=CategoryFactory(school=school, code="ART")
    )
    return w


def login_as(api, user, password=STRONG):
    return api.post(
        "/api/v1/auth/login/", {"identifier": user.username, "password": password, "device": DEVICE}, format="json"
    )


def rule(response, status):
    return error(response, status)["details"]["rule"]


def account(pk):
    return f"/api/v1/admin/accounts/{pk}/"


def new_teacher(w):
    body = data(as_(w.admin).post(TEACHERS, payload(w), format="json"), 201)
    return body


def issue(w, membership_id, client=None):
    return data((client or as_(w.admin)).post(account(membership_id) + "activation/"), 201)


def refused(response):
    """Every refusal of a code: same status, same body (anti-enumeration)."""
    assert response.status_code == 400, response.json()
    return response.json()


def test_teacher_account_full_lifecycle(w, api):
    teacher = new_teacher(w)
    assert teacher["account_state"] == "NOT_ACTIVATED" and not teacher["account_activated"]
    member_id = teacher["membership"]
    user = User.objects.get(memberships__pk=member_id)
    assert not user.has_usable_password()  # created without any password
    issued = issue(w, member_id)
    code = issued["code"]
    assert len(code) == 24 and issued["account"]["state"] == "PENDING_ACTIVATION"
    stored = AccountActivation.objects.get(membership_id=member_id)
    assert stored.code_hash == activation.code_hash(code) and code not in stored.code_hash
    # The code appears nowhere in the audit or the security log.
    logs = json.dumps([a.new_data for a in AuditLog.objects.all()] + [e.metadata for e in SecurityEvent.objects.all()])
    assert code not in logs and activation.normalise(code) not in logs
    assert data(as_(w.admin).get(account(member_id)))["state"] == "PENDING_ACTIVATION"
    assert "code" not in data(as_(w.admin).get(account(member_id)))

    preview = data(api.post(CHECK, {"code": code.lower().replace("-", " ")}, format="json"))
    assert preview["login"] == user.username and preview["school"] == w.school.name
    weak = api.post(COMPLETE, {"code": code, "password": "123"}, format="json")
    assert weak.status_code == 400 and weak.json()["error"]["code"] == "VALIDATION_ERROR"
    assert not User.objects.get(pk=user.pk).has_usable_password()  # the code is still usable
    assert data(api.post(COMPLETE, {"code": code, "password": STRONG}, format="json")) == {"login": user.username}
    user.refresh_from_db()
    assert user.has_usable_password() and user.password.startswith("argon2") and STRONG not in user.password

    tokens = data(
        api.post(
            "/api/v1/auth/login/", {"identifier": user.username, "password": STRONG, "device": DEVICE}, format="json"
        )
    )
    renewed = data(api.post("/api/v1/auth/refresh/", {"refresh_token": tokens["refresh_token"]}, format="json"))
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {renewed['access_token']}")
    assert api.post("/api/v1/auth/logout/").status_code == 200
    api.credentials()

    reused = refused(api.post(COMPLETE, {"code": code, "password": "Autre-2026!Mot-De-Passe"}, format="json"))
    assert reused["error"]["code"] == "INVALID_ACTIVATION_CODE"
    assert SecurityEvent.objects.filter(
        event_type=SecurityEventType.ACCOUNT_ACTIVATION_REJECTED, metadata__reason="ALREADY_USED"
    ).exists()
    assert data(as_(w.admin).get(account(member_id)))["state"] == "ACTIVE"
    assert rule(as_(w.admin).post(account(member_id) + "activation/"), 409) == "account_already_active"
    actions = set(AuditLog.objects.filter(entity_id=member_id).values_list("action", flat=True))
    assert {"ACCOUNT_ACTIVATION_ISSUED", "ACCOUNT_ACTIVATED"} <= actions
    assert SecurityEvent.objects.filter(event_type=SecurityEventType.ACCOUNT_ACTIVATED, user=user).exists()


def test_every_refusal_is_the_same_answer(w, api):
    member_id = new_teacher(w)["membership"]
    unknown = refused(api.post(CHECK, {"code": "AAAA-BBBB-CCCC-DDDD-EEEE"}, format="json"))
    expired_code = issue(w, member_id)["code"]
    AccountActivation.objects.filter(membership_id=member_id).update(
        created_at=timezone.now() - timedelta(days=5), expires_at=timezone.now() - timedelta(days=2)
    )
    expired = refused(api.post(COMPLETE, {"code": expired_code, "password": STRONG}, format="json"))
    first = issue(w, member_id)["code"]
    second = issue(w, member_id)["code"]  # a new code revokes the previous one
    revoked = refused(api.post(CHECK, {"code": first}, format="json"))
    assert unknown == expired == revoked
    reasons = set(
        SecurityEvent.objects.filter(event_type=SecurityEventType.ACCOUNT_ACTIVATION_REJECTED).values_list(
            "metadata__reason", flat=True
        )
    )
    assert reasons == {"UNKNOWN_CODE", "EXPIRED", "REVOKED"}  # the reason is in the log only
    data(as_(w.admin).post(account(member_id) + "activation/revoke/"))
    refused(api.post(CHECK, {"code": second}, format="json"))
    assert error(as_(w.admin).post(account(member_id) + "activation/revoke/"), 409)["details"]["rule"] == (
        "no_pending_activation"
    )
    assert data(as_(w.admin).get(account(member_id)))["state"] == "NOT_ACTIVATED"


def test_disabled_account(w, api, login):
    member_id = new_teacher(w)["membership"]
    code = issue(w, member_id)["code"]
    data(api.post(COMPLETE, {"code": code, "password": STRONG}, format="json"))
    user = User.objects.get(memberships__pk=member_id)
    tokens = data(
        api.post(
            "/api/v1/auth/login/", {"identifier": user.username, "password": STRONG, "device": DEVICE}, format="json"
        )
    )
    assert error(as_(w.admin).post(account(member_id) + "disable/", {"reason": ""}, format="json"), 400)
    summary = data(as_(w.admin).post(account(member_id) + "disable/", {"reason": "Fin de contrat"}, format="json"))
    assert summary["state"] == "DISABLED"
    user.refresh_from_db()
    assert not user.is_active and user.memberships.get().status == MembershipStatus.SUSPENDED
    login_again = login_as(api, user)
    assert login_again.status_code == 401  # existing check: inactive user
    assert (
        api.post("/api/v1/auth/refresh/", {"refresh_token": tokens["refresh_token"]}, format="json").status_code == 401
    )
    assert rule(as_(w.admin).post(account(member_id) + "activation/"), 409) == "account_already_active"
    assert (
        error(as_(w.admin).post(account(w.admin.pk) + "disable/", {"reason": "x"}, format="json"), 400)["details"][
            "rule"
        ]
        == "cannot_disable_self"
    )
    assert data(as_(w.admin).post(account(member_id) + "enable/"))["state"] == "ACTIVE"
    assert {"ACCOUNT_DISABLED", "ACCOUNT_ENABLED"} <= set(
        AuditLog.objects.filter(entity_id=member_id).values_list("action", flat=True)
    )


def test_pending_code_of_a_disabled_account_is_unusable(w, api):
    member_id = new_teacher(w)["membership"]
    code = issue(w, member_id)["code"]
    data(as_(w.admin).post(account(member_id) + "disable/", {"reason": "Erreur de saisie"}, format="json"))
    refused(api.post(COMPLETE, {"code": code, "password": STRONG}, format="json"))  # revoked with the account
    assert error(as_(w.admin).post(account(member_id) + "activation/"), 409)["details"]["rule"] == "account_disabled"


def test_permissions_and_school_isolation(w, api):
    member_id = new_teacher(w)["membership"]
    teacher = member_with_role(w.school, "TEACHER")
    for path in ("", "activation/", "activation/revoke/", "disable/", "enable/"):
        method = "get" if path == "" else "post"
        assert getattr(as_(teacher), method)(account(member_id) + path).status_code == 403
    other_school = SchoolFactory()
    other_admin = member_with_role(other_school, "ADMIN")
    for path in ("", "activation/", "disable/"):
        method = "get" if path == "" else "post"
        response = getattr(as_(other_admin), method)(account(member_id) + path, {"reason": "x"}, format="json")
        assert response.status_code == 404  # another school's member does not exist here
    super_admin = member_with_role(w.school, "SUPER_ADMIN")
    super_admin.user.set_unusable_password()
    super_admin.user.save()
    plain_admin = member_with_role(w.school, "ADMIN")
    assert as_(plain_admin).post(account(super_admin.pk) + "activation/").status_code == 403
    assert api.get(account(member_id)).status_code == 401


def test_activation_is_throttled(w, api, monkeypatch):
    monkeypatch.setitem(ScopedRateThrottle.THROTTLE_RATES, "auth-activation", "3/min")
    codes = [api.post(CHECK, {"code": f"WRONG-{i}"}, format="json").status_code for i in range(5)]
    assert codes[:3] == [400, 400, 400] and codes[3:] == [429, 429]


def test_codes_are_random_and_normalised():
    codes = {activation.new_code() for _ in range(200)}
    assert len(codes) == 200
    assert all(len(c) == 24 and c.count("-") == 4 for c in codes)
    assert activation.normalise("ab cd-ef0o-il") == "ABCDEF0011"


def test_service_refuses_an_administrator_of_another_school(w):
    """Defence in depth: even called directly, the service checks the school."""
    from django.core.exceptions import PermissionDenied

    member = SchoolMembershipModel.objects.get(pk=new_teacher(w)["membership"])
    other_admin = member_with_role(SchoolFactory(), "ADMIN")
    for call in (
        lambda: activation.issue_activation(member, actor=other_admin),
        lambda: activation.revoke_activation(member, actor=other_admin),
        lambda: activation.disable_account(member, actor=other_admin, reason="x"),
    ):
        with pytest.raises(PermissionDenied):
            call()


def test_code_of_an_account_suspended_otherwise_is_refused(w, api):
    """A pending code stays unusable when the account is suspended by another
    path (here: the whole school is suspended)."""
    member_id = new_teacher(w)["membership"]
    code = issue(w, member_id)["code"]
    w.school.status = "SUSPENDED"
    w.school.save(update_fields=["status"])
    refused(api.post(COMPLETE, {"code": code, "password": STRONG}, format="json"))
    assert SecurityEvent.objects.filter(
        event_type=SecurityEventType.ACCOUNT_ACTIVATION_REJECTED, metadata__reason="ACCOUNT_DISABLED"
    ).exists()
    assert not User.objects.get(memberships__pk=member_id).has_usable_password()
