"""Finance services and database guarantees (ADR 0013)."""

import threading
import uuid
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction

from apps.audit.models import AuditLog
from apps.finance import services as fin
from apps.finance.models import (
    Invoice,
    InvoiceStatus,
    LedgerDirection,
    LedgerType,
    Payment,
    PaymentAllocation,
    PaymentRefund,
    PaymentStatus,
    TreasuryTransaction,
    WalletTransaction,
)

from .conftest import DB
from .factories import SchoolFactory, admin_of, member_with_role
from .finance_world import make_finance_world, verified_parent, wallet_for
from .gradebook_world import make_world

pytestmark = DB
D = Decimal


@pytest.fixture
def w(school):
    return make_finance_world(school)


def key():
    return str(uuid.uuid4())


def pay(w, amount, *, actor=None, wallet=None, invoices=None, idem=None, **kw):
    invoices = [w.inv1, w.inv2] if invoices is None else invoices
    return fin.initiate_payment(
        w.students[0],
        actor=actor or w.parent,
        amount=amount,
        payment_method=kw.pop("method", "WALLET"),
        idempotency_key=idem or key(),
        wallet=wallet if wallet is not None else w.wallet,
        invoices=invoices,
        **kw,
    )


def reload(*objs):
    for obj in objs:
        obj.refresh_from_db()


def rule(exc):
    return exc.value.code


# =============================================================================
# Invoices
# =============================================================================


def test_invoice_numbering_totals_and_line_arithmetic(w):
    assert (w.inv1.invoice_number, w.inv2.invoice_number) == ("F25-000001", "F25-000002")
    assert (w.inv1.total_amount, w.inv1.balance_due, w.inv1.status) == (D("60000.00"), D("60000.00"), "ISSUED")
    line = w.inv1.lines.get()
    with pytest.raises(IntegrityError), transaction.atomic():
        type(line).objects.filter(pk=line.pk).update(total=D("1.00"))  # CHECK total = qty x price


def test_invoice_balance_is_checked_by_postgresql(w):
    with pytest.raises(IntegrityError), transaction.atomic():
        Invoice.objects.filter(pk=w.inv1.pk).update(amount_paid=D("10.00"))  # balance no longer total - paid
    with pytest.raises(IntegrityError), transaction.atomic():
        Invoice.objects.filter(pk=w.inv1.pk).update(status=InvoiceStatus.PAID)  # PAID with a balance


def test_only_admins_issue_invoices(w):
    with pytest.raises(PermissionDenied):
        fin.issue_invoice(
            w.students[1],
            actor=w.parent,
            due_date=date(2026, 1, 1),
            lines=[{"fee_type": w.tuition, "unit_price": "10"}],
        )


def test_generate_invoices_from_schedules_is_idempotent(w):
    fin.create_fee_schedule(
        w.tuition, actor=w.admin, academic_year=w.year, amount="25000", due_date=date(2025, 11, 1), school_class=w.klass
    )
    first = fin.generate_invoices(w.klass, actor=w.admin)
    assert len(first) == 3 and all(i.total_amount == D("25000.00") for i in first)
    assert fin.generate_invoices(w.klass, actor=w.admin) == []


def test_cancel_invoice_only_without_payments(w):
    pay(w, "60000", invoices=[w.inv1])
    with pytest.raises(ValidationError) as exc:
        fin.cancel_invoice(w.inv1, actor=w.admin, reason="erreur")
    assert rule(exc) == "invoice_has_payments"
    cancelled = fin.cancel_invoice(w.inv2, actor=w.admin, reason="doublon")
    assert cancelled.status == "CANCELLED"
    assert AuditLog.objects.filter(action="INVOICE_CANCELLED", entity_id=w.inv2.pk).exists()


# =============================================================================
# Payment outcomes (deterministic simulated provider)
# =============================================================================


