"""Payroll services and database guarantees (ADR 0014)."""

import threading
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction

from apps.audit.models import AuditLog
from apps.finance import services as fin
from apps.finance.models import TreasuryTransaction, WalletTransaction
from apps.payroll import services as pay
from apps.payroll.models import (
    LineKind,
    PayrollLine,
    PayrollSettlement,
    PayrollStatus,
    SalaryAdjustment,
    StaffPayroll,
    TeacherCompensationProfile,
    TeacherPayroll,
    TeacherSessionCheckIn,
)
from apps.scheduling import services as planning
from apps.scheduling.models import TeachingSession

from .conftest import DB
from .factories import SchoolFactory, admin_of
from .payroll_world import make_payroll_world, session
from .planning_world import MONDAY, at

pytestmark = DB
D = Decimal


@pytest.fixture
def w(school):
    return make_payroll_world(school)


def rule(exc):
    return exc.value.code


def validate(w, *sessions, **kw):
    return [pay.validate_session(s, actor=w.admin, **kw) for s in sessions]


def teacher_payroll(w, period=None):
    return TeacherPayroll.objects.exclude(status="CANCELLED").get(teacher=w.tm, payroll_period=period or w.october)


def run(w, period=None):
    return pay.calculate_period(period or w.october, actor=w.admin)


def approve_and_pay(w, payroll, method="CASH", wallet=None):
    pay.approve_payroll(payroll, actor=w.admin)
    return pay.pay_payroll(payroll, actor=w.admin, payout_method=method, wallet=wallet)


def current_lines(payroll, kind=None):
    lines = PayrollLine.objects.filter(teacher_payroll=payroll, version=payroll.version)
    return lines.filter(kind=kind) if kind else lines


# =============================================================================
# Payability
# =============================================================================


def test_validated_session_is_payable_and_correctly_priced(w):
    s0, s1 = w.sessions[0], w.sessions[1]
    validate(w, s0)
    # Late start: 90 minutes actually taught.
    validate(w, s1, actual_start=at(8, 30, day=s1.date), actual_end=at(10, 0, day=s1.date))
    run(w)
    payroll = teacher_payroll(w)
    earned = {line.teaching_session_id: line.amount for line in current_lines(payroll, LineKind.EARNED)}
    assert earned == {s0.pk: D("5000.00"), s1.pk: D("3750.00")}  # 5000 x 120/120, 5000 x 90/120
    assert (payroll.earned_amount, payroll.payable_sessions_count) == (D("8750.00"), 2)
    s0.refresh_from_db()
    assert s0.status == "COMPLETED" and pay.is_payable(s0)


def test_cancelled_session_is_never_payable(w):
    cancelled = w.sessions[3]
    with pytest.raises(ValidationError) as exc:
        pay.validate_session(cancelled, actor=w.admin)
    assert rule(exc) == "session_cancelled"
    run(w)
    payroll = teacher_payroll(w)
    assert not current_lines(payroll).filter(teaching_session=cancelled).exists()
    # Even raw SQL cannot validate it or write it as programmed / earned.
    with pytest.raises(IntegrityError), transaction.atomic():
        TeacherSessionCheckIn.objects.create(
            school=w.school,
            teaching_session=cancelled,
            teacher=w.tm,
            verified_status="VALIDATED",
            verified_at=cancelled.scheduled_end,
            verified_by=w.admin,
        )
    with pytest.raises(IntegrityError), transaction.atomic():
        PayrollLine.objects.create(
            school=w.school,
            teacher_payroll=payroll,
            version=payroll.version,
            kind=LineKind.PROGRAMMED,
            teacher=w.tm,
            teaching_session=cancelled,
            teacher_profile=w.rate,
            duration_minutes=120,
            vacation_minutes=120,
            rate=D("5000"),
            amount=D("5000.00"),
        )


