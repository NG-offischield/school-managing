"""Pre-enrollment workflow (ADR 0032): the server decides status, consent and
reference; transitions are controlled; the invitation is a 48 h single-use
activation code of a parent account WITHOUT any child link; abuse is limited."""

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.test import override_settings
from django.utils import timezone

from apps.accounts import activation
from apps.accounts.models import AccountActivation, RoleCode, User
from apps.admissions import services as admissions
from apps.admissions.models import PreEnrollment
from apps.people.models import ParentStudent

from .conftest import DB
from .factories import SchoolFactory, UserFactory
from .isbree_world import client, data, make_isbree_world

pytestmark = DB


@pytest.fixture
def w(school):
    cache.clear()  # throttle counters
    return make_isbree_world(school)


def form(w, **extra):
    return {
        "guardian_first_name": "Mireille",
        "guardian_last_name": "Atangana",
        "guardian_phone": "+237 690 00 00 00",
        "guardian_email": "mireille.atangana@famille.test",
        "relationship": "MOTHER",
        "child_first_name": "Paul",
        "child_last_name": "Atangana",
        "requested_level": str(w.level.pk),
        "requested_year": str(w.year.pk),
        "consent": True,
        **extra,
    }


def submit(w, **extra):
    url = f"/api/v1/public/{w.school.code}/pre-enrollments/"
    return client().post(url, form(w, **extra), format="json")


def accepted(w):
    request = PreEnrollment.objects.get(reference=data(submit(w), 202)["reference"])
    request = admissions.change_status(request, "UNDER_REVIEW", actor=w.admin)
    return admissions.change_status(request, "ACCEPTED", actor=w.admin, message_to_family="Bienvenue")


# --- submission ----------------------------------------------------------------------------


def test_submission_is_initialised_by_the_server_only(w):
    body = data(submit(w, status="ACCEPTED", consent_at="2000-01-01T00:00:00Z", account="x"), 202)
    request = PreEnrollment.objects.get(reference=body["reference"])
    assert (request.status, request.account_id) == ("RECEIVED", None)  # the client chose nothing
    assert request.consent_at > timezone.now() - timedelta(minutes=1) and request.consent_version
    assert body == {"received": True, "reference": request.reference}  # nothing else is returned
    assert request.reference.startswith(f"PRE-{w.year.start_date.year}-")
    assert [e.action for e in request.events.all()] == ["SUBMITTED"]


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"consent": False}, "consent"),
        ({"guardian_email": "pas-un-email"}, "guardian_email"),
        ({"guardian_phone": "<script>"}, "guardian_phone"),
        ({"comment": "x" * 1001}, "comment"),
        ({"child_first_name": ""}, "child_first_name"),
        ({"relationship": "NEIGHBOUR"}, "relationship"),
        ({"child_birth_date": "1950-01-01"}, "child_birth_date"),
    ],
)
def test_invalid_submissions_are_refused_with_the_field(w, change, field):
    response = submit(w, **change)
    assert response.status_code == 400 and field in response.json()["error"]["details"]
    assert not PreEnrollment.objects.exists()


def test_closed_level_and_other_schools_level_are_refused(w):
    other = make_isbree_world(SchoolFactory())
    refused = submit(w, requested_level=str(other.level.pk))
    assert refused.status_code == 400 and refused.json()["error"]["details"]["rule"] == "level_not_offered"
    w.level.public_visible = False  # the school no longer offers it publicly
    w.level.save(update_fields=["public_visible"])
    assert submit(w).json()["error"]["details"]["rule"] == "level_not_offered"


def test_honeypot_and_rate_limit(w):
    trapped = data(submit(w, website="http://spam.example"), 202)
    assert trapped == {"received": True, "reference": None} and not PreEnrollment.objects.exists()
    cache.clear()
    codes = [submit(w, guardian_email=f"f{i}@famille.test").status_code for i in range(6)]
    assert codes == [202] * 5 + [429]  # 5 requests / hour / IP


# --- review and invitation ---------------------------------------------------------------


def test_transitions_are_controlled_and_need_reasons(w):
    request = PreEnrollment.objects.get(reference=data(submit(w), 202)["reference"])
    with pytest.raises(Exception, match="not allowed"):
        admissions.change_status(request, "ACCEPTED", actor=w.admin)  # must be reviewed first
    request = admissions.change_status(request, "UNDER_REVIEW", actor=w.admin)
    with pytest.raises(Exception, match="reason"):
        admissions.change_status(request, "REJECTED", actor=w.admin)
    request = admissions.change_status(request, "REJECTED", actor=w.admin, note="Classe complète")
    assert request.decided_by == w.admin and request.decided_at
    with pytest.raises(Exception, match="not allowed"):
        admissions.change_status(request, "UNDER_REVIEW", actor=w.admin)  # a decision is final
    with pytest.raises(PermissionDenied):
        admissions.change_status(request, "UNDER_REVIEW", actor=w.tm_member)  # not an administrator