def test_successful_payment_moves_money_allocates_oldest_first_and_audits(w):
    outcome = pay(w, "70000")
    p = outcome.payment
    assert (outcome.replayed, p.status, p.provider) == (False, "SUCCEEDED", "SIMULATION_WALLET")
    assert p.completed_at and p.provider_reference.startswith("SIM-")
    assert (p.student, p.payer, p.initiated_by) == (w.students[0], w.parent, w.parent)
    reload(w.inv1, w.inv2, w.wallet)
    assert (w.inv1.status, w.inv1.balance_due) == ("PAID", D("0.00"))
    assert (w.inv2.status, w.inv2.amount_paid, w.inv2.balance_due) == ("PARTIALLY_PAID", D("10000.00"), D("30000.00"))
    assert w.wallet.balance == D("80000.00")
    assert fin.get_treasury(w.school).balance == D("70000.00")
    debit = WalletTransaction.objects.get(reference=p.payment_reference)
    assert (debit.direction, debit.balance_before, debit.balance_after) == ("DEBIT", D("150000.00"), D("80000.00"))
    assert TreasuryTransaction.objects.get(reference=p.payment_reference).direction == LedgerDirection.CREDIT
    assert sorted(a.amount for a in p.allocations.all()) == [D("10000.00"), D("60000.00")]
    log = AuditLog.objects.get(action="PAYMENT_SUCCEEDED", entity_id=p.pk)
    assert (log.actor, log.school, log.new_data["amount"]) == (w.parent, w.school, "70000.00")


@pytest.mark.parametrize(
    ("behavior", "expected"),
    [("DECLINE", "DECLINED"), ("TIMEOUT", "TIMEOUT"), ("PROVIDER_ERROR", "PROVIDER_ERROR")],
)
def test_provider_failures_are_recorded_results_without_money_movement(w, behavior, expected):
    wallet = wallet_for(w, w.parent, behavior=behavior, identifier="699000001")
    p = pay(w, "10000", wallet=wallet).payment
    assert (p.status, p.completed_at is not None, bool(p.failure_reason)) == (expected, True, True)
    reload(wallet, w.inv1)
    assert wallet.balance == D("150000.00") and w.inv1.amount_paid == 0
    assert not WalletTransaction.objects.filter(reference=p.payment_reference).exists()
    assert not PaymentAllocation.objects.filter(payment=p).exists()
    assert fin.get_treasury(w.school).balance == 0
    assert AuditLog.objects.get(action="PAYMENT_FAILED", entity_id=p.pk).new_data["status"] == expected


def test_insufficient_funds(w):
    poor = wallet_for(w, w.parent, balance="5000", identifier="699000002")
    p = pay(w, "60000", wallet=poor).payment
    assert p.status == "INSUFFICIENT_FUNDS"
    reload(poor)
    assert poor.balance == D("5000.00")


def test_blocked_wallet_is_declined(w):
    w.wallet.status = "BLOCKED"
    w.wallet.save()
    assert pay(w, "1000").payment.status == "DECLINED"


def test_fee_type_payment_without_invoice(w):
    p = pay(w, "2500", invoices=[], fee_type=w.tuition).payment
    assert p.status == "SUCCEEDED" and not p.allocations.exists() and p.fee_type == w.tuition
    with pytest.raises(ValidationError) as exc:
        pay(w, "2500", invoices=[])
    assert rule(exc) == "payment_reason_required"


def test_amount_rules(w):
    with pytest.raises(ValidationError) as exc:
        pay(w, "100001")
    assert rule(exc) == "amount_exceeds_balance"
    for bad in ("0", "-5", "10.001"):
        with pytest.raises(ValidationError):
            pay(w, bad)
    with pytest.raises(ValidationError) as exc:
        pay(
            w,
            "10",
            invoices=[
                fin.issue_invoice(
                    w.students[1],
                    actor=w.admin,
                    due_date=date(2026, 1, 1),
                    lines=[{"fee_type": w.tuition, "unit_price": "10"}],
                )
            ],
        )
    assert rule(exc) == "invoice_other_student"
    assert not Payment.objects.exists()


def test_cash_payment_is_admin_only(w):
    p = pay(w, "60000", actor=w.admin, method="CASH", wallet=None, payer=w.parent).payment
    assert (p.status, p.provider, p.wallet, p.payer, p.initiated_by) == ("SUCCEEDED", "CASH", None, w.parent, w.admin)
    assert fin.get_treasury(w.school).balance == D("60000.00")
    with pytest.raises(PermissionDenied):
        pay(w, "1000", method="CASH", wallet=None)


