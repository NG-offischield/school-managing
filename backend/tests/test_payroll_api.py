"""Payroll API: admin workflow, employees see only their own approved pay,
403 / 404 / 409, school isolation; QR solvency visibility by role."""

from datetime import date

import pytest
from rest_framework.test import APIClient

from apps.attendance import services as att
from apps.finance import services as fin
from apps.payroll import services as pay
from apps.payroll.models import StaffPayroll, TeacherPayroll
from apps.people import services as people

from .conftest import DB
from .factories import SchoolFactory, member_with_role
from .payroll_world import make_payroll_world, make_staff

pytestmark = DB


@pytest.fixture
def w(school):
    return make_payroll_world(school)


@pytest.fixture
def other():
    return make_payroll_world(SchoolFactory())


def as_(membership):
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


def data(response, expected=200):
    assert response.status_code == expected, response.json()
    return response.json()["data"]


def error(response, expected):
    assert response.status_code == expected, response.json()
    return response.json()["error"]


def prepared(w, *sessions):
    for s in sessions or w.sessions[:2]:
        pay.validate_session(s, actor=w.admin)
    pay.calculate_period(w.october, actor=w.admin)
    return TeacherPayroll.objects.get(teacher=w.tm, payroll_period=w.october)


# =============================================================================
# Administration workflow
# =============================================================================


def test_full_admin_workflow_over_http(w):
    admin = as_(w.admin)
    for s in w.sessions[:2]:
        body = data(admin.post(f"/api/v1/admin/sessions/{s.pk}/validate/", {}), 200)
        assert body["verified_status"] == "VALIDATED"
    summary = data(admin.post("/api/v1/admin/payroll/calculate/", {"period": str(w.october.pk)}))
    assert (summary["created"], summary["warnings"]) == (2, [])
    listed = data(admin.get(f"/api/v1/admin/payroll/?period={w.october.pk}&kind=TEACHER"))
    assert [(p["status"], p["programmed_amount"], p["earned_amount"]) for p in listed] == [
        ("CALCULATED", "15000.00", "10000.00")
    ]
    pid = listed[0]["id"]
    detail = data(admin.get(f"/api/v1/admin/payroll/{pid}/"))
    assert detail["reconstructible"] is True
    assert {line["kind"] for line in detail["lines"]} == {"PROGRAMMED", "EARNED"}
    assert data(admin.post(f"/api/v1/admin/payroll/{pid}/approve/"))["approved_amount"] == "10000.00"
    paid = data(admin.post(f"/api/v1/admin/payroll/{pid}/pay/", {"payout_method": "CASH"}))
    assert paid["status"] == "PAID" and paid["payment_reference"].startswith("PAYR-")
    err = error(admin.post(f"/api/v1/admin/payroll/{pid}/pay/", {"payout_method": "CASH"}), 409)
    assert (err["code"], err["details"]["rule"]) == ("CONFLICT", "payroll_already_paid")
    staff_id = data(admin.get("/api/v1/admin/payroll/?kind=STAFF"))[0]["id"]
    data(admin.post(f"/api/v1/admin/payroll/{staff_id}/cancel/", {"reason": "versé à part"}))
    closed = data(admin.post(f"/api/v1/admin/payroll/periods/{w.october.pk}/close/"))
    assert closed["status"] == "CLOSED"
    err = error(admin.post("/api/v1/admin/payroll/calculate/", {"period": str(w.october.pk)}), 409)
    assert err["details"]["rule"] == "period_closed"


