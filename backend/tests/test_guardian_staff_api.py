"""The API contract of the guardian and staff apps (ADR 0027): each one
sees only what the server allows for ITS role, in ITS school.

- guardian: own scans only; the scan answer carries the solvency status
  (never an amount); no pupil record, grades, finance, payroll or staff list;
- staff: own staff record and functions, own approved / paid payrolls, the
  school's planning; scans WITHOUT solvency;
- everyone: another school is invisible; a suspended account, an inactive
  guardian or an invalid token get nothing."""

from datetime import date

import pytest
from rest_framework.test import APIClient

from apps.attendance import services as att
from apps.finance import services as fin
from apps.payroll import services as pay
from apps.payroll.models import StaffPayroll
from apps.people import services as people
from apps.people.models import StaffFunction

from .conftest import DB
from .factories import SchoolFactory, member_with_role
from .payroll_world import MONDAY, at, make_payroll_world, make_staff

pytestmark = DB


@pytest.fixture
def w(school):
    w = make_payroll_world(school)
    w.guardian = member_with_role(school, "GUARDIAN")
    people.create_guardian(w.guardian, guardian_number="G-1")
    w.other_guardian = member_with_role(school, "GUARDIAN")
    people.create_guardian(w.other_guardian, guardian_number="G-2")
    w.staff_member = w.staff.employee.membership
    w.qr = {s.pk: att.issue_qr_code(s, actor=w.admin) for s in w.students}
    return w


def as_(membership):
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


def data(response, expected=200):
    assert response.status_code == expected, response.json()
    return response.json()["data"]


def ids(response):
    return {row["id"] for row in data(response)}


def scan(w, student, actor, hour=7):
    return att.scan(w.qr[student.pk].token, actor=actor, at=at(hour)).scan


# =============================================================================
# Guardian
# =============================================================================


def test_guardian_sees_only_own_scans(w):
    mine = scan(w, w.students[0], w.guardian)
    other_guardian = scan(w, w.students[1], w.other_guardian)
    by_staff = scan(w, w.students[2], w.staff_member)
    seen = ids(as_(w.guardian).get(f"/api/v1/guardians/scans/?date={MONDAY}"))
    assert seen == {str(mine.pk)}
    assert ids(as_(w.other_guardian).get(f"/api/v1/guardians/scans/?date={MONDAY}")) == {str(other_guardian.pk)}
    assert ids(as_(w.staff_member).get(f"/api/v1/guardians/scans/?date={MONDAY}")) == {str(by_staff.pk)}
    # Another school's guardian sees none of them.
    foreign = member_with_role(SchoolFactory(), "GUARDIAN")
    assert ids(as_(foreign).get(f"/api/v1/guardians/scans/?date={MONDAY}")) == set()


def test_scan_answer_depends_on_the_role(w):
    student = w.students[0]
    tuition = fin.create_fee_type(w.school, actor=w.admin, code="TUI", name="Scolarité")
    fin.issue_invoice(
        student, actor=w.admin, due_date=date(2025, 10, 1), lines=[{"fee_type": tuition, "unit_price": "75000"}]
    )
    token = w.qr[student.pk].token
    guardian = data(as_(w.guardian).post("/api/v1/qr/scans/", {"token": token}, format="json"), 201)
    staff = data(as_(w.staff_member).post("/api/v1/qr/scans/", {"token": token}, format="json"), 201)
    assert guardian["solvency"] == "OVERDUE" and staff["solvency"] is None
    for body in (guardian, staff):
        assert "75000" not in str(body) and "balance" not in str(body) and body["student"]["id"] == str(student.pk)
    for member in (w.tm_member, member_with_role(w.school, "PARENT")):
        assert as_(member).post("/api/v1/qr/scans/", {"token": token}, format="json").status_code == 403


def test_guardian_reaches_no_pupil_record_finance_or_payroll(w):
    child = w.students[0]
    client = as_(w.guardian)
    for url in (
        f"/api/v1/students/{child.pk}/",
        f"/api/v1/students/{child.pk}/attendance/",
        f"/api/v1/students/{child.pk}/sessions/",
        f"/api/v1/finance/students/{child.pk}/obligations/",
    ):
        assert client.get(url).status_code in (403, 404), url
    for url in ("/api/v1/staff/", "/api/v1/payroll/me/", "/api/v1/report-cards/", "/api/v1/finance/invoices/"):
        assert data(client.get(url)) == [], url
    for url in ("/api/v1/admin/scans/", "/api/v1/admin/payroll/", "/api/v1/admin/registrations/"):
        assert client.get(url).status_code == 403, url


