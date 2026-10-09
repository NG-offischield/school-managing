"""A parent's mobile payment, once really confirmed by Finance, notifies the
administrators of the SAME school (the members Finance lets see payments):
persisted, idempotent, pushed live, read later — never for a refused,
failed or rolled-back attempt, never across schools. Finance itself is
unchanged (same outcome, ledgers, invoices)."""

from decimal import Decimal

import pytest
from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from django.db import transaction
from rest_framework.test import APIClient

from apps.accounts.models import MembershipRole
from apps.communication import events
from apps.communication.models import Notification
from apps.finance import services as fin
from apps.finance.models import Invoice, PaymentStatus, TreasuryTransaction, WalletTransaction

from .conftest import DB
from .factories import SchoolFactory, member_with_role
from .finance_world import make_finance_world, wallet_for
from .test_realtime import authenticated

pytestmark = DB


@pytest.fixture
def w(school):
    w = make_finance_world(school)
    w.super_admin = member_with_role(school, "SUPER_ADMIN")
    w.suspended_admin = member_with_role(school, "ADMIN", status="SUSPENDED")
    w.former_admin = member_with_role(school, "ADMIN")
    MembershipRole.objects.filter(membership=w.former_admin).update(active=False)
    w.staff = member_with_role(school, "STAFF")
    w.teacher = w.tm.employee.membership
    return w


def admin_notes(member=None, **filters):
    notes = Notification.objects.filter(notification_type="PAYMENT", event_key__startswith="payment.admin:", **filters)
    return notes.filter(recipient=member) if member is not None else notes


def pay(w, *, wallet=None, key="mobile-1", amount="60000", invoices=None, actor=None):
    return fin.initiate_payment(
        w.students[0],
        actor=actor or w.parent,
        amount=amount,
        payment_method="WALLET",
        idempotency_key=key,
        wallet=wallet or w.wallet,
        invoices=[w.inv1] if invoices is None else invoices,
    )


def test_a_confirmed_parent_payment_notifies_the_schools_administrators(w):
    payment = pay(w).payment
    assert payment.status == PaymentStatus.SUCCEEDED
    w.inv1.refresh_from_db()
    note = admin_notes(w.admin).get()
    assert note.school_id == w.school.pk
    assert note.title == f"Paiement confirmé — facture {w.inv1.invoice_number} — 60 000 XAF"
    assert w.students[0].full_name in note.message and payment.payment_reference in note.message
    assert note.payload == {
        "payment": str(payment.pk),
        "reference": payment.payment_reference,
        "status": "SUCCEEDED",
        "amount": "60000.00",
        "currency": "XAF",
        "student": str(w.students[0].pk),
        "invoices": [str(w.inv1.pk)],
    }
    assert admin_notes(w.super_admin).count() == 1  # every administrator of the school
    # The payer keeps the existing notification, unchanged.
    payer = Notification.objects.get(recipient=w.parent, notification_type="PAYMENT")
    assert payer.title == "Paiement confirmé" and payer.event_key == f"payment:{payment.pk}:SUCCEEDED"


def test_several_invoices_are_listed(w):
    pay(w, amount="100000", invoices=[w.inv1, w.inv2])
    numbers = sorted([w.inv1.invoice_number, w.inv2.invoice_number])
    assert admin_notes(w.admin).get().title == f"Paiement confirmé — factures {', '.join(numbers)} — 100 000 XAF"


def test_only_members_allowed_to_see_finance_are_notified(w):
    pay(w)
    recipients = set(admin_notes().values_list("recipient", flat=True))
    assert recipients == {w.admin.pk, w.super_admin.pk}
    for member in (w.parent, w.teacher, w.staff, w.suspended_admin, w.former_admin):
        assert not admin_notes(member).exists()


@pytest.mark.parametrize(
    "behavior, status",
    [("DECLINE", "DECLINED"), ("PROVIDER_ERROR", "PROVIDER_ERROR"), ("TIMEOUT", "TIMEOUT")],
)
def test_a_refused_or_failed_attempt_is_never_announced_as_paid(w, behavior, status):
    wallet = wallet_for(w, w.parent, behavior=behavior, identifier="699000001")
    payment = pay(w, wallet=wallet).payment
    assert payment.status == status
    assert not admin_notes().exists()
    assert Notification.objects.get(recipient=w.parent, notification_type="PAYMENT").title == "Paiement non abouti"


