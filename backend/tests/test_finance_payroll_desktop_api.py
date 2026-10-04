"""Read-side additions for the desktop finance / payroll screens (ADR 0022):
list filters, the refunds list, the wallet owner's name, the teacher's
employee id, payrolls per employee and check-ins per teacher. Visibility and
isolation are unchanged: the filters only narrow what the caller already sees."""

import uuid

import pytest
from rest_framework.test import APIClient

from apps.finance import services as fin
from apps.payroll import services as pay

from .conftest import DB
from .factories import SchoolFactory
from .finance_world import make_finance_world
from .payroll_world import make_payroll_world

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
    return make_finance_world(school)


def cash(w, student, amount, invoices=()):
    return fin.initiate_payment(
        student,
        actor=w.admin,
        amount=amount,
        payment_method="CASH",
        idempotency_key=str(uuid.uuid4()),
        invoices=list(invoices),
        fee_type=None if invoices else w.tuition,
    ).payment


def test_payment_and_invoice_filters_search_dates_method(w):
    s0 = w.students[0]
    by_cash = cash(w, s0, "60000", [w.inv1])
    by_wallet = fin.initiate_payment(
        s0,
        actor=w.parent,
        amount="10000",
        payment_method="WALLET",
        wallet=w.wallet,
        idempotency_key=str(uuid.uuid4()),
        invoices=[w.inv2],
    ).payment
    admin = as_(w.admin)
    url = "/api/v1/finance/payments/"
    refs = lambda **params: {p["payment_reference"] for p in rows(admin.get(url, params))}  # noqa: E731
    assert refs() == {by_cash.payment_reference, by_wallet.payment_reference}
    assert refs(payment_method="CASH") == {by_cash.payment_reference}
    assert refs(search=by_wallet.payment_reference[-6:].lower()) == {by_wallet.payment_reference}
    assert refs(search=s0.last_name.upper()) == {by_cash.payment_reference, by_wallet.payment_reference}
    assert refs(search="personne-inconnue") == set()
    today = by_cash.initiated_at.date()
    assert len(refs(date_from=today.isoformat(), date_to=today.isoformat())) == 2
    assert refs(date_to="2000-01-01") == set()
    assert as_(w.admin).get(url, {"date_from": "pas-une-date"}).status_code == 400
    invoices = "/api/v1/finance/invoices/"
    numbers = lambda **params: [i["invoice_number"] for i in rows(admin.get(invoices, params))]  # noqa: E731
    assert numbers(search=w.inv2.invoice_number) == [w.inv2.invoice_number]
    assert numbers(date_from="2100-01-01") == []
    # A parent's search never widens what they see: another child's payment stays hidden.
    cash(w, w.students[1], "5000")
    seen = rows(as_(w.parent).get(url, {"search": w.students[1].last_name}))
    assert {p["student"] for p in seen} <= {str(s0.pk)}


def test_refunds_list_wallet_owner_and_isolation(w):
    payment = cash(w, w.students[0], "60000", [w.inv1])
    fin.refund_payment(payment, actor=w.admin, amount="20000", reason="Trop perçu")
    refunds = rows(as_(w.admin).get("/api/v1/admin/finance/refunds/"))
    assert [(r["payment_reference"], r["amount"], r["payment_amount"], r["reason"]) for r in refunds] == [
        (payment.payment_reference, "20000.00", "60000.00", "Trop perçu")
    ]
    assert refunds[0]["student_name"] == w.students[0].full_name
    assert rows(as_(w.admin).get("/api/v1/admin/finance/refunds/", {"search": "rien"})) == []
    wallets = rows(as_(w.admin).get("/api/v1/admin/finance/wallets/"))
    assert wallets[0]["owner_name"] == w.parent.user.full_name
    # Another school's admin sees none of it; parents / teachers are refused.
    other = make_finance_world(SchoolFactory())
    assert rows(as_(other.admin).get("/api/v1/admin/finance/refunds/")) == []
    assert as_(w.parent).get("/api/v1/admin/finance/refunds/").status_code == 403


def test_payrolls_per_employee_checkins_per_teacher_and_teacher_employee_id(school):
    w = make_payroll_world(school)
    pay.calculate_period(w.october, actor=w.admin)
    admin = as_(w.admin)
    teacher = rows(admin.get(f"/api/v1/teachers/{w.tm.pk}/"))
    assert teacher["employee"] == str(w.tm.employee_id)
    mine = rows(admin.get("/api/v1/admin/payroll/", {"employee": teacher["employee"]}))
    assert mine and {p["employee"] for p in mine} == {teacher["employee"]}
    everyone = rows(admin.get("/api/v1/admin/payroll/"))
    assert len(everyone) > len(mine)  # the staff member's payroll too
    assert rows(admin.get("/api/v1/admin/payroll/", {"employee": str(uuid.uuid4())})) == []
    assert admin.get("/api/v1/admin/payroll/", {"employee": "x"}).status_code == 400
    assert rows(admin.get("/api/v1/admin/payroll/check-ins/", {"teacher": str(w.tf.pk)})) == []
    other = make_payroll_world(SchoolFactory())
    assert rows(as_(other.admin).get("/api/v1/admin/payroll/", {"employee": teacher["employee"]})) == []