def test_inactive_guardian_or_suspended_accounts_get_nothing(w):
    token = w.qr[w.students[0].pk].token
    profile = w.guardian.guardian_profile
    profile.status = "SUSPENDED"
    profile.save(update_fields=["status"])
    assert as_(w.guardian).post("/api/v1/qr/scans/", {"token": token}, format="json").status_code == 403
    for member in (w.other_guardian, w.staff_member):
        member.status = "SUSPENDED"
        member.save(update_fields=["status"])
        response = as_(member).get("/api/v1/guardians/scans/")
        assert response.status_code == 403 and response.json()["error"]["code"] == "NO_ACTIVE_MEMBERSHIP"


def test_invalid_token_is_refused(w):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer not-a-token")
    for url in ("/api/v1/guardians/scans/", "/api/v1/staff/", "/api/v1/payroll/me/"):
        assert client.get(url).status_code == 401


def test_communication_allowed_to_each_role(w):
    """Spec §8: guardians have no messaging; staff write to the administration;
    complaints are filed by parents (about their child) and teachers only."""
    body = {"conversation_type": "ADMINISTRATION", "body": "Bonjour", "client_id": "c-1"}
    assert as_(w.guardian).post("/api/v1/conversations/", body, format="json").status_code == 403
    created = data(as_(w.staff_member).post("/api/v1/conversations/", body, format="json"), 201)
    assert created["conversation_type"] == "ADMINISTRATION"
    assert ids(as_(w.staff_member).get("/api/v1/conversations/")) == {created["id"]}
    assert data(as_(w.guardian).get("/api/v1/conversations/")) == []
    complaint = {"category": "OTHER", "subject": "Portail", "description": "Lampe en panne", "submit": True}
    for member in (w.guardian, w.staff_member):
        assert as_(member).post("/api/v1/complaints/", complaint, format="json").status_code == 403
    # Notifications are readable by everyone, each their own.
    for member in (w.guardian, w.staff_member):
        assert as_(member).get("/api/v1/notifications/unread-count/").status_code == 200


# =============================================================================
# Staff
# =============================================================================


def test_staff_sees_only_own_record_with_function_names(w):
    function = StaffFunction.objects.create(school=w.school, code="BURSAR", name="Économe")
    people.assign_staff_function(w.staff, function, actor=w.admin)
    colleague = make_staff(w, number="ST-02")
    rows = data(as_(w.staff_member).get("/api/v1/staff/"))
    assert [r["id"] for r in rows] == [str(w.staff.pk)]
    assert rows[0]["function_labels"] == [{"code": "BURSAR", "name": "Économe"}]
    assert str(colleague.pk) not in str(rows)


def test_staff_sees_only_own_payrolls(w):
    colleague = make_staff(w, number="ST-02")
    pay.set_staff_salary(colleague, actor=w.admin, monthly_salary="90000", effective_from=date(2025, 9, 1))
    pay.calculate_period(w.october, actor=w.admin)
    for payroll in StaffPayroll.objects.all():
        pay.approve_payroll(payroll, actor=w.admin)
    mine = StaffPayroll.objects.get(staff=w.staff)
    theirs = StaffPayroll.objects.get(staff=colleague)
    client = as_(w.staff_member)
    assert [p["id"] for p in data(client.get("/api/v1/payroll/me/"))] == [str(mine.pk)]
    assert data(client.get(f"/api/v1/payroll/me/{mine.pk}/"))["base_salary"] == "150000.00"
    assert client.get(f"/api/v1/payroll/me/{theirs.pk}/").status_code == 404


def test_staff_reads_the_school_planning_never_another_school(w):
    other = make_payroll_world(SchoolFactory())
    mine = ids(as_(w.staff_member).get("/api/v1/sessions/?date_from=2025-10-01&date_to=2025-10-31"))
    assert {str(s.pk) for s in w.sessions} <= mine
    assert not {str(s.pk) for s in other.sessions} & mine
    assert as_(w.staff_member).get(f"/api/v1/sessions/{other.sessions[0].pk}/").status_code == 404


def test_staff_has_no_administration_rights(w):
    client = as_(w.staff_member)
    for url in ("/api/v1/admin/payroll/", "/api/v1/admin/scans/", "/api/v1/admin/link-requests/"):
        assert client.get(url).status_code == 403, url
    assert client.get(f"/api/v1/finance/students/{w.students[0].pk}/obligations/").status_code in (403, 404)