def test_admin_configuration_endpoints(w):
    admin = as_(w.admin)
    period = data(
        admin.post(
            "/api/v1/admin/payroll/periods/",
            {
                "academic_year": str(w.year.pk),
                "name": "Décembre 2025",
                "start_date": "2025-12-01",
                "end_date": "2025-12-31",
            },
        ),
        201,
    )
    assert period["status"] == "OPEN"
    overlap = error(
        admin.post(
            "/api/v1/admin/payroll/periods/",
            {
                "academic_year": str(w.year.pk),
                "name": "X",
                "start_date": "2025-12-15",
                "end_date": "2026-01-15",
            },
        ),
        409,
    )
    assert overlap["details"]["rule"] == "period_overlap"
    rate = data(
        admin.post(
            "/api/v1/admin/payroll/teacher-rates/",
            {
                "teacher": str(w.tf.pk),
                "academic_year": str(w.year.pk),
                "vacation_rate": "4500.50",
                "effective_from": "2025-09-01",
            },
        ),
        201,
    )
    assert (rate["vacation_rate"], rate["vacation_minutes"]) == ("4500.50", 120)
    salary = data(
        admin.post(
            "/api/v1/admin/payroll/staff-salaries/",
            {
                "staff": str(make_staff(w, "ST-02").pk),
                "monthly_salary": "90000",
                "effective_from": "2025-09-01",
            },
        ),
        201,
    )
    assert salary["monthly_salary"] == "90000.00"
    adjustment = data(
        admin.post(
            "/api/v1/admin/payroll/adjustments/",
            {
                "employee": str(w.staff.employee.pk),
                "amount": "-2500",
                "reason": "Avance sur salaire",
            },
        ),
        201,
    )
    assert (adjustment["amount"], adjustment["source"]) == ("-2500.00", "MANUAL")
    remuneration = data(
        admin.get(
            f"/api/v1/admin/payroll/remuneration/?employee={w.tm.employee.pk}&date_from=2025-10-01&date_to=2025-10-31"
        )
    )
    assert remuneration["programmed_amount"] == "15000.00"
    pay.self_check_in(w.sessions[0], actor=w.tm_member, status="PRESENT")
    pending = data(admin.get("/api/v1/admin/payroll/check-ins/?status=PENDING"))
    assert [c["teaching_session"] for c in pending] == [str(w.sessions[0].pk)]


def test_validation_endpoints_409_and_reasons(w):
    admin = as_(w.admin)
    cancelled = w.sessions[3]
    err = error(admin.post(f"/api/v1/admin/sessions/{cancelled.pk}/validate/", {}), 409)
    assert err["details"]["rule"] == "session_cancelled"
    assert error(admin.post(f"/api/v1/admin/sessions/{w.sessions[0].pk}/reject/", {}), 400)["code"] == (
        "VALIDATION_ERROR"
    )
    rejected = data(admin.post(f"/api/v1/admin/sessions/{w.sessions[0].pk}/reject/", {"reason": "Absent"}))
    assert (rejected["verified_status"], rejected["verification_reason"]) == ("REJECTED", "Absent")


def test_stale_payroll_answers_409(w):
    payroll = prepared(w, w.sessions[0])
    pay.validate_session(w.sessions[1], actor=w.admin)
    err = error(as_(w.admin).post(f"/api/v1/admin/payroll/{payroll.pk}/approve/"), 409)
    assert err["details"]["rule"] == "payroll_stale"


# =============================================================================
# Rights and isolation
# =============================================================================


def test_non_admins_cannot_use_admin_endpoints(w):
    payroll = prepared(w)
    for member in (w.tm_member, w.staff.employee.membership, member_with_role(w.school, "PARENT")):
        client = as_(member)
        for method, url, body in (
            ("post", "/api/v1/admin/payroll/calculate/", {"period": str(w.october.pk)}),
            ("get", "/api/v1/admin/payroll/", None),
            ("post", f"/api/v1/admin/payroll/{payroll.pk}/approve/", None),
            ("post", f"/api/v1/admin/sessions/{w.sessions[2].pk}/validate/", {}),
            ("get", "/api/v1/admin/payroll/adjustments/", None),
        ):
            assert error(getattr(client, method)(url, body), 403)["code"] == "PERMISSION_DENIED"


def test_admin_of_another_school_gets_404(w, other):
    payroll = prepared(w)
    client = as_(other.admin)
    assert error(client.get(f"/api/v1/admin/payroll/{payroll.pk}/"), 404)["code"] == "NOT_FOUND"
    assert error(client.post(f"/api/v1/admin/payroll/{payroll.pk}/approve/"), 404)["code"] == "NOT_FOUND"
    assert error(client.post(f"/api/v1/admin/sessions/{w.sessions[2].pk}/validate/", {}), 404)["code"] == ("NOT_FOUND")
    assert error(client.post("/api/v1/admin/payroll/calculate/", {"period": str(w.october.pk)}), 404)["code"] == (
        "NOT_FOUND"
    )
    assert (
        error(
            client.post(
                "/api/v1/admin/payroll/teacher-rates/",
                {
                    "teacher": str(w.tm.pk),
                    "academic_year": str(other.year.pk),
                    "vacation_rate": "1",
                    "effective_from": "2025-12-01",
                },
            ),
            404,
        )["code"]
        == "NOT_FOUND"
    )
    assert data(client.get("/api/v1/admin/payroll/")) == []