def test_review_api_is_admin_only_and_school_scoped(w, api):
    request = accepted(w)
    url = f"/api/v1/admin/pre-enrollments/{request.pk}/"
    assert api.get(url).status_code == 401
    for member in (w.editor, w.tm_member, w.parent, w.guardian, w.staff_member):
        assert client(member).get(url).status_code == 403
    other = make_isbree_world(SchoolFactory())
    assert client(other.admin).get(url).status_code == 404  # another school's request
    detail = data(client(w.admin).get(url))
    assert detail["status"] == "ACCEPTED" and detail["invitation"]["state"] == "NONE"
    assert [e["action"] for e in detail["events"]] == ["SUBMITTED", "STATUS_CHANGED", "STATUS_CHANGED"]
    rows = data(client(w.admin).get("/api/v1/admin/pre-enrollments/?search=atangana"))
    assert [r["reference"] for r in rows] == [request.reference]


@override_settings(ISBREE_PORTAL_URL="https://portail.example")
def test_invitation_creates_a_parent_account_without_any_child_link(w):
    request = accepted(w)
    body = data(client(w.admin).post(f"/api/v1/admin/pre-enrollments/{request.pk}/invite/"), 201)
    assert body["link"] == f"https://portail.example/activation#code={body['code']}"  # code in the fragment
    request.refresh_from_db()
    membership = request.account
    assert membership.role_codes() == {RoleCode.PARENT} and not membership.user.has_usable_password()
    assert not ParentStudent.objects.filter(parent__membership=membership).exists()  # no child, no school data
    stored = AccountActivation.objects.get(membership=membership)
    assert stored.code_hash != body["code"] and body["code"] not in str(stored.__dict__)  # hashed only
    assert stored.expires_at <= timezone.now() + timedelta(hours=48, minutes=1)
    # The family activates with the EXISTING activation endpoints.
    checked = data(client().post("/api/v1/auth/activation/check/", {"code": body["code"]}, format="json"))
    assert checked["first_name"] == "Mireille"
    data(
        client().post(
            "/api/v1/auth/activation/complete/",
            {"code": body["code"], "password": "Un-Mot-De-Passe-Solide-2026"},
            format="json",
        )
    )
    again = client().post(
        "/api/v1/auth/activation/complete/",
        {"code": body["code"], "password": "Autre-Mot-De-Passe-2026"},
        format="json",
    )
    assert again.status_code == 400  # single use
    with pytest.raises(Exception, match="already activated"):
        admissions.invite(request, actor=w.admin)


def test_expired_invitation_is_refused_and_a_resend_revokes_the_previous_code(w):
    request = accepted(w)
    first, code, _ = admissions.invite(request, actor=w.admin)
    with pytest.raises(Exception, match="just issued"):
        admissions.invite(request, actor=w.admin)  # throttled resend
    AccountActivation.objects.filter(pk=first.activation_id).update(
        created_at=timezone.now() - timedelta(hours=49), expires_at=timezone.now() - timedelta(hours=1)
    )
    expired = client().post("/api/v1/auth/activation/check/", {"code": code}, format="json")
    assert expired.status_code == 400 and expired.json()["error"]["code"] == "INVALID_ACTIVATION_CODE"
    assert admissions.invitation_state(request)[0] == "EXPIRED"
    type(first).objects.filter(pk=first.pk).update(created_at=timezone.now() - timedelta(minutes=10))
    _, new_code, _ = admissions.invite(request, actor=w.admin)
    assert client().post("/api/v1/auth/activation/check/", {"code": new_code}, format="json").status_code == 200
    assert admissions.invitation_state(request)[0] == "PENDING"


def test_existing_email_is_never_linked_automatically(w):
    UserFactory(email="mireille.atangana@famille.test", username="mireille.atangana@famille.test")
    request = accepted(w)
    refused = client(w.admin).post(f"/api/v1/admin/pre-enrollments/{request.pk}/invite/")
    assert refused.status_code == 400 and refused.json()["error"]["details"]["rule"] == "account_exists"
    request.refresh_from_db()
    assert (
        request.account_id is None and User.objects.filter(email__iexact="mireille.atangana@famille.test").count() == 1
    )


def test_only_accepted_requests_can_be_invited(w):
    request = PreEnrollment.objects.get(reference=data(submit(w), 202)["reference"])
    refused = client(w.admin).post(f"/api/v1/admin/pre-enrollments/{request.pk}/invite/")
    assert refused.status_code == 400 and refused.json()["error"]["details"]["rule"] == "not_accepted"
    assert not AccountActivation.objects.filter(
        membership__school=w.school, membership__user__email="mireille.atangana@famille.test"
    ).exists()


def test_activation_helper_default_lifetime_is_unchanged(w):
    account = accepted(w)
    membership = admissions._parent_account(account, w.admin)
    issued, _ = activation.issue_activation(membership, actor=w.admin)
    assert issued.expires_at > timezone.now() + timedelta(hours=70)  # ACCOUNT_ACTIVATION_LIFETIME (72 h)
