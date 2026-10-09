"""Notifications produced from the existing domains, delivered to the right
recipients only, read/unread, preferences, push queue, immutability."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction

from apps.attendance import services as att
from apps.communication import notifications as notif
from apps.communication.models import Notification, NotificationDelivery
from apps.finance import services as fin
from apps.gradebook import services as gb
from apps.payroll import services as pay
from apps.payroll.models import TeacherPayroll
from apps.scheduling import services as planning
from apps.scheduling.models import ScheduleChange

from .communication_world import make_communication_world, verified_parent
from .conftest import DB
from .factories import SchoolFactory
from .planning_world import MONDAY, at
from .test_gradebook import fill_t1

pytestmark = DB


@pytest.fixture
def w(school):
    return make_communication_world(school)


def inbox(member, kind=None):
    notes = Notification.objects.filter(recipient=member)
    return notes.filter(notification_type=kind) if kind else notes


def late_scan(w, student):
    att.set_policy(
        w.school,
        MONDAY.isoweekday(),
        actor=w.admin,
        late_after_time=at(7, 30).time(),
        morning_absence_cutoff=at(10, 0).time(),
        absence_hours=Decimal("8.00"),
    )
    token = att.issue_qr_code(student, actor=w.admin).token
    return att.scan(token, actor=w.guardian, at=at(8, 5))


# =============================================================================
# Projection from the source domains
# =============================================================================


def test_late_arrival_notifies_only_the_verified_parents_of_that_pupil(w):
    muted = verified_parent(w, w.students[0], can_receive_notifications=False)
    late_scan(w, w.students[0])
    note = inbox(w.parent).get()
    assert (note.notification_type, note.severity, note.payload["late_minutes"]) == ("ATTENDANCE_LATE", "WARNING", 35)
    assert note.school == w.school and note.source_type == "attendance.StudentDailyAttendance"
    for nobody in (w.unverified, w.other_parent, muted, w.tm_member, w.guardian, w.admin):
        assert not inbox(nobody, "ATTENDANCE_LATE").exists()


def test_finalized_day_absences_are_notified_despite_bulk_writes(w):
    att.set_policy(
        w.school,
        MONDAY.isoweekday(),
        actor=w.admin,
        late_after_time=at(7, 30).time(),
        morning_absence_cutoff=at(10, 0).time(),
        absence_hours=Decimal("8.00"),
    )
    att.finalize_day(w.school, MONDAY, actor=w.admin)
    assert inbox(w.parent, "ATTENDANCE_ABSENT").count() == 1
    assert inbox(w.other_parent, "ATTENDANCE_ABSENT").count() == 1
    assert not inbox(w.unverified).exists()


def test_convocation_goes_to_the_convened_parent(w):
    att.create_convocation(
        w.students[0],
        w.parent.parent_profile,
        actor=w.admin,
        scheduled_start=at(14),
        scheduled_end=at(15),
        reason="Absences répétées",
    )
    note = inbox(w.parent, "CONVOCATION").get()
    assert note.severity == "CRITICAL"
    assert not Notification.objects.filter(notification_type="CONVOCATION").exclude(recipient=w.parent).exists()


def test_substitution_notifies_teachers_and_parents_without_internal_reason(w):
    session = w.sessions[0]
    planning.substitute_teacher(session, w.maths_substitute, actor=w.admin, reason="Congé maladie de M. X")
    change = ScheduleChange.objects.get(change_type="TEACHER_SUBSTITUTED")
    assert change.notification_status == "SENT" and change.notified_at is not None
    for teacher in (w.tm_member, w.maths_substitute.employee.membership):
        assert inbox(teacher, "SUBSTITUTION").get().payload["reason"] == "Congé maladie de M. X"
    parent_note = inbox(w.parent, "SUBSTITUTION").get()
    assert "reason" not in parent_note.payload and "Congé" not in parent_note.message
    assert not inbox(w.unverified).exists() and not inbox(w.outsider_teacher).exists()
    assert not inbox(w.tf_member, "SUBSTITUTION").exists()


def test_payment_goes_to_the_payer_and_the_admins_refund_to_the_payer_only(w):
    tuition = fin.create_fee_type(w.school, actor=w.admin, code="TUI", name="Scolarité")
    invoice = fin.issue_invoice(
        w.students[0], actor=w.admin, due_date=date(2025, 10, 1), lines=[{"fee_type": tuition, "unit_price": "1000"}]
    )
    w.parent.parent_profile.children_links.update(can_pay=True)
    wallet = fin.create_wallet(w.parent, actor=w.admin, provider_code="FAKE", wallet_identifier="600000001")
    fin.fund_wallet(wallet, "5000", actor=w.admin)
    payment = fin.initiate_payment(
        w.students[0],
        actor=w.parent,
        amount="1000",
        payment_method="WALLET",
        idempotency_key="k1",
        wallet=wallet,
        invoices=[invoice],
    ).payment
    assert inbox(w.parent, "PAYMENT").get().payload["status"] == "SUCCEEDED"
    fin.refund_payment(payment, actor=w.admin, amount="400", reason="Trop-perçu")
    assert inbox(w.parent, "REFUND").count() == 1
    assert not inbox(w.other_parent, "PAYMENT").exists()
    # A parent's confirmed mobile payment also reaches the administration (once);
    # the refund stays the payer's (tests/test_payment_admin_notifications.py).
    assert inbox(w.admin, "PAYMENT").get().event_key == f"payment.admin:{payment.pk}"
    assert not inbox(w.admin, "REFUND").exists()


def test_payroll_validation_and_payment_notify_the_employee(w):
    pay.validate_session(w.sessions[0], actor=w.admin)
    pay.calculate_period(w.october, actor=w.admin)
    payroll = TeacherPayroll.objects.get(teacher=w.tm)
    pay.approve_payroll(payroll, actor=w.admin)
    pay.pay_payroll(payroll, actor=w.admin, payout_method="CASH")
    assert list(inbox(w.tm_member, "PAYROLL").order_by("created_at").values_list("title", flat=True)) == [
        "Paie validée",
        "Paie versée",
    ]
    assert not inbox(w.tf_member, "PAYROLL").exists() and not inbox(w.staff_member, "PAYROLL").exists()


def test_validated_report_card_notifies_parents(w):
    fill_t1(w)
    card = next(c for c in gb.generate_report_cards(w.klass, w.t1, actor=w.admin) if c.student == w.students[0])
    assert not inbox(w.parent, "REPORT_CARD").exists()  # a draft card is not announced
    gb.close_period(w.t1, actor=w.admin)
    gb.validate_report_card(card, actor=w.admin)
    assert inbox(w.parent, "REPORT_CARD").count() == 1
    assert not inbox(w.other_parent, "REPORT_CARD").exists()


def test_projection_is_idempotent_and_replayable(w):
    late_scan(w, w.students[0])
    late_scan(w, w.students[0])  # second scan of the same day
    call_command("dispatch_notifications", school=w.school.code, days=3650)
    assert inbox(w.parent).count() == 1


# =============================================================================
# Inbox, preferences, push queue
# =============================================================================


def test_read_unread(w):
    late_scan(w, w.students[0])
    att.create_convocation(
        w.students[0], w.parent.parent_profile, actor=w.admin, scheduled_start=at(14), scheduled_end=at(15), reason="x"
    )
    assert notif.unread_count(w.parent) == 2
    first = inbox(w.parent).first()
    notif.mark_read(first, actor=w.parent)
    first.refresh_from_db()
    assert first.is_read and first.read_at and notif.unread_count(w.parent) == 1
    with pytest.raises(PermissionDenied):
        notif.mark_read(inbox(w.parent).last(), actor=w.other_parent)
    assert notif.mark_all_read(w.parent) == 1 and notif.unread_count(w.parent) == 0


def test_preferences_and_push_queue(w):
    notif.set_preference(w.parent, "ATTENDANCE_LATE", push_enabled=False)
    late_scan(w, w.students[0])
    note = inbox(w.parent).get()
    assert not NotificationDelivery.objects.filter(notification=note).exists()
    att.create_convocation(
        w.students[0], w.parent.parent_profile, actor=w.admin, scheduled_start=at(14), scheduled_end=at(15), reason="x"
    )
    delivery = NotificationDelivery.objects.get(notification__notification_type="CONVOCATION")
    assert (delivery.status, delivery.channel, delivery.attempts) == ("PENDING", "PUSH", 0)  # FCM later
    notif.set_preference(w.other_parent, "ATTENDANCE_LATE", in_app_enabled=False)
    late_scan(w, w.students[1])
    assert not inbox(w.other_parent).exists()
    with pytest.raises(ValidationError) as exc:
        notif.set_preference(w.parent, "CONVOCATION", in_app_enabled=False)
    assert exc.value.code == "notification_mandatory"


def test_notifications_are_immutable_history(w):
    late_scan(w, w.students[0])
    note = inbox(w.parent).get()
    for attempt in (
        lambda: Notification.objects.filter(pk=note.pk).update(title="x"),
        lambda: Notification.objects.filter(pk=note.pk).delete(),
    ):
        with pytest.raises(IntegrityError), transaction.atomic():
            attempt()
    notif.mark_read(note, actor=w.parent)
    with pytest.raises(IntegrityError), transaction.atomic():
        Notification.objects.filter(pk=note.pk).update(is_read=False, read_at=None)


def test_a_notification_never_crosses_schools(w):
    """Mutation target: the explicit recipient must belong to the event's school."""
    other = make_communication_world(SchoolFactory())
    with pytest.raises(PermissionDenied):
        notif.notify(
            other.parent, school=w.school, notification_type="PAYMENT", title="x", message="x", event_key="test:1"
        )
    late_scan(w, w.students[0])
    assert not Notification.objects.filter(school=other.school, notification_type="ATTENDANCE_LATE").exists()
    assert all(n.school_id == n.recipient.school_id for n in Notification.objects.select_related("recipient"))


