"""Demonstration dataset (apps/demo, docs/demo-data.md): built by the domain
services, idempotent, and the five demo scenarios behave as documented."""

import io
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.core.management import CommandError, call_command

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.core.models import School
from apps.demo import dataset
from apps.demo.seed import refill_wallets, seed
from apps.documents import services as docs
from apps.finance import services as fin
from apps.finance.models import (
    Invoice,
    LedgerType,
    Payment,
    PaymentStatus,
    SimulationTreasury,
    TreasuryTransaction,
    Wallet,
    WalletTransaction,
)
from apps.people.models import ParentStudent, Student, StudentEnrollment

from .conftest import DB
from .factories import SchoolFactory, StudentFactory

pytestmark = DB
PASSWORD = "Demo-Manguiers-2026!"  # test value only: real runs inject DEMO_PASSWORD


@pytest.fixture
def w():
    return seed(password=PASSWORD)


def balance(wallet):
    wallet.refresh_from_db()
    return wallet.balance


def treasury(w):
    return SimulationTreasury.objects.get(school=w.school).balance


def pay(w, parent, invoice, *, key):
    """The parent app's request: WALLET, the invoice's balance_due, an idempotency key."""
    invoice.refresh_from_db()
    return fin.initiate_payment(
        invoice.student,
        actor=w.parents[parent],
        amount=invoice.balance_due,
        payment_method="WALLET",
        idempotency_key=key,
        wallet=w.wallets[parent],
        invoices=[invoice],
    )


# --- the dataset ------------------------------------------------------------------------


def test_school_admin_year_and_classes(w):
    assert w.school.code == "DEMO" and w.school.name == dataset.SCHOOL["name"]
    assert w.admin.user.username == "demo.admin" and w.admin.user.check_password(PASSWORD)
    assert w.year.is_current
    assert sorted(w.classes) == ["3e B", "6e A"]


def test_pupils_created_enrolled_in_their_class(w):
    assert len(w.students) == 5
    for spec in dataset.STUDENTS:
        student = Student.objects.get(school=w.school, student_number=spec["student_number"])
        assert (student.first_name, student.last_name, student.sex, str(student.date_of_birth)) == (
            spec["first_name"],
            spec["last_name"],
            spec["sex"],
            spec["date_of_birth"],
        )
        assert student.status == "ACTIVE"
        enrollment = StudentEnrollment.objects.get(student=student, academic_year=w.year)
        assert enrollment.school_class.name == spec["class"]
    # The canonical path was used: every creation is audited.
    assert AuditLog.objects.filter(school=w.school, action="STUDENT_CREATED").count() == 5


def test_parents_linked_through_the_workflow_with_the_rights(w):
    for spec in dataset.PARENTS:
        membership = w.parents[spec["key"]]
        assert membership.status == "ACTIVE" and membership.user.check_password(PASSWORD)
        children = ParentStudent.objects.filter(parent__membership=membership, identity_verified=True, active=True)
        expected = {w.students[c["student"]].pk for c in spec["children"]}
        assert {link.student_id for link in children} == expected
        assert all(link.can_pay and link.can_view_financial_data for link in children)
        assert all(fin.can_pay(membership, w.students[c["student"]]) for c in spec["children"])
    # Nobody is linked to another family's child.
    assert not fin.can_pay(w.parents["A"], w.students["S2"])


def test_invoices_statuses_and_amounts(w):
    inv = {k: Invoice.objects.get(pk=v.pk) for k, v in w.invoices.items()}
    assert inv["F-S1-TUITION"].total_amount == Decimal("75000") and inv["F-S1-TUITION"].status == "ISSUED"
    assert inv["F-S3-CANTEEN"].total_amount == Decimal("25000")
    assert inv["F-S4-EXAM"].status == "PAID" and inv["F-S4-EXAM"].balance_due == 0
    assert inv["F-S4-TRANSPORT"].status == "PARTIALLY_PAID"
    transport = inv["F-S4-TRANSPORT"]
    assert (transport.amount_paid, transport.balance_due) == (Decimal("10000"), Decimal("20000"))
    assert all(i.due_date is not None for i in inv.values())
    assert fin.solvency(w.students["S4"]) == "OVERDUE"  # transport due 5 days ago, not settled


def test_wallets_and_treasury(w):
    expected = {spec["owner"]: spec["balance"] for spec in dataset.WALLETS}
    assert {k: balance(v) for k, v in w.wallets.items()} == expected
    assert balance(w.wallets["C"]) == w.invoices["F-S3-CANTEEN"].total_amount  # Parent C: exactly the invoice
    assert all(wallet.owner == w.parents[key] for key, wallet in w.wallets.items())
    # Initial working capital + the two desk payments of the seed (15 000 + 10 000).
    assert treasury(w) == dataset.TREASURY_FUNDING + Decimal("25000")


def test_second_run_creates_no_duplicate(w):
    counts = lambda: (  # noqa: E731
        School.objects.filter(code="DEMO").count(),
        Student.objects.filter(school=w.school).count(),
        User.objects.filter(email__endswith="@demo-ecole.test").count(),
        ParentStudent.objects.filter(school=w.school).count(),
        Invoice.objects.filter(school=w.school).count(),
        Wallet.objects.filter(school=w.school).count(),
        Payment.objects.filter(school=w.school).count(),
        TreasuryTransaction.objects.filter(school=w.school).count(),
        WalletTransaction.objects.filter(school=w.school).count(),
    )
    before = counts()
    again = seed()  # no password needed: every account already exists
    assert again.created == []
    assert counts() == before
    assert treasury(again) == treasury(w)


