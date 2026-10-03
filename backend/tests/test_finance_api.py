"""Finance API: audiences, school isolation, 403 / 404 / 409, idempotency."""

import uuid
from datetime import date

import pytest
from rest_framework.test import APIClient

from apps.finance import services as fin
from apps.finance.models import Payment

from .conftest import DB
from .factories import SchoolFactory, member_with_role
from .finance_world import make_finance_world, verified_parent, wallet_for

pytestmark = DB


@pytest.fixture
def w(school):
    return make_finance_world(school)


@pytest.fixture
def other():
    return make_finance_world(SchoolFactory())


def as_(membership):
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


def data(response, expected=200):
    assert response.status_code == expected, response.json()
    return response.json()["data"]


def error(response, expected):
    assert response.status_code == expected, response.json()
    body = response.json()
    assert body["success"] is False
    return body["error"]


def payment_body(w, amount="70000", **extra):
    return {
        "student": str(w.students[0].pk),
        "amount": amount,
        "payment_method": "WALLET",
        "wallet": str(w.wallet.pk),
        "invoices": [str(w.inv1.pk), str(w.inv2.pk)],
        **extra,
    }


def post_payment(client, body, key=None):
    return client.post("/api/v1/finance/payments/", body, format="json", HTTP_IDEMPOTENCY_KEY=key or str(uuid.uuid4()))


# =============================================================================
# Obligations / invoices
# =============================================================================


def test_parent_sees_obligations_of_their_child(w):
    body = data(as_(w.parent).get(f"/api/v1/finance/students/{w.students[0].pk}/obligations/"))
    assert (body["balance_due"], body["solvency"], body["can_pay"]) == ("100000.00", "OVERDUE", True)
    assert [i["invoice_number"] for i in body["open_invoices"]] == ["F25-000001", "F25-000002"]
    assert body["open_invoices"][0]["total_amount"] == "60000.00"  # strings, never floats


def test_obligations_403_404(w, other):
    url = f"/api/v1/finance/students/{w.students[0].pk}/obligations/"
    no_finance_right = verified_parent(w, w.students[0], can_pay=False, can_view=False)
    assert error(as_(no_finance_right).get(url), 403)["code"] == "PERMISSION_DENIED"
    for stranger in (member_with_role(w.school, "PARENT"), w.tm_member, member_with_role(w.school, "STAFF")):
        assert error(as_(stranger).get(url), 404)["code"] == "NOT_FOUND"
    # Valid id of school A asked from school B, even by its admin: 404.
    assert error(as_(other.admin).get(url), 404)["code"] == "NOT_FOUND"
    assert error(as_(other.parent).get(url), 404)["code"] == "NOT_FOUND"


def test_invoice_visibility(w, other):
    assert len(data(as_(w.admin).get("/api/v1/finance/invoices/"))) == 2
    assert len(data(as_(w.parent).get("/api/v1/finance/invoices/"))) == 2
    for nobody in (w.tm_member, member_with_role(w.school, "STAFF"), verified_parent(w, w.students[1])):
        assert data(as_(nobody).get("/api/v1/finance/invoices/")) == []
    viewer_only = verified_parent(w, w.students[0], can_pay=True, can_view=False)
    assert data(as_(viewer_only).get("/api/v1/finance/invoices/")) == []
    assert error(as_(other.admin).get(f"/api/v1/finance/invoices/{w.inv1.pk}/"), 404)["code"] == "NOT_FOUND"
    assert data(as_(w.parent).get(f"/api/v1/finance/invoices/{w.inv1.pk}/"))["lines"][0]["total"] == "60000.00"


def test_admin_issues_and_cancels_invoices(w):
    admin = as_(w.admin)
    created = data(
        admin.post(
            "/api/v1/admin/finance/invoices/",
            {
                "student": str(w.students[1].pk),
                "due_date": "2026-02-01",
                "lines": [{"fee_type": str(w.tuition.pk), "unit_price": "12500", "quantity": "2"}],
            },
            format="json",
        ),
        201,
    )
    assert (created["total_amount"], created["status"]) == ("25000.00", "ISSUED")
    cancelled = data(admin.post(f"/api/v1/admin/finance/invoices/{created['id']}/cancel/", {"reason": "Erreur"}), 200)
    assert cancelled["status"] == "CANCELLED"
    fin.initiate_payment(
        w.students[0],
        actor=w.parent,
        amount="1000",
        payment_method="WALLET",
        idempotency_key="k1",
        wallet=w.wallet,
        invoices=[w.inv1],
    )
    err = error(admin.post(f"/api/v1/admin/finance/invoices/{w.inv1.pk}/cancel/", {"reason": "x"}), 409)
    assert (err["code"], err["details"]["rule"]) == ("CONFLICT", "invoice_has_payments")
    assert error(as_(w.parent).post("/api/v1/admin/finance/invoices/", {}, format="json"), 403)["code"] == (
        "PERMISSION_DENIED"
    )


