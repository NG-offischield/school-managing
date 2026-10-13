"""Notification projectors: business events of the other domains -> notifications.

The source domains do NOT import this app and are not modified: each
projector reads a source row AFTER its transaction committed and turns the
state the source domain decided (a LATE record, a SUCCEEDED payment, an
APPROVED payroll...) into notifications. No business rule is re-implemented
here: "is this pupil late?" is answered by attendance, "is this payment
successful?" by finance.

    source row                      notification                   recipients
    StudentDailyAttendance LATE     ATTENDANCE_LATE                parents (verified, notifications on)
    StudentDailyAttendance ABSENT   ATTENDANCE_ABSENT              idem
    Convocation (any status)        CONVOCATION                    the convened parent
    ScheduleChange (PENDING)        SCHEDULE_CHANGE / SUBSTITUTION teachers concerned + parents of the class
    Payment SUCCEEDED / failed      PAYMENT                        the payer
    Payment SUCCEEDED (parent,       PAYMENT                        the school's administrators
      own wallet: parent app)                                      (who see Finance)
    PaymentRefund                   REFUND                         the payer
    Teacher/StaffPayroll APPROVED   PAYROLL                        the employee
      / PAID
    ReportCard VALIDATED            REPORT_CARD                    parents

Triggers: post_save of the source models (scan, corrections, services) and,
for the bulk path of attendance (finalize_day uses bulk_create/update, which
send no signal), the ATTENDANCE_DAY_FINALIZED audit row. Every projector is
idempotent (event_key), so `manage.py dispatch_notifications` can replay any
window after an outage without duplicates. A projector failure never breaks
the source transaction (it runs after commit) and is logged.
"""

import logging
from datetime import date

from django.db import transaction
from django.db.models.signals import post_save
from django.utils import timezone

from apps.attendance.models import Convocation, DailyStatus, StudentDailyAttendance
from apps.audit.models import AuditLog
from apps.finance.models import FAILED_STATUSES, Payment, PaymentMethod, PaymentRefund, PaymentStatus
from apps.gradebook.models import ReportCard, ReportCardStatus
from apps.payroll.models import PayrollStatus, StaffPayroll, TeacherPayroll
from apps.people.models import EnrollmentStatus, Student, TeacherProfile
from apps.scheduling.models import ChangeType, NotificationStatus, ScheduleChange
from common.permissions import membership_has_role

from .models import NotificationType, Severity
from .notifications import administrators, notify_many, parents_to_inform
from .texts import label, text

logger = logging.getLogger(__name__)


# =============================================================================
# Projectors (one per source model)
# =============================================================================


def project_attendance(record):
    if record.status not in (DailyStatus.LATE, DailyStatus.ABSENT):
        return []
    student = record.student
    late = record.status == DailyStatus.LATE
    return notify_many(
        parents_to_inform(student),
        school=record.school,
        notification_type=NotificationType.ATTENDANCE_LATE if late else NotificationType.ATTENDANCE_ABSENT,
        severity=Severity.WARNING,
        title=text("attendance.late.title" if late else "attendance.absent.title", student=student.full_name),
        message=(
            text(
                "attendance.late.message",
                student=student.full_name,
                minutes=record.late_minutes,
                date=f"{record.date:%d/%m/%Y}",
            )
            if late
            else text("attendance.absent.message", student=student.full_name, date=f"{record.date:%d/%m/%Y}")
        ),
        event_key=f"attendance:{record.pk}:{record.status}",
        payload={
            "student": str(student.pk),
            "date": record.date.isoformat(),
            "status": record.status,
            "late_minutes": record.late_minutes,
        },
        source=record,
    )


def project_convocation(convocation):
    scheduled = convocation.status == "SCHEDULED"
    start = timezone.localtime(convocation.scheduled_start)
    return notify_many(
        [convocation.parent.membership],
        school=convocation.school,
        notification_type=NotificationType.CONVOCATION,
        severity=Severity.CRITICAL if scheduled else Severity.INFO,
        title=(
            text("convocation.scheduled.title", student=convocation.student.full_name)
            if scheduled
            else text("convocation.status.title", status=label("convocation_status", convocation.status, lower=True))
        ),
        message=(
            text("convocation.scheduled.message", date=f"{start:%d/%m/%Y}", time=f"{start:%H:%M}")
            if scheduled
            else text("convocation.status.message")
        ),
        event_key=f"convocation:{convocation.pk}:{convocation.status}",
        payload={
            "convocation": str(convocation.pk),
            "student": str(convocation.student_id),
            "status": convocation.status,
            "scheduled_start": convocation.scheduled_start.isoformat(),
        },
        source=convocation,
    )


SUBSTITUTION_CHANGES = {ChangeType.TEACHER_SUBSTITUTED, ChangeType.TEACHER_RESTORED}