def test_inactive_member_gets_nothing(w):
    w.parent.status = "SUSPENDED"
    w.parent.save()
    late_scan(w, w.students[0])
    assert not inbox(w.parent).exists()
    assert MONDAY + timedelta(days=0) == w.sessions[0].date


def test_inbox_api_shows_only_the_callers_notifications(w):
    """Mutation target: the inbox is filtered on the explicit recipient."""
    from rest_framework.test import APIClient

    late_scan(w, w.students[0])
    note = inbox(w.parent, "ATTENDANCE_LATE").get()

    def client(member):
        api = APIClient()
        api.force_authenticate(member.user)
        return api

    mine = client(w.parent).get("/api/v1/notifications/?type=ATTENDANCE_LATE").json()["data"]
    assert [n["id"] for n in mine] == [str(note.pk)]
    for other in (w.other_parent, w.tm_member, w.admin):
        listed = client(other).get("/api/v1/notifications/").json()["data"]
        assert str(note.pk) not in {n["id"] for n in listed}
        assert client(other).post(f"/api/v1/notifications/{note.pk}/read/").status_code == 404
    assert client(w.parent).get("/api/v1/notifications/unread-count/").json()["data"]["unread"] == 1
    assert client(w.parent).post("/api/v1/notifications/read-all/").json()["data"]["marked"] == 1