# =============================================================================
# Payments
# =============================================================================


def test_parent_pays_and_reads_the_result(w):
    client = as_(w.parent)
    body = data(post_payment(client, payment_body(w)), 201)
    assert (body["status"], body["amount"], body["replayed"]) == ("SUCCEEDED", "70000.00", False)
    assert len(body["allocations"]) == 2
    detail = data(client.get(f"/api/v1/finance/payments/{body['id']}/"))
    assert (detail["payment_reference"], detail["refunds"]) == (body["payment_reference"], [])
    assert [p["id"] for p in data(client.get("/api/v1/finance/payments/"))] == [body["id"]]
    wallets = data(client.get("/api/v1/finance/wallets/"))
    assert [(x["id"], x["balance"]) for x in wallets] == [(str(w.wallet.pk), "80000.00")]


def test_failed_payment_is_a_201_result(w):
    poor = wallet_for(w, w.parent, balance="100", identifier="699100001")
    body = data(post_payment(as_(w.parent), payment_body(w, wallet=str(poor.pk))), 201)
    assert (body["status"], body["allocations"]) == ("INSUFFICIENT_FUNDS", [])
    timeout = wallet_for(w, w.parent, behavior="TIMEOUT", identifier="699100002")
    assert data(post_payment(as_(w.parent), payment_body(w, wallet=str(timeout.pk))), 201)["status"] == "TIMEOUT"


def test_idempotency_over_http(w):
    client, key = as_(w.parent), str(uuid.uuid4())
    first = data(post_payment(client, payment_body(w), key), 201)
    replay = data(post_payment(client, payment_body(w), key), 200)
    assert (replay["id"], replay["replayed"]) == (first["id"], True)
    err = error(post_payment(client, payment_body(w, amount="1"), key), 409)
    assert (err["code"], err["details"]["rule"]) == ("CONFLICT", "idempotency_conflict")
    # Body field works as well; no key at all is a 400.
    no_key = client.post("/api/v1/finance/payments/", payment_body(w, amount="10"), format="json")
    assert error(no_key, 400)["code"] == "VALIDATION_ERROR"
    assert Payment.objects.count() == 1


def test_payment_permissions_and_isolation(w, other):
    teacher_wallet = wallet_for(w, w.tm_member, identifier="699100003")
    err = error(post_payment(as_(w.tm_member), payment_body(w, wallet=str(teacher_wallet.pk))), 403)
    assert err["code"] == "PERMISSION_DENIED"
    # Another parent's wallet: 403; a wallet / invoice / student of another school: 404.
    second = verified_parent(w, w.students[0])
    assert error(post_payment(as_(second), payment_body(w)), 403)["code"] == "PERMISSION_DENIED"
    assert error(post_payment(as_(w.parent), payment_body(w, wallet=str(other.wallet.pk))), 404)["code"] == (
        "NOT_FOUND"
    )
    assert error(post_payment(as_(w.parent), payment_body(w, invoices=[str(other.inv1.pk)])), 404)["code"] == (
        "NOT_FOUND"
    )
    assert (
        error(post_payment(as_(other.admin), payment_body(w, payment_method="CASH", wallet=None)), 404)["code"]
        == "NOT_FOUND"
    )
    assert not Payment.objects.exists()


def test_payment_history_visibility(w, other):
    paid = data(post_payment(as_(w.parent), payment_body(w, amount="1000")), 201)
    payer_only = verified_parent(w, w.students[0], can_pay=True, can_view=False)
    mine = data(
        post_payment(
            as_(payer_only),
            payment_body(w, amount="500", wallet=str(wallet_for(w, payer_only, identifier="699100004").pk)),
        ),
        201,
    )
    # A payer without the "view" right sees only what they paid.
    assert [p["id"] for p in data(as_(payer_only).get("/api/v1/finance/payments/"))] == [mine["id"]]
    assert {p["id"] for p in data(as_(w.parent).get("/api/v1/finance/payments/"))} == {
        paid["id"],
        mine["id"],
    }
    assert data(as_(w.tm_member).get("/api/v1/finance/payments/")) == []
    assert error(as_(w.tm_member).get(f"/api/v1/finance/payments/{paid['id']}/"), 404)["code"] == "NOT_FOUND"
    assert error(as_(other.admin).get(f"/api/v1/finance/payments/{paid['id']}/"), 404)["code"] == "NOT_FOUND"
    assert data(as_(other.admin).get("/api/v1/finance/payments/")) == []
    filtered = data(as_(w.admin).get("/api/v1/finance/payments/?status=SUCCEEDED"))
    assert len(filtered) == 2