def test_non_validated_session_is_not_payable(w):
    s0, s1, s2 = w.sessions[:3]
    pay.self_check_in(s0, actor=w.tm_member, status="PRESENT")  # declared, not verified
    pay.reject_session(s1, actor=w.admin, reason="Absent")
    validate(w, s2)
    run(w)
    payroll = teacher_payroll(w)
    assert [line.teaching_session_id for line in current_lines(payroll, LineKind.EARNED)] == [s2.pk]
    assert not pay.is_payable(TeachingSession.objects.get(pk=s0.pk))
    # A forged EARNED line for the non-validated session is refused by PostgreSQL.
    check_in = TeacherSessionCheckIn.objects.get(teaching_session=s0)
    with pytest.raises(IntegrityError), transaction.atomic():
        PayrollLine.objects.create(
            school=w.school,
            teacher_payroll=payroll,
            version=payroll.version,
            kind=LineKind.EARNED,
            teacher=w.tm,
            teaching_session=s0,
            check_in=check_in,
            teacher_profile=w.rate,
            duration_minutes=120,
            vacation_minutes=120,
            rate=D("5000"),
            amount=D("5000.00"),
        )


def test_completed_is_not_enough_only_the_administrative_validation_pays(w):
    """Mutation target: a session marked COMPLETED by another path (future
    call sheets, a script) but not validated by the administration —
    self-reported only, or with no check-in at all — earns nothing."""
    s0, s1, s2 = w.sessions[:3]
    pay.self_check_in(s0, actor=w.tm_member, status="PRESENT")
    TeachingSession.objects.filter(pk__in=[s0.pk, s1.pk]).update(status="COMPLETED")
    validate(w, s2)
    run(w)
    payroll = teacher_payroll(w)
    assert [line.teaching_session_id for line in current_lines(payroll, LineKind.EARNED)] == [s2.pk]
    assert (payroll.completed_sessions_count, payroll.payable_sessions_count) == (3, 1)


def test_validation_rules(w, monkeypatch):
    with monkeypatch.context() as m:  # 09:00 during the first session: not over yet
        m.setattr(pay.timezone, "now", lambda: at(9, 0, day=MONDAY))
        with pytest.raises(ValidationError) as exc:
            pay.validate_session(w.sessions[0], actor=w.admin)
        assert rule(exc) == "session_not_finished"
    validate(w, w.sessions[0])
    with pytest.raises(ValidationError) as exc:
        pay.validate_session(w.sessions[0], actor=w.admin)
    assert rule(exc) == "session_already_validated"
    with pytest.raises(PermissionDenied):
        pay.validate_session(w.sessions[1], actor=w.tm_member)
    with pytest.raises(PermissionDenied):
        pay.self_check_in(w.sessions[1], actor=w.tf_member, status="PRESENT")  # not their session
    log = AuditLog.objects.get(action="SESSION_VALIDATED")
    assert (log.actor, log.new_data["duration_minutes"]) == (w.admin, 120)


def test_a_validated_session_is_frozen(w):
    s0 = w.sessions[0]
    validate(w, s0)
    with pytest.raises(ValidationError):  # scheduling refuses: no longer SCHEDULED
        planning.cancel_session(s0, actor=w.admin, reason="x")
    for change in ({"status": "CANCELLED"}, {"scheduled_end": at(11, day=s0.date)}, {"teacher": w.tf}):
        with pytest.raises(IntegrityError), transaction.atomic():
            TeachingSession.objects.filter(pk=s0.pk).update(**change)


# =============================================================================
# The five states: programmed, earned, prepared, approved, paid
# =============================================================================