def test_command_output_and_password_rules(w):
    out = io.StringIO()
    call_command("seed_demo", stdout=out)
    text = out.getvalue()
    assert "déjà complet" in text and "parent.a@demo-ecole.test" in text
    assert PASSWORD not in text


def test_first_run_without_password_is_refused():
    with pytest.raises(CommandError, match="DEMO_PASSWORD"):
        call_command("seed_demo", stdout=io.StringIO())
    assert not School.objects.filter(code="DEMO").exists()  # all or nothing


# --- the demo scenarios (docs/demo-data.md) --------------------------------------------------


def test_scenario_a_parent_a_pays_75000(w):
    before = treasury(w)
    outcome = pay(w, "A", w.invoices["F-S1-TUITION"], key="demo-scenario-a")
    payment = outcome.payment
    assert payment.status == PaymentStatus.SUCCEEDED
    assert balance(w.wallets["A"]) == Decimal("25000")
    assert treasury(w) == before + Decimal("75000")
    invoice = Invoice.objects.get(pk=w.invoices["F-S1-TUITION"].pk)
    assert (invoice.status, invoice.balance_due) == ("PAID", 0)
    receipt, _ = docs.generate("PAYMENT_RECEIPT", payment, actor=w.parents["A"])
    assert dict(receipt.content["fields"])["Référence"] == payment.payment_reference


def test_scenario_b_insufficient_funds_nothing_moves(w):
    before = treasury(w)
    payment = pay(w, "B", w.invoices["F-S2-TUITION"], key="demo-scenario-b").payment
    assert payment.status == PaymentStatus.INSUFFICIENT_FUNDS
    assert balance(w.wallets["B"]) == Decimal("1000")
    assert treasury(w) == before
    assert Invoice.objects.get(pk=w.invoices["F-S2-TUITION"].pk).status == "ISSUED"
    assert not Payment.objects.filter(student=w.students["S2"], status=PaymentStatus.SUCCEEDED).exists()


def test_scenario_c_exact_amount_leaves_zero(w):
    payment = pay(w, "C", w.invoices["F-S3-CANTEEN"], key="demo-scenario-c").payment
    assert payment.status == PaymentStatus.SUCCEEDED
    assert balance(w.wallets["C"]) == 0
    assert Invoice.objects.get(pk=w.invoices["F-S3-CANTEEN"].pk).status == "PAID"


def test_scenario_d_same_key_one_debit(w):
    before = treasury(w)
    first = pay(w, "A", w.invoices["F-S1-TUITION"], key="demo-scenario-d")
    invoice = w.invoices["F-S1-TUITION"]
    replay = fin.initiate_payment(
        invoice.student,
        actor=w.parents["A"],
        amount=Decimal("75000.00"),
        payment_method="WALLET",
        idempotency_key="demo-scenario-d",
        wallet=w.wallets["A"],
        invoices=[invoice],
    )
    assert replay.replayed and replay.payment.pk == first.payment.pk
    assert Payment.objects.filter(idempotency_key="demo-scenario-d").count() == 1
    assert balance(w.wallets["A"]) == Decimal("25000")  # debited once
    assert treasury(w) == before + Decimal("75000")  # collected once
    assert WalletTransaction.objects.filter(wallet=w.wallets["A"], transaction_type=LedgerType.PAYMENT).count() == 1


def test_scenario_e_pupil_not_linked(w, api):
    # Same school, not my child: 403 (the right to pay is refused).
    with pytest.raises(PermissionDenied):
        pay(w, "A", w.invoices["F-S2-TUITION"], key="demo-scenario-e")
    api.force_authenticate(w.parents["A"].user)
    body = {
        "student": str(w.students["S2"].pk),
        "amount": "75000.00",
        "payment_method": "WALLET",
        "wallet": str(w.wallets["A"].pk),
        "invoices": [str(w.invoices["F-S2-TUITION"].pk)],
        "idempotency_key": "demo-scenario-e-api",
    }
    assert api.post("/api/v1/finance/payments/", body, format="json").status_code == 403
    # A pupil of another school: 404 (the id is not even visible).
    elsewhere = StudentFactory(school=SchoolFactory())
    body["student"] = str(elsewhere.pk)
    assert api.post("/api/v1/finance/payments/", body, format="json").status_code == 404
    assert balance(w.wallets["A"]) == Decimal("100000")


def test_refill_restores_the_demo_balances(w):
    pay(w, "A", w.invoices["F-S1-TUITION"], key="demo-refill-a")
    pay(w, "C", w.invoices["F-S3-CANTEEN"], key="demo-refill-c")
    refilled = dict(refill_wallets())
    assert refilled == {"A": Decimal("75000"), "C": Decimal("25000")}
    assert balance(w.wallets["A"]) == Decimal("100000") and balance(w.wallets["C"]) == Decimal("25000")
    assert refill_wallets() == []  # already full: nothing
    out = io.StringIO()
    call_command("seed_demo", "--refill-wallets", stdout=out)
    assert "0 wallet(s) rechargé(s)" in out.getvalue()


def test_never_with_production_settings(settings):
    settings.SETTINGS_MODULE = "config.settings.production"
    with pytest.raises(CommandError, match="production"):
        call_command("seed_demo", stdout=io.StringIO())