# =============================================================================
# Idempotency / double submission
# =============================================================================


def test_same_key_replays_without_charging_twice(w):
    idem = key()
    first = pay(w, "30000", idem=idem)
    again = pay(w, "30000", idem=idem)
    assert (again.replayed, again.payment.pk) == (True, first.payment.pk)
    reload(w.wallet)
    assert w.wallet.balance == D("120000.00") and Payment.objects.count() == 1
    assert WalletTransaction.objects.filter(transaction_type=LedgerType.PAYMENT).count() == 1


def test_same_key_for_a_different_request_is_a_conflict(w):
    idem = key()
    pay(w, "30000", idem=idem)
    with pytest.raises(ValidationError) as exc:
        pay(w, "30001", idem=idem)
    assert rule(exc) == "idempotency_conflict"


def test_a_failed_payment_is_replayed_too_a_retry_needs_a_new_key(w):
    poor = wallet_for(w, w.parent, balance="10", identifier="699000003")
    idem = key()
    failed = pay(w, "500", wallet=poor, idem=idem).payment
    assert pay(w, "500", wallet=poor, idem=idem).payment.pk == failed.pk
    fin.fund_wallet(poor, "1000", actor=w.admin)
    assert pay(w, "500", wallet=poor).payment.status == "SUCCEEDED"


def concurrently(*calls):
    """Run the calls in parallel threads (own DB connections); returns
    (results, errors)."""
    results, errors = [], []
    barrier = threading.Barrier(len(calls))

    def run(call):
        try:
            barrier.wait()
            results.append(call())
        except Exception as exc:  # pragma: no cover - reported by the caller
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(call,)) for call in calls]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results, errors


def test_concurrent_double_submission_charges_once(w):
    idem = key()
    results, errors = concurrently(lambda: pay(w, "40000", idem=idem), lambda: pay(w, "40000", idem=idem))
    assert errors == []
    assert sorted(r.replayed for r in results) == [False, True]
    assert len({r.payment.pk for r in results}) == 1
    reload(w.wallet)
    assert w.wallet.balance == D("110000.00") and Payment.objects.count() == 1


def test_two_different_payments_racing_on_one_wallet(w):
    """Wallet locked before the provider decides: with 150 000 available, two
    simultaneous 100 000 payments give one SUCCEEDED and one recorded
    INSUFFICIENT_FUNDS — never a crash, never a negative balance."""
    results, errors = concurrently(
        lambda: pay(w, "100000", invoices=[], fee_type=w.tuition),
        lambda: pay(w, "100000", invoices=[], fee_type=w.tuition),
    )
    assert errors == []
    assert sorted(r.payment.status for r in results) == ["INSUFFICIENT_FUNDS", "SUCCEEDED"]
    reload(w.wallet)
    assert w.wallet.balance == D("50000.00")


def test_idempotency_keys_are_scoped_to_the_school(w):
    """Mutation target: the same key in another school is another payment."""
    idem = key()
    pay(w, "1000", idem=idem)
    other = make_finance_world(SchoolFactory())
    p = pay(other, "1000", idem=idem).payment
    assert p.school == other.school and Payment.objects.count() == 2


# =============================================================================
# Rights
# =============================================================================


def test_only_admins_and_verified_payers_can_pay(w):
    s0 = w.students[0]
    viewer = verified_parent(w, s0, can_pay=False)
    teacher = w.tm_member
    from apps.people import services as people

    from .factories import ParentFactory

    declared = ParentFactory(school=w.school)
    people.link_parent(declared, s0, relationship_type="FATHER")  # not verified
    for actor in (viewer, teacher, declared.membership, member_with_role(w.school, "STAFF")):
        assert not fin.can_pay(actor, s0)
        with pytest.raises(PermissionDenied):
            pay(w, "1000", actor=actor, wallet=wallet_for(w, actor, identifier=f"7{uuid.uuid4().int % 10**8}"))
    other_parent = verified_parent(w, w.students[1])
    with pytest.raises(PermissionDenied):
        pay(w, "1000", actor=other_parent, wallet=wallet_for(w, other_parent, identifier="699000004"))
    assert not Payment.objects.exists()