def test_programmed_earned_prepared_approved_paid(w):
    wallet = fin.create_wallet(w.tm_member, actor=w.admin, provider_code="FAKE_MTN", wallet_identifier="677000001")
    validate(w, *w.sessions[:2])
    summary = run(w)
    assert summary["created"] == 2  # tm + staff
    payroll = teacher_payroll(w)
    # programmed: 3 non-cancelled sessions; earned: the 2 validated.
    assert (payroll.programmed_amount, payroll.earned_amount, payroll.net_amount) == (
        D("15000.00"),
        D("10000.00"),
        D("10000.00"),
    )
    assert (payroll.scheduled_sessions_count, payroll.completed_sessions_count) == (3, 2)
    assert payroll.status == PayrollStatus.CALCULATED  # prepared
    pay.approve_payroll(payroll, actor=w.admin)
    payroll.refresh_from_db()
    assert (payroll.status, payroll.approved_amount, payroll.approved_by) == ("APPROVED", D("10000.00"), w.admin)
    pay.pay_payroll(payroll, actor=w.admin, payout_method="WALLET", wallet=wallet)
    payroll.refresh_from_db()
    wallet.refresh_from_db()
    assert payroll.status == "PAID" and payroll.payment_reference.startswith("PAYR-")
    assert wallet.balance == D("10000.00")
    assert fin.get_treasury(w.school).balance == D("990000.00")
    debit = TreasuryTransaction.objects.get(reference=payroll.payment_reference)
    assert (debit.transaction_type, debit.direction, debit.amount) == ("PAYROLL", "DEBIT", D("10000.00"))
    assert WalletTransaction.objects.get(reference=payroll.payment_reference).direction == "CREDIT"
    assert set(PayrollSettlement.objects.values_list("teaching_session_id", flat=True)) == {
        w.sessions[0].pk,
        w.sessions[1].pk,
    }
    assert pay.reconstruct(payroll)
    actions = list(
        AuditLog.objects.filter(entity_id=payroll.pk).order_by("created_at").values_list("action", flat=True)
    )
    assert actions == ["PAYROLL_CALCULATED", "PAYROLL_APPROVED", "PAYROLL_PAID"]


def test_staff_fixed_salary(w):
    run(w)
    staff_payroll = StaffPayroll.objects.get(staff=w.staff, payroll_period=w.october)
    assert (staff_payroll.base_salary, staff_payroll.gross_amount) == (D("150000.00"), D("150000.00"))
    approve_and_pay(w, staff_payroll)
    staff_payroll.refresh_from_db()
    assert staff_payroll.status == "PAID" and fin.get_treasury(w.school).balance == D("850000.00")


def test_calculation_is_idempotent_and_versions_are_kept(w):
    validate(w, w.sessions[0])
    run(w)
    assert run(w)["unchanged"] == 2
    payroll = teacher_payroll(w)
    assert payroll.version == 1
    validate(w, w.sessions[1])
    assert run(w)["recalculated"] == 1
    payroll.refresh_from_db()
    assert (payroll.version, payroll.earned_amount) == (2, D("10000.00"))
    # Version 1 is kept as the trace of the first calculation.
    assert PayrollLine.objects.filter(teacher_payroll=payroll, version=1, kind="EARNED").count() == 1
    assert PayrollLine.objects.filter(teacher_payroll=payroll, version=2, kind="EARNED").count() == 2


def test_approval_refuses_a_stale_calculation(w):
    validate(w, w.sessions[0])
    run(w)
    validate(w, w.sessions[1])  # sources changed after the calculation
    with pytest.raises(ValidationError) as exc:
        pay.approve_payroll(teacher_payroll(w), actor=w.admin)
    assert rule(exc) == "payroll_stale"
    run(w)
    pay.approve_payroll(teacher_payroll(w), actor=w.admin)


def test_payment_requires_approval_and_amounts_freeze(w):
    validate(w, w.sessions[0])
    run(w)
    payroll = teacher_payroll(w)
    with pytest.raises(ValidationError) as exc:
        pay.pay_payroll(payroll, actor=w.admin, payout_method="CASH")
    assert rule(exc) == "payroll_not_approved"
    pay.approve_payroll(payroll, actor=w.admin)
    with pytest.raises(IntegrityError), transaction.atomic():
        TeacherPayroll.objects.filter(pk=payroll.pk).update(net_amount=D("99999"), earned_amount=D("99999"))
    with pytest.raises(IntegrityError), transaction.atomic():
        TeacherPayroll.objects.filter(pk=payroll.pk).update(status="CALCULATED")


