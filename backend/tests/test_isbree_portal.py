"""Espace ISBREE portal API (ADR 0032): the role context is chosen among the
roles HELD (never granted by the client), each role reads only its contents,
a parent only the resources of a VERIFIED child, downloads are checked by the
server, responses are never cached, sessions are re-checked, and the client
IP is trusted only from a web server proving itself."""

import pytest
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.services import ClientContext, login, revoke_session
from apps.website import services as web
from apps.website.models import ReleaseStatus

from .conftest import DB, DEVICE
from .factories import DEFAULT_PASSWORD, SchoolFactory, member_with_role
from .isbree_world import apk, client, data, make_isbree_world, pdf

pytestmark = DB
CONTEXT = "/api/v1/portal/context/"
RESOURCES = "/api/v1/portal/resources/"


@pytest.fixture
def w(school):
    cache.clear()
    return make_isbree_world(school)


def context(member, role=None):
    return data(client(member).get(CONTEXT, {"role": role} if role else {}))


def titles(rows, key="title"):
    return {r[key] for r in rows}


# --- role context -----------------------------------------------------------------------------


def test_each_role_reads_only_its_own_contents(w):
    parent = context(w.parent, "PARENT")
    assert parent["roles"] == ["PARENT"] and parent["role"] == "PARENT"
    assert titles(parent["faq"], "question") == {"Parents ?"}
    assert titles(parent["news"]) == {"Rentrée"}  # the staff note is never sent to a parent
    assert titles(parent["resources"]) == {"Horaires"}  # no child chosen: general resources only
    teacher = context(w.tm_member, "TEACHER")
    assert titles(teacher["pages"]) == {"Politique"} and titles(teacher["news"]) == set()
    assert titles(teacher["resources"]) == {"Programme 3e"}  # scoped to the level of their classes
    staff = context(w.staff_member, "STAFF")
    assert titles(staff["news"]) == {"Note interne"} and titles(staff["resources"]) == set()
    guardian = context(w.guardian, "GUARDIAN")
    assert titles(guardian["resources"]) == {"Accès au portail"} and guardian["pre_enrollments"] == []


def test_a_role_not_held_is_refused_never_granted(w, api):
    assert api.get(CONTEXT).status_code == 401
    for member, role in ((w.parent, "TEACHER"), (w.tm_member, "PARENT"), (w.guardian, "STAFF"), (w.parent, "ADMIN")):
        response = client(member).get(CONTEXT, {"role": role})
        assert response.status_code == 403, (member, role)
    assert client(w.admin).get(CONTEXT).status_code == 403  # an administrator has no portal role


def test_multi_role_member_chooses_a_context_without_mixing_data(w):
    both = member_with_role(w.school, "TEACHER")
    from apps.accounts.models import MembershipRole, Role

    MembershipRole.objects.create(membership=both, role=Role.objects.get(code="GUARDIAN"))
    as_guardian = context(both, "GUARDIAN")
    assert sorted(as_guardian["roles"]) == ["GUARDIAN", "TEACHER"]
    assert titles(as_guardian["resources"]) == {"Accès au portail"}  # not the union of both roles
    assert {a["app"] for a in as_guardian["apps"]} == {"GUARDIAN", "TEACHER"}


def test_responses_are_private_and_never_cached(w):
    response = client(w.parent).get(CONTEXT, {"role": "PARENT"})
    assert response["Cache-Control"] == "private, no-store"


# --- a parent and the children -----------------------------------------------------------


def test_child_resources_require_a_verified_link_and_the_right_class(w):
    mine = data(client(w.parent).get(RESOURCES, {"role": "PARENT", "student": str(w.students[0].pk)}))
    assert titles(mine) == {"Horaires", "Fournitures 3e A"}
    # another family's child, an unverified link, an unknown id: the same 404
    assert client(w.parent).get(RESOURCES, {"role": "PARENT", "student": str(w.students[1].pk)}).status_code == 404
    assert client(w.unverified).get(RESOURCES, {"role": "PARENT", "student": str(w.students[0].pk)}).status_code in (
        403,
        404,
    )
    other = make_isbree_world(SchoolFactory())
    assert client(w.parent).get(RESOURCES, {"role": "PARENT", "student": str(other.students[0].pk)}).status_code == 404
    assert client(w.tm_member).get(RESOURCES, {"role": "TEACHER", "student": str(w.students[0].pk)}).status_code == 403