def test_employees_see_only_their_own_approved_remuneration(w):
    payroll = prepared(w)
    teacher = as_(w.tm_member)
    # Prepared (CALCULATED) payroll: internal to the administration.
    assert data(teacher.get("/api/v1/payroll/me/")) == []
    assert error(teacher.get(f"/api/v1/payroll/me/{payroll.pk}/"), 404)["code"] == "NOT_FOUND"
    pay.approve_payroll(payroll, actor=w.admin)
    mine = data(teacher.get("/api/v1/payroll/me/"))
    assert [(p["id"], p["status"], p["approved_amount"]) for p in mine] == [(str(payroll.pk), "APPROVED", "10000.00")]
    detail = data(teacher.get(f"/api/v1/payroll/me/{payroll.pk}/"))
    assert sorted(line["kind"] for line in detail["lines"]) == [
        "EARNED",
        "EARNED",
        "PROGRAMMED",
        "PROGRAMMED",
        "PROGRAMMED",
    ]
    summary = data(teacher.get("/api/v1/teacher/payroll/?date_from=2025-10-01&date_to=2025-10-31"))
    assert summary["live"]["programmed_amount"] == "15000.00" and len(summary["payrolls"]) == 1
    # Another teacher, the staff member, a parent: nothing of it.
    for stranger in (w.tf_member, w.staff.employee.membership, member_with_role(w.school, "PARENT")):
        assert data(as_(stranger).get("/api/v1/payroll/me/")) == []
        assert error(as_(stranger).get(f"/api/v1/payroll/me/{payroll.pk}/"), 404)["code"] == "NOT_FOUND"
    assert error(as_(w.staff.employee.membership).get("/api/v1/teacher/payroll/"), 403)["code"] == ("PERMISSION_DENIED")


def test_staff_sees_own_paid_salary(w):
    pay.calculate_period(w.october, actor=w.admin)
    staff_payroll = StaffPayroll.objects.get(staff=w.staff)
    pay.approve_payroll(staff_payroll, actor=w.admin)
    pay.pay_payroll(staff_payroll, actor=w.admin, payout_method="CASH")
    mine = data(as_(w.staff.employee.membership).get("/api/v1/payroll/me/"))
    assert [(p["kind"], p["status"], p["gross_amount"]) for p in mine] == [("STAFF", "PAID", "150000.00")]
    assert data(as_(w.tm_member).get("/api/v1/payroll/me/")) == []


def test_teacher_self_check_in(w):
    teacher = as_(w.tm_member)
    body = data(teacher.post(f"/api/v1/teacher/sessions/{w.sessions[0].pk}/check-in/", {"status": "PRESENT"}), 201)
    assert (body["self_reported_status"], body["verified_status"]) == ("PRESENT", "PENDING")
    # Someone else's session: 404; a self-report does not make it payable.
    assert (
        error(
            as_(w.tf_member).post(f"/api/v1/teacher/sessions/{w.sessions[1].pk}/check-in/", {"status": "PRESENT"}), 404
        )["code"]
        == "NOT_FOUND"
    )
    pay.calculate_period(w.october, actor=w.admin)
    assert TeacherPayroll.objects.get(teacher=w.tm).earned_amount == 0


# =============================================================================
# QR scan: financial status only for authorized roles, never amounts
# =============================================================================


def test_qr_solvency_only_for_authorized_scanners_and_without_amounts(w):
    student = w.students[0]
    tuition = fin.create_fee_type(w.school, actor=w.admin, code="TUI", name="Scolarité")
    fin.issue_invoice(
        student, actor=w.admin, due_date=date(2025, 10, 1), lines=[{"fee_type": tuition, "unit_price": "75000"}]
    )
    token = att.issue_qr_code(student, actor=w.admin).token
    guardian = member_with_role(w.school, "GUARDIAN")
    people.create_guardian(guardian, guardian_number="G-1")
    staff_scanner = w.staff.employee.membership
    seen = {}
    for name, member in (("guardian", guardian), ("admin", w.admin), ("staff", staff_scanner)):
        body = data(as_(member).post("/api/v1/qr/scans/", {"token": token}, format="json"), 201)
        assert body["student"]["id"] == str(student.pk)
        assert "75000" not in str(body) and "balance" not in str(body)
        seen[name] = body["solvency"]
    assert seen == {"guardian": "OVERDUE", "admin": "OVERDUE", "staff": None}
    # Non-scanners cannot even reach the endpoint.
    for member in (w.tm_member, member_with_role(w.school, "PARENT")):
        assert error(as_(member).post("/api/v1/qr/scans/", {"token": token}, format="json"), 403)["code"] == (
            "PERMISSION_DENIED"
        )
