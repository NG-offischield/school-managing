"""Read-side additions for the desktop communication / documents screens
(ADR 0023): the administration's member directory and the document search.
Nothing personal beyond the name and roles; another school sees nothing."""

import pytest
from rest_framework.test import APIClient

from apps.documents import services as documents
from apps.documents.models import DocumentKind

from .communication_world import make_communication_world
from .conftest import DB
from .factories import SchoolFactory
from .planning_world import MONDAY

pytestmark = DB


def as_(membership):
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


def rows(response, expected=200):
    assert response.status_code == expected, response.json()
    return response.json()["data"]


@pytest.fixture
def w(school):
    return make_communication_world(school)


def test_member_directory_is_admin_only_and_minimal(w):
    members = rows(as_(w.admin).get("/api/v1/admin/communication/members/"))
    ids = {m["id"] for m in members}
    assert str(w.parent.pk) in ids and str(w.admin.pk) in ids
    assert set(members[0]) == {"id", "name", "roles"}  # no e-mail, phone, address
    parents = rows(as_(w.admin).get("/api/v1/admin/communication/members/", {"role": "PARENT"}))
    assert parents and all("PARENT" in m["roles"] for m in parents)
    named = rows(as_(w.admin).get("/api/v1/admin/communication/members/", {"search": w.parent.user.last_name}))
    assert str(w.parent.pk) in {m["id"] for m in named}
    for outsider in (w.parent, w.tm.employee.membership, w.staff_member):
        assert as_(outsider).get("/api/v1/admin/communication/members/").status_code == 403
    other = make_communication_world(SchoolFactory())
    assert str(w.parent.pk) not in {m["id"] for m in rows(as_(other.admin).get("/api/v1/admin/communication/members/"))}


def test_document_search_narrows_visible_documents(w):
    class_doc, _ = documents.generate(DocumentKind.TIMETABLE, w.klass, actor=w.admin, date=MONDAY)
    documents.generate(DocumentKind.TIMETABLE, w.klass_b, actor=w.admin, date=MONDAY)
    admin = as_(w.admin)
    assert len(rows(admin.get("/api/v1/documents/", {"kind": "TIMETABLE"}))) == 2
    found = rows(admin.get("/api/v1/documents/", {"search": w.klass.name}))
    assert [d["id"] for d in found] == [str(class_doc.pk)]
    by_code = rows(admin.get("/api/v1/documents/", {"search": class_doc.verification_code.lower()}))
    assert [d["id"] for d in by_code] == [str(class_doc.pk)]
    # A search never reaches documents the caller may not read (other class, other school).
    assert rows(as_(w.other_parent).get("/api/v1/documents/", {"search": w.klass_b.name})) == []
    other = make_communication_world(SchoolFactory())
    assert rows(as_(other.admin).get("/api/v1/documents/", {"search": w.klass.name})) == []