# =============================================================================
# Rates
# =============================================================================


def test_rate_change_is_dated_and_never_rewrites_history(w):
    s0, s1, s2 = w.sessions[:3]
    validate(w, s0, s1, s2)
    new = pay.set_teacher_rate(w.tm, actor=w.admin, academic_year=w.year, vacation_rate="6000", effective_from=s2.date)
    w.rate.refresh_from_db()
    assert w.rate.effective_to == s1.date and new.effective_to is None
    run(w)
    earned = {line.teaching_session_id: line.amount for line in current_lines(teacher_payroll(w), "EARNED")}
    assert earned == {s0.pk: D("5000.00"), s1.pk: D("5000.00"), s2.pk: D("6000.00")}
    # A rate row is never edited in place.
    with pytest.raises(IntegrityError), transaction.atomic():
        TeacherCompensationProfile.objects.filter(pk=new.pk).update(vacation_rate=D("1"))
    with pytest.raises(IntegrityError), transaction.atomic():
        TeacherCompensationProfile.objects.filter(pk=new.pk).delete()
    assert AuditLog.objects.filter(action="TEACHER_RATE_SET", entity_id=new.pk).exists()


def test_rate_cannot_be_changed_under_a_paid_payroll(w):
    validate(w, *w.sessions[:2])
    run(w)
    approve_and_pay(w, teacher_payroll(w))
    with pytest.raises(ValidationError) as exc:
        pay.set_teacher_rate(
            w.tm, actor=w.admin, academic_year=w.year, vacation_rate="9000", effective_from=date(2025, 10, 7)
        )
    assert rule(exc) == "rate_locked_by_payroll"
    # After the paid sessions it is fine.
    pay.set_teacher_rate(
        w.tm, actor=w.admin, academic_year=w.year, vacation_rate="9000", effective_from=date(2025, 11, 1)
    )


def test_missing_rate_is_reported_not_guessed(w):
    tf_session = session(w, date(2025, 10, 13), course=w.course_french)
    validate(w, tf_session)
    summary = run(w)
    assert {"code": "missing_rate", "session": str(tf_session.pk), "date": "2025-10-13"} in summary["warnings"]
    assert not TeacherPayroll.objects.filter(teacher=w.tf).exists()


# =============================================================================
# Periods
# =============================================================================


def test_closing_a_period(w):
    validate(w, w.sessions[0])
    run(w)
    with pytest.raises(ValidationError) as exc:
        pay.close_period(w.october, actor=w.admin)
    assert rule(exc) == "period_not_settled"
    approve_and_pay(w, teacher_payroll(w))
    pay.cancel_payroll(StaffPayroll.objects.get(staff=w.staff), actor=w.admin, reason="payé hors période")
    pay.close_period(w.october, actor=w.admin)
    with pytest.raises(ValidationError) as exc:
        run(w)
    assert rule(exc) == "period_closed"
    with pytest.raises(IntegrityError), transaction.atomic():
        TeacherPayroll.objects.create(
            school=w.school, teacher=w.tf, payroll_period=w.october, calculated_at=w.october.closed_at
        )


def test_late_validation_is_paid_in_the_next_period_once(w):
    validate(w, w.sessions[0])
    run(w)
    approve_and_pay(w, teacher_payroll(w))
    pay.cancel_payroll(StaffPayroll.objects.get(staff=w.staff, payroll_period=w.october), actor=w.admin, reason="x")
    pay.close_period(w.october, actor=w.admin)
    validate(w, w.sessions[1])  # October session validated after closing
    run(w, w.november)
    november = teacher_payroll(w, w.november)
    late = current_lines(november, "EARNED").get()
    assert (late.teaching_session_id, late.late, late.amount) == (w.sessions[1].pk, True, D("5000.00"))
    assert november.programmed_amount == 0  # no November session programmed


