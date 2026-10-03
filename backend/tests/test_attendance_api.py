"""Attendance & QR API: roles, isolation, what each audience may see."""

import uuid

import pytest
from rest_framework.test import APIClient

from apps.attendance import services as att
from apps.people import services as people
from apps.people.models import VerificationMethod

from .attendance_world import MONDAY, at, make_attendance_world
from .conftest import DB
from .factories import ParentFactory, SchoolFactory, member_with_role

pytestmark = DB


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


def verified_parent(w, student):
    parent = ParentFactory(school=w.school)
    link = people.link_parent(parent, student, relationship_type="MOTHER")
    people.verify_parent_link(link, actor=w.admin, method=VerificationMethod.ADMIN_IN_PERSON)
    return parent.membership


def test_scan_endpoint_returns_minimum_and_never_the_token(w):
    token = w.qr[w.students[0].pk].token
    body = data(as_(w.guardian_member).post("/api/v1/qr/scans/", {"token": token}, format="json"), 201)
    assert body["result"] in ("ACCEPTED", "ALREADY_PRESENT")
    assert body["student"]["name"] == w.students[0].full_name and body["student"]["class"] == "3e A"
    assert body["attendance"]["status"] in ("PRESENT", "LATE")
    assert token not in str(body) and body["solvency"] is None


def test_scan_unknown_token_is_a_logged_refusal_not_an_error(w):
    body = data(as_(w.guardian_member).post("/api/v1/qr/scans/", {"token": "nope"}, format="json"), 201)
    assert (body["result"], body["student"], body["attendance"]) == ("UNKNOWN_TOKEN", None, None)


def test_scan_permissions(w, api):
    token = w.qr[w.students[0].pk].token
    assert api.post("/api/v1/qr/scans/", {"token": token}, format="json").status_code == 401
    parent = as_(member_with_role(w.school, "PARENT")).post("/api/v1/qr/scans/", {"token": token}, format="json")
    assert (parent.status_code, parent.json()["error"]["code"]) == (403, "PERMISSION_DENIED")


def test_scan_device_must_belong_to_the_caller(w):
    body = {"token": w.qr[w.students[0].pk].token, "device_id": str(uuid.uuid4())}
    assert data(as_(w.guardian_member).post("/api/v1/qr/scans/", body, format="json"), 201)["result"]


def test_guardian_sees_only_own_scans_admin_sees_all(w):
    staff = member_with_role(w.school, "STAFF")
    mine = att.scan(w.qr[w.students[0].pk].token, actor=w.guardian_member, at=at(7)).scan
    theirs = att.scan(w.qr[w.students[1].pk].token, actor=staff, at=at(7)).scan
    seen = {r["id"] for r in data(as_(w.guardian_member).get("/api/v1/guardians/scans/"))}
    assert seen == {str(mine.id)}
    admin_seen = {r["id"] for r in data(as_(w.admin).get(f"/api/v1/admin/scans/?date={MONDAY}"))}
    assert {str(mine.id), str(theirs.id)} <= admin_seen
    assert as_(w.guardian_member).get("/api/v1/admin/scans/").status_code == 403


def test_parent_sees_only_accepted_scans_of_own_child(w):
    child, other = w.students[0], w.students[1]
    att.scan(w.qr[child.pk].token, actor=w.guardian_member, at=at(7))
    att.scan(w.qr[other.pk].token, actor=w.guardian_member, at=at(7))
    att.scan("bogus", actor=w.guardian_member, at=at(7))
    parent = as_(verified_parent(w, child))
    rows = data(parent.get(f"/api/v1/students/{child.id}/scans/"))
    assert len(rows) == 1 and set(rows[0]) == {"id", "scanned_at", "result"}  # no scanner identity
    assert data(parent.get(f"/api/v1/students/{other.id}/scans/")) == []


def test_student_attendance_endpoint_visibility(w):
    child = w.students[0]
    att.finalize_day(w.school, MONDAY, actor=w.admin)
    parent = as_(verified_parent(w, child))
    body = data(parent.get(f"/api/v1/students/{child.id}/attendance/"))
    assert body["summary"]["alert_level"] == "NONE" and body["records"][0]["status"] == "ABSENT"
    assert parent.get(f"/api/v1/students/{w.students[1].id}/attendance/").status_code == 404
    assert as_(w.tm_member).get(f"/api/v1/students/{child.id}/attendance/").status_code == 200  # class teacher