def test_a_payer_can_only_use_their_own_wallet(w):
    second = verified_parent(w, w.students[0])
    with pytest.raises(PermissionDenied):
        pay(w, "1000", actor=second, wallet=w.wallet)


def test_inactive_link_or_membership_loses_payment_right(w):
    link = w.parent.parent_profile.children_links.get()
    link.active = False
    link.save()
    assert not fin.can_pay(w.parent, w.students[0])


def test_admin_of_another_school_is_nobody_here(w):
    foreign_admin = admin_of(SchoolFactory())
    with pytest.raises(PermissionDenied):
        pay(w, "1000", actor=foreign_admin, method="CASH", wallet=None)
    with pytest.raises(PermissionDenied):
        fin.refund_payment(pay(w, "1000").payment, actor=foreign_admin, amount="1", reason="x")


# =============================================================================
# Refunds = inverse transactions
# =============================================================================


def test_partial_then_full_refund_through_inverse_transactions(w):
    p = pay(w, "70000").payment
    r1 = fin.refund_payment(p, actor=w.admin, amount="15000", reason="Trop-perçu")
    reload(p, w.inv1, w.inv2, w.wallet)
    assert (p.status, p.refunded_amount, p.amount) == ("PARTIALLY_REFUNDED", D("15000.00"), D("70000.00"))
    assert (r1.payment, r1.status, r1.inverse_transaction_reference.startswith("REF-")) == (p, "COMPLETED", True)
    # Latest allocation reversed first, then the older one.
    assert (w.inv2.amount_paid, w.inv1.amount_paid) == (D("0.00"), D("55000.00"))
    assert w.inv1.status == "PARTIALLY_PAID" and w.inv2.status == "ISSUED"
    assert w.wallet.balance == D("95000.00") and fin.get_treasury(w.school).balance == D("55000.00")
    inverse = WalletTransaction.objects.get(reference=r1.inverse_transaction_reference)
    assert (inverse.transaction_type, inverse.direction, inverse.metadata["payment"]) == ("REFUND", "CREDIT", str(p.pk))
    assert PaymentAllocation.objects.filter(refund=r1).count() == 2  # 10 000 on inv2 + 5 000 on inv1

    fin.refund_payment(p, actor=w.admin, amount="55000", reason="Départ")
    reload(p, w.inv1)
    assert (p.status, p.refunded_amount) == ("REFUNDED", D("70000.00"))
    assert w.inv1.amount_paid == 0 and fin.get_treasury(w.school).balance == 0
    # The original payment and its ledger lines are still there, untouched.
    assert WalletTransaction.objects.filter(reference=p.payment_reference, direction="DEBIT").count() == 1
    assert PaymentRefund.objects.filter(payment=p).count() == 2
    assert AuditLog.objects.filter(action="PAYMENT_REFUNDED").count() == 2


def test_refund_rules(w):
    p = pay(w, "10000").payment
    with pytest.raises(ValidationError) as exc:
        fin.refund_payment(p, actor=w.admin, amount="10000.01", reason="x")
    assert rule(exc) == "refund_exceeds_payment"
    with pytest.raises(ValidationError) as exc:
        fin.refund_payment(p, actor=w.admin, amount="1", reason="  ")
    assert rule(exc) == "reason_required"
    with pytest.raises(PermissionDenied):
        fin.refund_payment(p, actor=w.parent, amount="1", reason="moi")
    failed = pay(w, "10", wallet=wallet_for(w, w.parent, behavior="DECLINE", identifier="699000005")).payment
    with pytest.raises(ValidationError) as exc:
        fin.refund_payment(failed, actor=w.admin, amount="10", reason="x")
    assert rule(exc) == "payment_not_refundable"


def test_cash_refund_touches_only_the_treasury(w):
    p = pay(w, "5000", actor=w.admin, method="CASH", wallet=None, payer=w.parent).payment
    refund = fin.refund_payment(p, actor=w.admin, amount="5000", reason="Annulation")
    assert not WalletTransaction.objects.filter(reference=refund.inverse_transaction_reference).exists()
    assert fin.get_treasury(w.school).balance == 0