def test_overlapping_periods_are_refused(w):
    with pytest.raises(ValidationError) as exc:
        pay.create_period(
            w.year, actor=w.admin, name="Mi-octobre", start_date=date(2025, 10, 15), end_date=date(2025, 11, 15)
        )
    assert rule(exc) == "period_overlap"


# =============================================================================
# Double payment / concurrency
# =============================================================================


def test_double_payment_is_impossible(w):
    validate(w, w.sessions[0])
    run(w)
    payroll = teacher_payroll(w)
    approve_and_pay(w, payroll)
    with pytest.raises(ValidationError) as exc:
        pay.pay_payroll(payroll, actor=w.admin, payout_method="CASH")
    assert rule(exc) == "payroll_already_paid"
    # A paid session never re-enters a calculation...
    run(w, w.november)
    assert not TeacherPayroll.objects.filter(payroll_period=w.november, teacher=w.tm).exists()
    # ...and the database refuses a second settlement of it.
    with pytest.raises(IntegrityError), transaction.atomic():
        PayrollSettlement.objects.create(
            school=w.school,
            teaching_session=w.sessions[0],
            teacher_payroll=payroll,
            line=current_lines(payroll, "EARNED").get(),
            amount=D("5000.00"),
            settled_at=payroll.paid_at,
        )
    assert TreasuryTransaction.objects.filter(transaction_type="PAYROLL").count() == 1


def test_concurrent_payments_pay_once(w):
    validate(w, *w.sessions[:3])
    run(w)
    payroll = teacher_payroll(w)
    pay.approve_payroll(payroll, actor=w.admin)
    results, errors = [], []
    barrier = threading.Barrier(2)

    def attempt():
        try:
            barrier.wait()
            results.append(pay.pay_payroll(payroll, actor=w.admin, payout_method="CASH"))
        except ValidationError as exc:
            errors.append(exc.code)
        finally:
            connection.close()

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert (len(results), errors) == (1, ["payroll_already_paid"])
    assert TreasuryTransaction.objects.filter(transaction_type="PAYROLL").count() == 1
    assert fin.get_treasury(w.school).balance == D("985000.00")


def test_concurrent_calculations_create_one_payroll(w):
    validate(w, w.sessions[0])
    errors = []

    def attempt():
        try:
            run(w)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert TeacherPayroll.objects.filter(teacher=w.tm, payroll_period=w.october).count() == 1


def test_insufficient_treasury_keeps_the_payroll_approved(w):
    validate(w, w.sessions[0])
    run(w)
    payroll = teacher_payroll(w)
    pay.approve_payroll(payroll, actor=w.admin)
    with transaction.atomic():  # the treasury is (almost) empty
        treasury = fin.get_treasury(w.school)
        fin._post(
            treasury,
            transaction_type="PAYROLL",
            direction="DEBIT",
            amount=treasury.balance - D("10"),
            reference="DRAIN",
            actor=w.admin,
        )
    with pytest.raises(ValidationError) as exc:
        pay.pay_payroll(payroll, actor=w.admin, payout_method="CASH")
    assert rule(exc) == "insufficient_balance"
    payroll.refresh_from_db()
    assert payroll.status == "APPROVED" and not PayrollSettlement.objects.exists()


def test_salary_goes_only_to_the_employees_own_wallet(w):
    validate(w, w.sessions[0])
    run(w)
    payroll = teacher_payroll(w)
    pay.approve_payroll(payroll, actor=w.admin)
    someone_else = fin.create_wallet(w.tf_member, actor=w.admin, provider_code="FAKE_MTN", wallet_identifier="1")
    with pytest.raises(PermissionDenied):
        pay.pay_payroll(payroll, actor=w.admin, payout_method="WALLET", wallet=someone_else)