def test_documents_follow_the_same_rules(w):
    web.attach_document(w.class_supplies, actor=w.editor, upload=pdf())
    url = f"/api/v1/portal/resources/{w.class_supplies.pk}/document/"
    allowed = client(w.parent).get(url, {"role": "PARENT", "student": str(w.students[0].pk)})
    assert allowed.status_code == 200 and b"".join(allowed.streaming_content).startswith(b"%PDF")
    assert client(w.parent).get(url, {"role": "PARENT"}).status_code == 404  # no child chosen -> not in scope
    # the other family's child is in the same class: the class list is theirs too…
    assert client(w.other_parent).get(url, {"role": "PARENT", "student": str(w.students[1].pk)}).status_code == 200
    # …but asking through a child that is not theirs is a 404
    assert client(w.other_parent).get(url, {"role": "PARENT", "student": str(w.students[0].pk)}).status_code == 404
    assert client(w.guardian).get(url, {"role": "GUARDIAN"}).status_code == 404


def test_pre_enrollment_status_is_shown_to_its_family_only(w):
    from tests.test_isbree_admissions import accepted

    request = accepted(w)
    from apps.admissions import services as admissions

    admissions.invite(request, actor=w.admin)
    request.refresh_from_db()
    family = request.account
    shown = context(family, "PARENT")["pre_enrollments"]
    assert [(r["reference"], r["status"], r["message"]) for r in shown] == [
        (request.reference, "ACCEPTED", "Bienvenue")
    ]
    assert context(w.parent, "PARENT")["pre_enrollments"] == []
    assert data(client(family).get("/api/v1/parents/children/")) == []  # no child data without a verified link


# --- downloads ---------------------------------------------------------------------------


def test_downloads_only_published_releases_of_a_held_role(w):
    release = web.add_release(
        w.school, actor=w.editor, upload=apk(), app="PARENT", version_name="1.0.0", version_code=1
    )
    url = f"/api/v1/portal/apps/{release.pk}/download/"
    assert client(w.parent).get(url).status_code == 404  # still a draft
    assert context(w.parent, "PARENT")["apps"] == [{"app": "PARENT", "label": "Application Parent", "release": None}]
    web.set_release_status(release, ReleaseStatus.PUBLISHED, actor=w.editor)
    response = client(w.parent).get(url)
    assert response.status_code == 200 and response["Content-Disposition"].startswith("attachment")
    assert context(w.parent, "PARENT")["apps"][0]["release"]["package"] == "cm.schoolmanaging.school_parent"
    assert client(w.tm_member).get(url).status_code == 403  # not the teacher's application
    assert APIClient().get(url).status_code == 401
    other = make_isbree_world(SchoolFactory())
    assert client(other.parent).get(url).status_code == 404  # another school's file


# --- sessions and client IP ---------------------------------------------------------------


def test_a_revoked_session_is_refused(w):
    issued = login(w.parent.user.username, DEFAULT_PASSWORD, DEVICE, ClientContext())
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {issued.access_token}")
    assert api.get(CONTEXT, {"role": "PARENT"}).status_code == 200
    revoke_session(issued.session, ctx=ClientContext())
    assert api.get(CONTEXT, {"role": "PARENT"}).status_code == 401


@override_settings(WEB_BFF_TOKEN="test-bff-token-0123456789abcdef")
def test_client_ip_is_trusted_only_from_a_proven_web_server(w):
    url = f"/api/v1/public/{w.school.code}/pre-enrollments/"
    body = {"consent": False}  # invalid on purpose: only the throttling matters here

    def post(ip, token=None):
        headers = {"HTTP_X_ISBREE_CLIENT_IP": ip}
        if token:
            headers["HTTP_X_ISBREE_BFF"] = token
        return APIClient().post(url, body, format="json", **headers).status_code

    good = "test-bff-token-0123456789abcdef"
    # Through the proven web server, two visitors have two separate quotas.
    assert [post("198.51.100.1", good) for _ in range(5)] == [400] * 5
    assert post("198.51.100.1", good) == 429
    assert post("198.51.100.2", good) == 400
    # A forged header without (or with a wrong) token is ignored: same quota as the server address.
    cache.clear()
    assert [post(f"203.0.113.{i}", "wrong") for i in range(5)] == [400] * 5
    assert post("203.0.113.99") == 429
