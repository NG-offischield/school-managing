"""Convocations from the administration: who may be convened about a student
(GET /admin/convocations/recipients/ — active, verified links only), what the
administration list shows (names, never contact details), creation and
status, isolation between schools; the parents' own route is unchanged."""

import uuid

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import MembershipStatus
from apps.audit.models import AuditLog
from apps.communication.models import Notification
from apps.people import services as people
from apps.people.models import ParentStudent, VerificationMethod

from .attendance_world import make_attendance_world
from .conftest import DB
from .factories import ParentFactory, SchoolFactory, member_with_role

pytestmark = DB
RECIPIENTS = "/api/v1/admin/convocations/recipients/"
CONVOCATIONS = "/api/v1/admin/convocations/"
RECIPIENT_FIELDS = {"parent", "name", "relationship_type", "is_primary_contact", "verified_at", "notified"}
PARENT_FIELDS = {
    "id",
    "student",
    "parent",
    "scheduled_start",
    "scheduled_end",
    "reason",
    "alert_level",
    "status",
    "notes",
}


@pytest.fixture
def w(school):
    return make_attendance_world(school)


def as_(membership):
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


def data(response, expected=200):
    assert response.status_code == expected, response.json()
    return response.json()["data"]


def parent_of(w, student, *, verified=True, relationship="MOTHER", **rights):
    parent = ParentFactory(school=w.school)
    link = people.link_parent(parent, student, relationship_type=relationship, **rights)
    if verified:
        people.verify_parent_link(link, actor=w.admin, method=VerificationMethod.ADMIN_IN_PERSON)
    return parent


def recipients(client, student):
    return data(client.get(RECIPIENTS, {"student": str(student.pk)}))


def body(student, parent, **extra):
    return {
        "student": str(student.pk),
        "parent": str(parent.pk),
        "scheduled_start": "2025-10-10T15:00:00+01:00",
        "scheduled_end": "2025-10-10T16:00:00+01:00",
        "reason": "Retards répétés",
        **extra,
    }


# --- who may be convened --------------------------------------------------------------


def test_only_active_verified_links_are_recipients(w):
    child = w.students[0]
    mother = parent_of(w, child, relationship="MOTHER", is_primary_contact=True)
    declared = parent_of(w, child, verified=False, relationship="FATHER")
    former = parent_of(w, child, relationship="TUTOR")
    ParentStudent.objects.filter(parent=former, student=child).update(active=False)
    parent_of(w, w.students[1])  # another pupil's parent
    rows = recipients(as_(w.admin), child)
    assert [r["parent"] for r in rows] == [str(mother.pk)]
    assert str(declared.pk) not in str(rows) and str(former.pk) not in str(rows)
    row = rows[0]
    assert set(row) == RECIPIENT_FIELDS  # nothing else: no phone, e-mail, address, document
    assert row["name"] == mother.membership.user.full_name
    assert (row["relationship_type"], row["is_primary_contact"], row["notified"]) == ("MOTHER", True, True)
    assert row["verified_at"]


def test_recipient_list_order_and_notification_reachability(w):
    child = w.students[0]
    second = parent_of(w, child, relationship="FATHER", can_receive_notifications=False)
    primary = parent_of(w, child, relationship="MOTHER", is_primary_contact=True)
    suspended = parent_of(w, child, relationship="TUTOR")
    suspended.membership.status = MembershipStatus.SUSPENDED
    suspended.membership.save(update_fields=["status"])
    rows = recipients(as_(w.admin), child)
    assert rows[0]["parent"] == str(primary.pk)  # the primary contact first
    reach = {r["parent"]: r["notified"] for r in rows}
    assert reach == {str(primary.pk): True, str(second.pk): False, str(suspended.pk): False}


def test_a_student_without_eligible_parent_is_an_empty_list(w):
    parent_of(w, w.students[0], verified=False)
    assert recipients(as_(w.admin), w.students[0]) == []