# =============================================================================
# Corrections
# =============================================================================


def test_revoking_a_paid_validation_creates_a_traced_correction(w):
    s0, s1 = w.sessions[:2]
    validate(w, s0)
    run(w)
    paid = teacher_payroll(w)
    approve_and_pay(w, paid)
    pay.reject_session(s0, actor=w.admin, reason="Enseignant absent, saisie erronée")
    adjustment = SalaryAdjustment.objects.get()
    assert (adjustment.amount, adjustment.source, adjustment.teaching_session) == (
        D("-5000.00"),
        "VALIDATION_REVOKED",
        s0,
    )
    # The payment, its settlement and its lines stay untouched in history.
    paid.refresh_from_db()
    assert paid.status == "PAID" and PayrollSettlement.objects.filter(teaching_session=s0).exists()
    # Next period: the recovery is deducted from two November sessions.
    validate(w, session(w, date(2025, 11, 3)), session(w, date(2025, 11, 4)))
    run(w, w.november)
    november = teacher_payroll(w, w.november)
    assert (november.earned_amount, november.adjustments_amount, november.net_amount) == (
        D("10000.00"),
        D("-5000.00"),
        D("5000.00"),
    )
    approve_and_pay(w, november)
    adjustment.refresh_from_db()
    assert adjustment.settled_teacher_payroll == november
    revoked = AuditLog.objects.get(action="SESSION_VALIDATION_REVOKED")
    assert revoked.new_data["adjustment"] == str(adjustment.pk)
    # Revalidating a paid session is refused: corrections go through adjustments.
    with pytest.raises(ValidationError) as exc:
        pay.validate_session(s0, actor=w.admin)
    assert rule(exc) == "session_already_paid"


def test_revocation_inside_an_approved_payroll_is_refused(w):
    validate(w, w.sessions[0])
    run(w)
    pay.approve_payroll(teacher_payroll(w), actor=w.admin)
    with pytest.raises(ValidationError) as exc:
        pay.reject_session(w.sessions[0], actor=w.admin, reason="erreur")
    assert rule(exc) == "session_in_approved_payroll"


def test_manual_adjustments_and_deferred_recovery(w):
    bonus = pay.create_adjustment(w.staff.employee, actor=w.admin, amount="20000", reason="Prime de fin d'année")
    recovery = pay.create_adjustment(w.staff.employee, actor=w.admin, amount="-500000", reason="Trop-perçu")
    summary = run(w)
    staff = StaffPayroll.objects.get(staff=w.staff)
    assert (staff.base_salary, staff.adjustments_amount, staff.gross_amount) == (
        D("150000.00"),
        D("20000.00"),
        D("170000.00"),
    )
    assert {"code": "adjustment_deferred", "adjustment": str(recovery.pk)} in summary["warnings"]
    approve_and_pay(w, staff)
    bonus.refresh_from_db()
    recovery.refresh_from_db()
    assert bonus.settled_staff_payroll == staff and recovery.settled_staff_payroll is None
    with pytest.raises(IntegrityError), transaction.atomic():
        SalaryAdjustment.objects.filter(pk=bonus.pk).update(amount=D("1"))
    with pytest.raises(IntegrityError), transaction.atomic():
        SalaryAdjustment.objects.filter(pk=recovery.pk).delete()


def test_cancel_and_recalculate_keeps_history(w):
    validate(w, w.sessions[0])
    run(w)
    first = teacher_payroll(w)
    pay.cancel_payroll(first, actor=w.admin, reason="erreur de période")
    run(w)
    second = teacher_payroll(w)
    assert second.pk != first.pk
    first.refresh_from_db()
    assert first.status == "CANCELLED" and PayrollLine.objects.filter(teacher_payroll=first).exists()