def project_schedule_change(change):
    """The planning outbox (ADR 0012): only changes flagged for notification
    (PENDING). Teachers get the reason; parents only the facts."""
    if change.notification_status != NotificationStatus.PENDING:
        return []
    kind = (
        NotificationType.SUBSTITUTION
        if change.change_type in SUBSTITUTION_CHANGES
        else NotificationType.SCHEDULE_CHANGE
    )
    session = change.session
    facts = {
        "change": str(change.pk),
        "change_type": change.change_type,
        "session": str(session.pk) if session else None,
        "date": session.date.isoformat() if session else None,
        "school_class": str(change.school_class_id) if change.school_class_id else None,
    }
    change_label = label("change_type", change.change_type)
    message = (
        text("schedule.message.dated", change=change_label, date=f"{session.date:%d/%m/%Y}")
        if session
        else text("schedule.message", change=change_label)
    )
    common = {
        "school": change.school,
        "notification_type": kind,
        "event_key": f"schedule_change:{change.pk}",
        "source": change,
    }
    teachers = [
        t.employee.membership
        for t in TeacherProfile.objects.filter(pk__in=change.teacher_ids, school=change.school).select_related(
            "employee__membership"
        )
    ]
    created = notify_many(
        teachers,
        title=text("schedule.teacher.title", change=change_label),
        message=message,
        payload={**facts, "reason": change.reason},
        **common,
    )
    if change.school_class_id:
        students = Student.objects.filter(
            enrollments__school_class_id=change.school_class_id, enrollments__status=EnrollmentStatus.ACTIVE
        )
        parents = [p for s in students for p in parents_to_inform(s)]
        created += notify_many(
            parents,
            title=text("schedule.parent.title", change=change_label),
            message=message,
            payload=facts,
            **common,
        )
    ScheduleChange.objects.filter(pk=change.pk).update(
        notification_status=NotificationStatus.SENT, notified_at=timezone.now()
    )
    return created


def _amount_label(amount, currency):
    whole = amount == amount.to_integral_value()
    text = f"{amount:,.0f}" if whole else f"{amount:,.2f}"
    return f"{text.replace(',', ' ').replace('.', ',')} {currency}"


def _is_parent_mobile_payment(payment):
    """Paid by a parent with their own wallet: the parent app's path
    (the administration records counter payments as CASH)."""
    return payment.payment_method == PaymentMethod.WALLET and membership_has_role(payment.payer, {"PARENT"})


def project_payment(payment):
    if payment.status != PaymentStatus.SUCCEEDED and payment.status not in FAILED_STATUSES:
        return []
    ok = payment.status == PaymentStatus.SUCCEEDED
    created = _notify_payer(payment, ok)
    if ok and _is_parent_mobile_payment(payment):
        created += _notify_finance_admins(payment)
    return created


def _notify_finance_admins(payment):
    """A confirmed parent payment -> the administrators of THE SAME school,
    i.e. the members Finance itself lets see payments (ADMIN / SUPER_ADMIN,
    finance.services._is_admin). Runs after the payment's commit, only on
    SUCCEEDED: a refused, failed or rolled-back attempt never gets here.
    One notification per (admin, payment): replays add nothing (event_key)."""
    invoices = list(
        payment.allocations.select_related("invoice")
        .order_by("invoice__invoice_number")
        .values_list("invoice__invoice_number", "invoice_id")
    )
    numbers = [number for number, _ in invoices]
    if numbers:
        about = text("payment.admin.invoices", n=len(numbers), numbers=", ".join(numbers))
    else:
        # a fee type's name is the school's data: shown as it is
        about = payment.fee_type.name if payment.fee_type_id else text("payment.admin.free")
    amount = _amount_label(payment.amount, payment.currency)
    when = timezone.localtime(payment.completed_at or payment.initiated_at)
    return notify_many(
        administrators(payment.school),
        school=payment.school,
        notification_type=NotificationType.PAYMENT,
        title=text("payment.admin.title", about=about, amount=amount),
        message=text(
            "payment.admin.message",
            student=payment.student.full_name,
            reference=payment.payment_reference,
            date=f"{when:%d/%m/%Y}",
            time=f"{when:%H:%M}",
        ),
        event_key=f"payment.admin:{payment.pk}",
        payload={
            "payment": str(payment.pk),
            "reference": payment.payment_reference,
            "status": payment.status,
            "amount": str(payment.amount),
            "currency": payment.currency,
            "student": str(payment.student_id),
            "invoices": [str(invoice_id) for _, invoice_id in invoices],
        },
        source=payment,
    )


def _notify_payer(payment, ok):
    return notify_many(
        [payment.payer],
        school=payment.school,
        notification_type=NotificationType.PAYMENT,
        severity=Severity.INFO if ok else Severity.WARNING,
        title=text("payment.confirmed.title" if ok else "payment.failed.title"),
        message=text(
            "payment.payer.message",
            reference=payment.payment_reference,
            amount=payment.amount,
            currency=payment.currency,
            status=label("payment_status", payment.status, lower=True),
        ),
        event_key=f"payment:{payment.pk}:{payment.status}",
        payload={
            "payment": str(payment.pk),
            "reference": payment.payment_reference,
            "status": payment.status,
            "amount": str(payment.amount),
            "student": str(payment.student_id),
        },
        source=payment,
    )