def test_refund_endpoint(w, other):
    paid = data(post_payment(as_(w.parent), payment_body(w)), 201)
    url = f"/api/v1/admin/finance/payments/{paid['id']}/refund/"
    assert error(as_(w.parent).post(url, {"amount": "10", "reason": "x"}), 403)["code"] == "PERMISSION_DENIED"
    assert error(as_(other.admin).post(url, {"amount": "10", "reason": "x"}), 404)["code"] == "NOT_FOUND"
    refund = data(as_(w.admin).post(url, {"amount": "20000", "reason": "Trop-perçu"}), 201)
    assert (refund["payment"], refund["amount"]) == (paid["id"], "20000.00")
    err = error(as_(w.admin).post(url, {"amount": "50000.01", "reason": "x"}), 409)
    assert err["details"]["rule"] == "refund_exceeds_payment"
    detail = data(as_(w.parent).get(f"/api/v1/finance/payments/{paid['id']}/"))
    assert (detail["status"], detail["refunded_amount"], len(detail["refunds"])) == (
        "PARTIALLY_REFUNDED",
        "20000.00",
        1,
    )


# =============================================================================
# Administration
# =============================================================================


def test_admin_configuration_wallets_treasury_dashboard(w):
    admin = as_(w.admin)
    fee = data(admin.post("/api/v1/admin/finance/fee-types/", {"code": "exam", "name": "Examen"}), 201)
    assert fee["code"] == "EXAM"
    dup = error(admin.post("/api/v1/admin/finance/fee-types/", {"code": "EXAM", "name": "Bis"}), 409)
    assert dup["details"]["rule"] == "duplicate_code"
    schedule = data(
        admin.post(
            "/api/v1/admin/finance/fee-schedules/",
            {
                "fee_type": fee["id"],
                "academic_year": str(w.year.pk),
                "school_class": str(w.klass.pk),
                "amount": "5000",
                "due_date": str(date(2026, 3, 1)),
            },
            format="json",
        ),
        201,
    )
    assert schedule["amount"] == "5000.00"
    generated = data(admin.post("/api/v1/admin/finance/invoices/generate/", {"school_class": str(w.klass.pk)}), 201)
    assert generated["created"] == 3

    wallet = data(
        admin.post(
            "/api/v1/admin/finance/wallets/",
            {
                "owner": str(w.parent.pk),
                "provider_code": "FAKE_MTN",
                "wallet_identifier": "677000000",
            },
        ),
        201,
    )
    assert (
        data(admin.post(f"/api/v1/admin/finance/wallets/{wallet['id']}/fund/", {"amount": "999.50"}), 201)["balance"]
        == "999.50"
    )
    assert data(admin.post("/api/v1/admin/finance/treasury/credit/", {"amount": "10"}), 201)["balance"] == "10.00"
    treasury = data(admin.get("/api/v1/admin/finance/treasury/"))
    assert treasury["balance"] == "10.00" and len(treasury["recent_transactions"]) == 1

    post_payment(as_(w.parent), payment_body(w, amount="60000", invoices=[str(w.inv1.pk)]))
    dash = data(admin.get("/api/v1/admin/finance/dashboard/"))
    assert (dash["collected"], dash["treasury_balance"], dash["payments_by_status"]) == (
        "60000.00",
        "60010.00",
        {"SUCCEEDED": 1},
    )
    for path in ("dashboard/", "treasury/", "wallets/", "fee-types/"):
        assert error(as_(w.parent).get(f"/api/v1/admin/finance/{path}"), 403)["code"] == "PERMISSION_DENIED"


def test_admin_cannot_reach_another_school_objects(w, other):
    admin = as_(w.admin)
    assert (
        error(admin.post(f"/api/v1/admin/finance/wallets/{other.wallet.pk}/fund/", {"amount": "1"}), 404)["code"]
        == "NOT_FOUND"
    )
    assert (
        error(
            admin.post(
                "/api/v1/admin/finance/wallets/",
                {
                    "owner": str(other.parent.pk),
                    "provider_code": "X",
                    "wallet_identifier": "1",
                },
            ),
            404,
        )["code"]
        == "NOT_FOUND"
    )
    assert {i["id"] for i in data(admin.get("/api/v1/finance/invoices/"))} == {
        str(w.inv1.pk),
        str(w.inv2.pk),
    }
    assert len(data(admin.get("/api/v1/admin/finance/wallets/"))) == 1


def test_qr_scan_reports_solvency_without_amounts(w):
    from apps.attendance import services as att
    from apps.people import services as people

    guardian_member = member_with_role(w.school, "GUARDIAN")
    people.create_guardian(guardian_member, guardian_number="G-1")
    token = att.issue_qr_code(w.students[0], actor=w.admin).token
    body = data(as_(guardian_member).post("/api/v1/qr/scans/", {"token": token}, format="json"), 201)
    assert body["solvency"] == "OVERDUE" and "60000" not in str(body)