# =============================================================================
# History is append-only
# =============================================================================


def test_payroll_history_cannot_be_rewritten(w):
    validate(w, w.sessions[0])
    run(w)
    payroll = teacher_payroll(w)
    approve_and_pay(w, payroll)
    line = current_lines(payroll).first()
    for attempt in (
        lambda: PayrollLine.objects.filter(pk=line.pk).update(amount=D("1")),
        lambda: PayrollLine.objects.filter(pk=line.pk).delete(),
        lambda: PayrollSettlement.objects.all().delete(),
        lambda: TeacherPayroll.objects.filter(pk=payroll.pk).delete(),
        lambda: TeacherPayroll.objects.filter(pk=payroll.pk).update(status="CANCELLED", cancelled_reason="x"),
        lambda: TeacherSessionCheckIn.objects.all().delete(),
        lambda: type(w.october).objects.filter(pk=w.october.pk).delete(),
    ):
        with pytest.raises(IntegrityError), transaction.atomic():
            attempt()


# =============================================================================
# Isolation and rights
# =============================================================================


def test_school_isolation(w):
    other = make_payroll_world(SchoolFactory())
    validate(w, w.sessions[0])
    validate(other, other.sessions[0], other.sessions[1])
    run(w)
    assert not TeacherPayroll.objects.filter(school=other.school).exists()
    assert teacher_payroll(w).earned_amount == D("5000.00")
    foreign_admin = other.admin
    for call in (
        lambda: pay.validate_session(w.sessions[1], actor=foreign_admin),
        lambda: pay.calculate_period(w.october, actor=foreign_admin),
        lambda: pay.approve_payroll(teacher_payroll(w), actor=foreign_admin),
        lambda: pay.set_teacher_rate(
            w.tm, actor=foreign_admin, academic_year=w.year, vacation_rate="1", effective_from=date(2025, 12, 1)
        ),
        lambda: pay.create_adjustment(w.staff.employee, actor=foreign_admin, amount="1", reason="x"),
    ):
        with pytest.raises(PermissionDenied):
            call()
    # A rate of school B cannot point at a teacher of school A (composite FK).
    with pytest.raises(IntegrityError), transaction.atomic():
        TeacherCompensationProfile.objects.create(
            school=other.school,
            teacher=w.tm,
            academic_year=other.year,
            vacation_rate=D("1"),
            vacation_minutes=120,
            effective_from=date(2025, 12, 1),
        )


def test_only_admins_run_payroll(w):
    validate(w, w.sessions[0])
    for actor in (w.tm_member, w.staff.employee.membership, admin_of(SchoolFactory())):
        with pytest.raises(PermissionDenied):
            pay.calculate_period(w.october, actor=actor)
    run(w)
    for actor in (w.tm_member, w.staff.employee.membership):
        with pytest.raises(PermissionDenied):
            pay.approve_payroll(teacher_payroll(w), actor=actor)
        with pytest.raises(PermissionDenied):
            pay.cancel_payroll(teacher_payroll(w), actor=actor, reason="x")


def test_live_remuneration_summary(w):
    validate(w, *w.sessions[:2])
    run(w)
    approve_and_pay(w, teacher_payroll(w))
    validate(w, w.sessions[2])
    summary = pay.remuneration(w.tm.employee, date(2025, 10, 1), date(2025, 10, 31))
    assert (summary["programmed_amount"], summary["earned_unpaid_amount"], summary["paid_amount"]) == (
        D("15000.00"),
        D("5000.00"),
        D("10000.00"),
    )
    assert summary["sessions"] == {"scheduled": 3, "validated": 1, "paid": 2, "missing_rate": 0}
    assert pay.remuneration(w.staff.employee, date(2025, 10, 1), date(2025, 10, 31))["monthly_salary"] == D("150000.00")
    assert MONDAY == w.sessions[0].date