# =============================================================================
# History is append-only (PostgreSQL triggers)
# =============================================================================


def test_ledgers_allocations_and_refunds_cannot_be_rewritten_or_deleted(w):
    p = pay(w, "60000").payment
    fin.refund_payment(p, actor=w.admin, amount="1000", reason="x")
    for model in (WalletTransaction, TreasuryTransaction, PaymentAllocation, PaymentRefund):
        row = model.objects.first()
        with pytest.raises(IntegrityError), transaction.atomic():
            model.objects.filter(pk=row.pk).update(created_at=row.created_at)
        with pytest.raises(IntegrityError), transaction.atomic():
            model.objects.filter(pk=row.pk).delete()


def test_completed_payments_are_never_deleted_or_rewritten(w):
    p = pay(w, "60000").payment
    failed = pay(w, "10", wallet=wallet_for(w, w.parent, behavior="TIMEOUT", identifier="699000006")).payment
    attempts = [
        lambda: Payment.objects.filter(pk=p.pk).delete(),
        lambda: Payment.objects.filter(pk=p.pk).update(amount=D("1.00")),
        lambda: Payment.objects.filter(pk=p.pk).update(status=PaymentStatus.PENDING),
        lambda: Payment.objects.filter(pk=failed.pk).update(status=PaymentStatus.SUCCEEDED),
        lambda: Payment.objects.filter(pk=p.pk).update(payer=w.admin),
    ]
    for attempt in attempts:
        with pytest.raises(IntegrityError), transaction.atomic():
            attempt()
    reload(p)
    assert (p.amount, p.status) == (D("60000.00"), "SUCCEEDED")


def test_balances_can_never_go_negative(w):
    with pytest.raises(IntegrityError), transaction.atomic():
        type(w.wallet).objects.filter(pk=w.wallet.pk).update(balance=D("-1"))
    with pytest.raises(ValidationError), transaction.atomic():
        fin._post(
            fin.get_treasury(w.school),
            transaction_type=LedgerType.REFUND,
            direction=LedgerDirection.DEBIT,
            amount=D("1.00"),
            reference="X",
            actor=w.admin,
        )


def test_wallet_of_a_payment_must_belong_to_its_payer(w):
    """Composite FK (wallet, payer) -> wallet(id, owner): even raw SQL cannot
    record a payment made by A with B's wallet."""
    other = verified_parent(w, w.students[0])
    with pytest.raises(IntegrityError), transaction.atomic():
        Payment.objects.create(
            school=w.school,
            payment_reference="RAW-1",
            idempotency_key="raw-1",
            request_fingerprint="x",
            student=w.students[0],
            payer=other,
            initiated_by=other,
            wallet=w.wallet,
            amount=D("1"),
            currency="XAF",
            payment_method="WALLET",
            provider="SIMULATION_WALLET",
        )


# =============================================================================
# Read models
# =============================================================================


def test_solvency_and_dashboard(w):
    s0 = w.students[0]
    assert fin.solvency(s0) == "OVERDUE"  # inv1 due 2025-10-15, unpaid
    assert fin.solvency(w.students[1]) == "UP_TO_DATE"
    pay(w, "100000")
    assert fin.solvency(s0) == "UP_TO_DATE"
    pay(
        w,
        "1",
        invoices=[],
        fee_type=w.tuition,
        wallet=wallet_for(w, w.parent, behavior="DECLINE", identifier="6990007"),
    )
    data = fin.dashboard(w.school)
    assert (data["collected"], data["outstanding"], data["treasury_balance"]) == (D("100000.00"), 0, D("100000.00"))
    assert data["payments_by_status"] == {"SUCCEEDED": 1, "DECLINED": 1} and data["failed_payments"] == 1


def test_finance_of_two_schools_never_mix(w):
    other = make_world(SchoolFactory())
    assert fin.get_treasury(other.school).balance == 0
    pay(w, "60000")
    assert fin.dashboard(other.school)["collected"] == 0
    with pytest.raises(ValidationError):  # invoice of school A in a payment of school B
        fin.initiate_payment(
            other.students[0],
            actor=other.admin,
            amount="10",
            payment_method="CASH",
            idempotency_key=key(),
            invoices=[w.inv2],
        )