def test_insufficient_funds_produce_no_success_notification(w):
    poor = wallet_for(w, w.parent, balance="100", identifier="699000002")
    assert pay(w, wallet=poor).payment.status == "INSUFFICIENT_FUNDS"
    assert not admin_notes().exists()
    assert not Notification.objects.filter(title__startswith="Paiement confirmé").exists()


def test_a_rolled_back_payment_announces_nothing(w):
    with pytest.raises(RuntimeError), transaction.atomic():
        pay(w)
        raise RuntimeError("the surrounding transaction fails")
    assert not Notification.objects.filter(notification_type="PAYMENT").exists()


def test_a_replay_never_doubles_the_notification(w):
    first = pay(w)
    replay = pay(w)  # lost response: the parent app resends the same intent
    assert replay.replayed and replay.payment.pk == first.payment.pk
    events.project_payment(first.payment)  # the projector invoked again (dispatch_notifications)
    events.project_payment(first.payment)
    assert admin_notes(w.admin).count() == 1
    assert Notification.objects.filter(recipient=w.parent, notification_type="PAYMENT").count() == 1


def test_counter_payments_recorded_by_the_administration_do_not_notify_it(w):
    fin.initiate_payment(
        w.students[0],
        actor=w.admin,
        amount="60000",
        payment_method="CASH",
        idempotency_key="cash-1",
        invoices=[w.inv1],
        payer=w.parent,
    )
    assert not admin_notes().exists()


def test_another_school_receives_nothing_and_sees_nothing(w):
    other = make_finance_world(SchoolFactory())
    pay(w)
    pay(other, key="other-1")
    assert set(admin_notes().filter(school=w.school).values_list("recipient", flat=True)) == {
        w.admin.pk,
        w.super_admin.pk,
    }
    assert set(admin_notes().filter(school=other.school).values_list("recipient", flat=True)) == {other.admin.pk}
    assert not admin_notes(w.admin).filter(payload__student=str(other.students[0].pk)).exists()
    client = APIClient()
    client.force_authenticate(other.admin.user)
    rows = client.get("/api/v1/notifications/", {"type": "PAYMENT"}).json()["data"]
    assert [r["payload"]["student"] for r in rows] == [str(other.students[0].pk)]


def test_an_offline_administrator_finds_it_later(w):
    pay(w)
    client = APIClient()
    client.force_authenticate(w.admin.user)
    assert client.get("/api/v1/notifications/unread-count/").json()["data"]["unread"] == 1
    rows = client.get("/api/v1/notifications/", {"type": "PAYMENT"}).json()["data"]
    assert len(rows) == 1 and rows[0]["title"].startswith("Paiement confirmé — facture ")
    assert rows[0]["is_read"] is False


def test_pushed_live_to_the_administrator_only(w):
    async def scenario():
        admin, _ = await authenticated(w.admin)
        teacher, _ = await authenticated(w.teacher)
        payment = (await database_sync_to_async(pay)(w)).payment
        frame = await admin.receive_json_from(timeout=5)
        assert frame["type"] == "notification" and frame["data"]["notification_type"] == "PAYMENT"
        assert frame["data"]["payload"]["payment"] == str(payment.pk)
        assert await teacher.receive_nothing(timeout=0.5)
        await admin.disconnect()
        await teacher.disconnect()

    async_to_sync(scenario)()


def test_finance_outcome_is_unchanged(w):
    before_wallet = w.wallet.balance
    payment = pay(w).payment
    w.wallet.refresh_from_db()
    assert w.wallet.balance == before_wallet - Decimal("60000")
    assert Invoice.objects.get(pk=w.inv1.pk).status == "PAID"
    assert WalletTransaction.objects.filter(reference=payment.payment_reference).count() == 1  # wallet debit
    assert TreasuryTransaction.objects.filter(reference=payment.payment_reference).count() == 1  # treasury credit