def test_admin_qr_endpoints(w):
    admin, s = as_(w.admin), w.students[0]
    listed = data(admin.get(f"/api/v1/admin/qr-codes/?student={s.id}"))
    assert listed[0]["token"] == w.qr[s.pk].token  # admins can print cards
    reissued = data(
        admin.post("/api/v1/admin/qr-codes/reissue/", {"student": str(s.id), "reason": "Perdu"}, format="json"), 201
    )
    assert reissued["version"] == 2
    revoked = data(admin.post(f"/api/v1/admin/qr-codes/{reissued['id']}/revoke/", {"reason": "Volé"}, format="json"))
    assert revoked["status"] == "REVOKED"
    issued = data(admin.post("/api/v1/admin/qr-codes/issue/", {"student": str(s.id)}, format="json"), 201)
    assert issued["version"] == 3
    for path in ("/api/v1/admin/qr-codes/", "/api/v1/admin/attendance/policies/"):
        assert as_(w.tm_member).get(path).status_code == 403


def test_cross_school_ids_are_404(w):
    other = make_attendance_world(SchoolFactory())
    admin = as_(w.admin)
    foreign_student = other.students[0]
    assert (
        admin.post("/api/v1/admin/qr-codes/issue/", {"student": str(foreign_student.id)}, format="json").status_code
        == 404
    )
    assert (
        admin.post(
            f"/api/v1/admin/qr-codes/{other.qr[foreign_student.pk].id}/revoke/", {"reason": "x"}, format="json"
        ).status_code
        == 404
    )
    assert admin.get(f"/api/v1/students/{foreign_student.id}/attendance/").status_code == 404
    assert (
        admin.post(
            "/api/v1/admin/qr-codes/issue-class/", {"school_class": str(other.klass.id)}, format="json"
        ).status_code
        == 404
    )


def test_finalize_correct_and_dashboard(w):
    admin = as_(w.admin)
    att.scan(w.qr[w.students[0].pk].token, actor=w.guardian_member, at=at(8, 0))  # late
    result = data(admin.post("/api/v1/admin/attendance/finalize/", {"date": str(MONDAY)}, format="json"))
    assert result["absences_created"] == 2
    board = data(admin.get(f"/api/v1/admin/attendance/dashboard/?date={MONDAY}"))
    assert (board["counts"]["LATE"], board["counts"]["ABSENT"]) == (1, 2)
    record_id = data(admin.get(f"/api/v1/students/{w.students[1].id}/attendance/"))["records"][0]["id"]
    corrected = data(
        admin.post(
            f"/api/v1/admin/attendance/{record_id}/correct/", {"status": "EXCUSED", "reason": "Malade"}, format="json"
        )
    )
    assert corrected["status"] == "EXCUSED"
    no_reason = admin.post(f"/api/v1/admin/attendance/{record_id}/correct/", {"status": "ABSENT"}, format="json")
    assert no_reason.json()["error"]["code"] == "VALIDATION_ERROR"
    assert admin.get("/api/v1/admin/attendance/dashboard/").json()["error"]["code"] == "VALIDATION_ERROR"


def test_policy_put(w):
    admin = as_(w.admin)
    body = {
        "late_after_time": "07:45",
        "morning_absence_cutoff": "10:30",
        "absence_hours": "7.50",
        "day_absence_trigger": "NO_ARRIVAL",
        "active": True,
    }
    saved = data(admin.put("/api/v1/admin/attendance/policies/2/", body, format="json"))
    assert (saved["day_of_week"], saved["absence_hours"]) == (2, "7.50")
    assert admin.put("/api/v1/admin/attendance/policies/9/", body, format="json").status_code == 400


def test_convocations_api(w):
    child = w.students[0]
    parent_member = verified_parent(w, child)
    parent_id = parent_member.parent_profile.id
    body = {
        "student": str(child.id),
        "parent": str(parent_id),
        "scheduled_start": "2025-10-10T15:00:00+01:00",
        "scheduled_end": "2025-10-10T16:00:00+01:00",
        "reason": "Retards répétés",
    }
    created = data(as_(w.admin).post("/api/v1/admin/convocations/", body, format="json"), 201)
    assert as_(w.tm_member).post("/api/v1/admin/convocations/", body, format="json").status_code == 403
    mine = data(as_(parent_member).get("/api/v1/parents/convocations/"))
    assert [c["id"] for c in mine] == [created["id"]]
    assert data(as_(member_with_role(w.school, "PARENT")).get("/api/v1/parents/convocations/")) == []