def test_recipients_permissions_and_parameters(w, api):
    child = w.students[0]
    parent = parent_of(w, child)
    assert api.get(RECIPIENTS, {"student": str(child.pk)}).status_code == 401
    for member in (w.tm_member, w.guardian_member, parent.membership, member_with_role(w.school, "STAFF")):
        response = as_(member).get(RECIPIENTS, {"student": str(child.pk)})
        assert response.status_code == 403, member
    admin = as_(w.admin)
    missing = admin.get(RECIPIENTS)
    assert missing.status_code == 400 and "student" in missing.json()["error"]["details"]
    assert admin.get(RECIPIENTS, {"student": "not-a-uuid"}).status_code == 400
    assert admin.get(RECIPIENTS, {"student": str(uuid.uuid4())}).status_code == 404


def test_another_schools_student_is_never_reachable(w):
    other = make_attendance_world(SchoolFactory())
    foreign_parent = parent_of(other, other.students[0])
    response = as_(w.admin).get(RECIPIENTS, {"student": str(other.students[0].pk)})
    assert response.status_code == 404  # same answer as an unknown id
    assert str(foreign_parent.pk) not in response.content.decode()
    # nor through creation: the other school's parent / student ids are 404s
    mine = w.students[0]
    assert as_(w.admin).post(CONVOCATIONS, body(mine, foreign_parent), format="json").status_code == 404
    local = parent_of(w, mine)
    assert as_(w.admin).post(CONVOCATIONS, body(other.students[0], local), format="json").status_code == 404


# --- creation, administration list, status ---------------------------------------------


def test_create_list_and_close_a_convocation(w):
    child = w.students[0]
    mother = parent_of(w, child)
    admin = as_(w.admin)
    created = data(admin.post(CONVOCATIONS, body(child, mother), format="json"), 201)
    assert created["status"] == "SCHEDULED" and created["reason"] == "Retards répétés"
    assert (created["student_name"], created["parent_name"]) == (child.full_name, mother.membership.user.full_name)
    assert created["student_number"] == child.student_number
    assert AuditLog.objects.filter(action="CONVOCATION_CREATED", entity_id=created["id"]).exists()
    note = Notification.objects.get(recipient=mother.membership, notification_type="CONVOCATION")
    assert note.text["title"]["key"] == "convocation.scheduled.title"  # the bilingual mechanism

    listed = data(admin.get(CONVOCATIONS))
    assert [c["id"] for c in listed] == [created["id"]]
    assert set(listed[0]) == PARENT_FIELDS | {"student_name", "student_number", "parent_name"}
    assert "phone" not in str(listed) and "email" not in str(listed)

    closed = data(admin.post(f"{CONVOCATIONS}{created['id']}/status/", {"status": "HELD", "notes": "Venue"}))
    assert (closed["status"], closed["notes"], closed["parent_name"]) == (
        "HELD",
        "Venue",
        mother.membership.user.full_name,
    )
    assert data(admin.get(CONVOCATIONS, {"status": "SCHEDULED"})) == []
    assert [c["id"] for c in data(admin.get(CONVOCATIONS, {"status": "HELD"}))] == [created["id"]]
    assert admin.get(CONVOCATIONS, {"status": "WHATEVER"}).status_code == 400
    again = admin.post(f"{CONVOCATIONS}{created['id']}/status/", {"status": "CANCELLED"})
    assert again.status_code == 400  # closed once: the server refuses


def test_creation_refuses_a_declared_link_and_bad_data(w):
    child = w.students[0]
    declared = parent_of(w, child, verified=False)
    admin = as_(w.admin)
    refused = admin.post(CONVOCATIONS, body(child, declared), format="json")
    assert refused.status_code == 400 and refused.json()["error"]["details"]["rule"] == "parent_not_linked"
    mother = parent_of(w, child)
    backwards = body(child, mother, scheduled_end="2025-10-10T14:00:00+01:00")
    assert admin.post(CONVOCATIONS, backwards, format="json").status_code == 400
    assert admin.post(CONVOCATIONS, body(child, mother, reason=""), format="json").status_code == 400
    assert not data(admin.get(CONVOCATIONS))


def test_parents_route_keeps_its_contract(w):
    child = w.students[0]
    mother = parent_of(w, child)
    data(as_(w.admin).post(CONVOCATIONS, body(child, mother), format="json"), 201)
    mine = data(as_(mother.membership).get("/api/v1/parents/convocations/"))
    assert len(mine) == 1 and set(mine[0]) == PARENT_FIELDS  # unchanged for the parent app