def project_refund(refund):
    payment = refund.payment
    return notify_many(
        [payment.payer],
        school=refund.school,
        notification_type=NotificationType.REFUND,
        title=text("refund.title"),
        message=text(
            "refund.message", amount=refund.amount, currency=payment.currency, reference=payment.payment_reference
        ),
        event_key=f"refund:{refund.pk}",
        payload={"refund": str(refund.pk), "payment": str(payment.pk), "amount": str(refund.amount)},
        source=refund,
    )


def project_payroll(payroll):
    if payroll.status not in (PayrollStatus.APPROVED, PayrollStatus.PAID):
        return []
    employee = payroll.teacher.employee if isinstance(payroll, TeacherPayroll) else payroll.staff.employee
    paid = payroll.status == PayrollStatus.PAID
    return notify_many(
        [employee.membership],
        school=payroll.school,
        notification_type=NotificationType.PAYROLL,
        title=text("payroll.paid.title" if paid else "payroll.approved.title"),
        message=text(
            "payroll.paid.message" if paid else "payroll.approved.message",
            period=payroll.payroll_period.name,
            amount=payroll.approved_amount,
            currency=payroll.currency,
        ),
        event_key=f"payroll:{payroll.pk}:{payroll.status}",
        payload={
            "payroll": str(payroll.pk),
            "status": payroll.status,
            "amount": str(payroll.approved_amount),
            "period": str(payroll.payroll_period_id),
        },
        source=payroll,
    )


def project_report_card(card):
    if card.status != ReportCardStatus.VALIDATED:
        return []
    return notify_many(
        parents_to_inform(card.student),
        school=card.school,
        notification_type=NotificationType.REPORT_CARD,
        title=text("report_card.title", student=card.student.full_name),
        message=text("report_card.message", period=card.academic_period.name),
        event_key=f"report_card:{card.pk}",
        payload={"report_card": str(card.pk), "student": str(card.student_id), "period": str(card.academic_period_id)},
        source=card,
    )


def project_finalized_day(audit):
    """Bulk path of attendance: the day's ABSENT records were written by
    bulk_create / update (no signal); the audit row of the finalisation
    carries the date."""
    if audit.action != "ATTENDANCE_DAY_FINALIZED" or audit.school_id is None:
        return []
    day = date.fromisoformat(str(audit.new_data.get("date")))
    created = []
    for record in StudentDailyAttendance.objects.filter(school_id=audit.school_id, date=day, status=DailyStatus.ABSENT):
        created += project_attendance(record)
    return created


PROJECTORS = {
    StudentDailyAttendance: project_attendance,
    Convocation: project_convocation,
    ScheduleChange: project_schedule_change,
    Payment: project_payment,
    PaymentRefund: project_refund,
    TeacherPayroll: project_payroll,
    StaffPayroll: project_payroll,
    ReportCard: project_report_card,
    AuditLog: project_finalized_day,
}


# =============================================================================
# Wiring
# =============================================================================


def dispatch(model, pk):
    """Re-read the committed source row and project it. Never raises: the
    source change is already committed; a failure is logged and can be
    replayed with `manage.py dispatch_notifications`."""
    try:
        with transaction.atomic():
            instance = model.objects.filter(pk=pk).first()
            if instance is None:
                return []
            return PROJECTORS[model](instance)
    except Exception:
        logger.exception("Notification projection failed for %s %s", model._meta.label, pk)
        return []


def _receiver(sender, instance, **kwargs):
    if sender is AuditLog and instance.action != "ATTENDANCE_DAY_FINALIZED":
        return  # cheap filter: the only audit row listened to
    pk = instance.pk
    transaction.on_commit(lambda: dispatch(sender, pk))


def connect():
    for model in PROJECTORS:
        post_save.connect(_receiver, sender=model, dispatch_uid=f"communication.{model._meta.label}")


def replay(school, since):
    """Re-project every source row of `school` touched since `since`
    (idempotent). Used by the dispatch_notifications command."""
    created = 0
    sources = [
        (StudentDailyAttendance.objects.filter(school=school, date__gte=since.date()), project_attendance),
        (Convocation.objects.filter(school=school, updated_at__gte=since), project_convocation),
        (
            ScheduleChange.objects.filter(school=school, notification_status=NotificationStatus.PENDING),
            project_schedule_change,
        ),
        (Payment.objects.filter(school=school, updated_at__gte=since), project_payment),
        (PaymentRefund.objects.filter(school=school, created_at__gte=since), project_refund),
        (TeacherPayroll.objects.filter(school=school, updated_at__gte=since), project_payroll),
        (StaffPayroll.objects.filter(school=school, updated_at__gte=since), project_payroll),
        (ReportCard.objects.filter(school=school, updated_at__gte=since), project_report_card),
    ]
    for queryset, projector in sources:
        for row in queryset:
            with transaction.atomic():
                created += len(projector(row))
    return created
