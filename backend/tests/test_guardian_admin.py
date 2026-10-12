"""Gate guardians administered from the desktop (people/guardian_admin_api.py)
and the attendance views it needs: creation with the EXISTING service, the
EXISTING activation and suspension, scans per guardian, the day's attendance —
administrators only, never across schools, no amount ever shown."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import MembershipStatus, RoleCode
from apps.attendance import services as att
from apps.audit.models import AuditLog

from .attendance_world import MONDAY, at, make_attendance_world
from .conftest import DB, DEVICE
from .factories import SchoolFactory, member_with_role

pytestmark = DB

GUARDIANS = "/api/v1/admin/guardians/"
STRONG = "Portail-Ecole-2026!"


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


def new_guardian(w, **extra):
    payload = {
        "first_name": "Moussa",
        "last_name": "Bello",
        "email": "moussa.bello@ecole.test",
        "guardian_number": "G-77",
        "phone": "699001122",
        **extra,
    }
    return as_(w.admin).post(GUARDIANS, payload, format="json")


def test_admin_creates_a_guardian_without_password_audited(w):
    body = data(new_guardian(w), 201)
    assert (body["guardian_number"], body["first_name"], body["account_status"]) == ("G-77", "Moussa", "ACTIVE")
    assert body["activated"] is False and body["scans_today"] == 0
    from apps.people.models import GuardianProfile

    guardian = GuardianProfile.objects.get(pk=body["id"])
    assert guardian.school_id == w.school.id and guardian.membership.role_codes() == {RoleCode.GUARDIAN}
    assert not guardian.membership.user.has_usable_password()
    assert AuditLog.objects.filter(action="GUARDIAN_CREATED", entity_id=guardian.pk, actor=w.admin).exists()
    listed = data(as_(w.admin).get(GUARDIANS))
    assert {g["guardian_number"] for g in listed} == {"G-01", "G-77"}
    assert [g["guardian_number"] for g in data(as_(w.admin).get(GUARDIANS + "?search=bello"))] == ["G-77"]


def test_duplicates_and_invalid_input_are_refused(w):
    data(new_guardian(w), 201)
    assert new_guardian(w, email="autre@ecole.test").status_code == 409  # number taken in this school
    assert new_guardian(w, guardian_number="G-78").status_code == 409  # e-mail taken
    assert new_guardian(w, guardian_number="G-79", email="pas-un-mail").status_code == 400
    assert new_guardian(w, guardian_number="", email="x@ecole.test").status_code == 400


def test_existing_activation_then_suspension_and_reactivation(w):
    body = data(new_guardian(w), 201)
    account = f"/api/v1/admin/accounts/{body['membership']}/"
    code = data(as_(w.admin).post(account + "activation/"), 201)["code"]
    api = APIClient()
    done = api.post("/api/v1/auth/activation/complete/", {"code": code, "password": STRONG}, format="json")
    assert done.status_code == 200, done.json()
    assert data(as_(w.admin).get(GUARDIANS + body["id"] + "/"))["activated"] is True
    login = {"identifier": "moussa.bello@ecole.test", "password": STRONG, "device": DEVICE}
    assert api.post("/api/v1/auth/login/", login, format="json").status_code == 200
    data(as_(w.admin).post(account + "disable/", {"reason": "Fin de contrat"}, format="json"))
    assert data(as_(w.admin).get(GUARDIANS + body["id"] + "/"))["account_status"] == MembershipStatus.SUSPENDED
    assert api.post("/api/v1/auth/login/", login, format="json").status_code == 401
    assert [g["id"] for g in data(as_(w.admin).get(GUARDIANS + "?status=SUSPENDED"))] == [body["id"]]
    data(as_(w.admin).post(account + "enable/"))
    assert api.post("/api/v1/auth/login/", login, format="json").status_code == 200


def test_only_administrators_of_the_school(w):
    for member in (w.guardian_member, member_with_role(w.school, "TEACHER"), member_with_role(w.school, "PARENT")):
        assert as_(member).get(GUARDIANS).status_code == 403
        assert as_(member).post(GUARDIANS, {}, format="json").status_code == 403
    other_admin = member_with_role(SchoolFactory(), "ADMIN")
    assert data(as_(other_admin).get(GUARDIANS)) == []
    assert as_(other_admin).get(GUARDIANS + str(w.guardian.pk) + "/").status_code == 404


def test_scans_per_guardian_and_never_another_school(w):
    token = w.qr[w.students[0].pk].token
    other = data(new_guardian(w), 201)
    from apps.people.models import GuardianProfile

    second = GuardianProfile.objects.get(pk=other["id"]).membership
    att.scan(token, actor=w.guardian_member, at=at(7, 10))
    att.scan(w.qr[w.students[1].pk].token, actor=second, at=at(7, 12))
    mine = data(as_(w.admin).get(f"/api/v1/admin/scans/?guardian={w.guardian.pk}"))
    assert [s["student_name"] for s in mine] == [w.students[0].full_name]
    assert mine[0]["guardian"] == str(w.guardian.pk) and mine[0]["scanned_by_name"]
    assert len(data(as_(w.admin).get("/api/v1/admin/scans/"))) == 2
    detail = data(as_(w.admin).get(GUARDIANS + str(w.guardian.pk) + "/"))
    assert detail["last_scan_at"] is not None
    other_admin = member_with_role(SchoolFactory(), "ADMIN")
    assert data(as_(other_admin).get(f"/api/v1/admin/scans/?guardian={w.guardian.pk}")) == []
    assert as_(w.guardian_member).get(f"/api/v1/admin/scans/?guardian={w.guardian.pk}").status_code == 403
    assert as_(w.admin).get("/api/v1/admin/scans/?guardian=pas-un-uuid").status_code == 400


def test_today_scans_are_counted(w):
    body = data(as_(w.guardian_member).post("/api/v1/qr/scans/", {"token": w.qr[w.students[0].pk].token}), 201)
    assert body["student"]["name"] == w.students[0].full_name  # a recognised pupil: one scan logged
    assert data(as_(w.admin).get(GUARDIANS + str(w.guardian.pk) + "/"))["scans_today"] == 1


def test_daily_attendance_list_by_date_and_class(w):
    att.scan(w.qr[w.students[0].pk].token, actor=w.guardian_member, at=at(7, 10))
    att.scan(w.qr[w.students[1].pk].token, actor=w.guardian_member, at=at(7, 50))  # late (after 7:30)
    rows = data(as_(w.admin).get(f"/api/v1/admin/attendance/daily/?date={MONDAY.isoformat()}"))
    by_name = {r["student_name"]: r for r in rows}
    assert by_name[w.students[0].full_name]["status"] == "PRESENT"
    assert by_name[w.students[1].full_name]["status"] == "LATE" and by_name[w.students[1].full_name]["late_minutes"] > 0
    assert {r["school_class_name"] for r in rows} == {"3e A"}
    same = data(
        as_(w.admin).get(f"/api/v1/admin/attendance/daily/?date={MONDAY.isoformat()}&school_class={w.klass.pk}")
    )
    assert {r["id"] for r in same} == {r["id"] for r in rows}
    assert as_(w.admin).get("/api/v1/admin/attendance/daily/").status_code == 400  # the date is required
    other_admin = member_with_role(SchoolFactory(), "ADMIN")
    assert data(as_(other_admin).get(f"/api/v1/admin/attendance/daily/?date={MONDAY.isoformat()}")) == []
    assert as_(w.guardian_member).get(f"/api/v1/admin/attendance/daily/?date={MONDAY.isoformat()}").status_code == 403


def test_no_amount_in_what_guardians_and_their_admin_views_return(w):
    body = data(as_(w.guardian_member).post("/api/v1/qr/scans/", {"token": w.qr[w.students[0].pk].token}), 201)
    listing = data(as_(w.admin).get(GUARDIANS))
    for payload in (body, listing, data(as_(w.admin).get("/api/v1/admin/scans/"))):
        text = str(payload).lower()
        for money in ("amount", "balance", "montant", "xaf", "due"):
            assert money not in text, (money, payload)
