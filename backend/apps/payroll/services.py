"""Payroll services (ADR 0014).

Locked decisions applied here:
- remuneration EARNED only by sessions VALIDATED by the administration
  (TeacherSessionCheckIn.verified_status = VALIDATED, session COMPLETED);
  a cancelled or non-validated session is never payable (also enforced by
  PostgreSQL triggers on the lines);
- programmed / earned / prepared / approved / paid are distinct states;
- the calculation is deterministic and reconstructible: `compute_*` is a pure
  function of (sessions, validations, dated rates, pending corrections) and
  `reconstruct()` re-runs it to prove a payroll still matches its sources;
- money moves only through Finance (treasury debit, wallet credit), with the
  same append-only ledgers as fee payments;
- nothing is deleted: recalculation = new line version, revocation after
  payment = SalaryAdjustment, every sensitive action is audited.

Rights: ADMIN / SUPER_ADMIN of the school for every write; employees only
read their own data (see api.py).
"""

import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit.models import AuditLayer
from apps.audit.services import record_audit
from apps.finance import services as finance
from apps.finance.models import AccountStatus, LedgerDirection, LedgerType, Wallet
from apps.people.models import EmployeeProfile, StaffProfile, TeacherProfile
from apps.scheduling import services as scheduling
from apps.scheduling.models import SessionStatus, TeachingSession
from common.permissions import ADMIN_ROLES, require_role

from .models import (
    ZERO,
    AdjustmentSource,
    LineKind,
    PayoutMethod,
    PayrollLine,
    PayrollPeriod,
    PayrollSettlement,
    PayrollStatus,
    PeriodStatus,
    SalaryAdjustment,
    SelfReportStatus,
    StaffCompensationProfile,
    StaffPayroll,
    TeacherCompensationProfile,
    TeacherPayroll,
    TeacherSessionCheckIn,
    VerificationStatus,
)

CENT = Decimal("0.01")


def _admin(actor, school):
    require_role(actor, ADMIN_ROLES, school=school)


def _reason(reason):
    if not reason or not str(reason).strip():
        raise ValidationError("A reason is required.", code="reason_required")
    return str(reason).strip()


def _money(value, *, allow_negative=False):
    value = Decimal(str(value))
    if value.as_tuple().exponent < -2:
        raise ValidationError("Amounts have at most 2 decimals.", code="invalid_amount")
    if value == 0 or (value < 0 and not allow_negative):
        raise ValidationError("Invalid amount.", code="invalid_amount")
    return value.quantize(CENT)


def _audit(action, actor, entity, *, new=None, old=None, layer=AuditLayer.BUSINESS):
    record_audit(action, actor=actor, entity=entity, new=new, old=old, layer=layer)


def employee_of(membership):
    return EmployeeProfile.objects.filter(membership=membership).first() if membership else None


# =============================================================================
# Session validation (administrative) — on the existing TeachingSession
# =============================================================================


def _check_in(session):
    check_in, _ = TeacherSessionCheckIn.objects.get_or_create(
        teaching_session=session, defaults={"school": session.school, "teacher": session.teacher}
    )
    return TeacherSessionCheckIn.objects.select_for_update().get(pk=check_in.pk)


def _locked_session(session):
    return TeachingSession.objects.select_for_update().get(pk=session.pk)


@transaction.atomic
def self_check_in(session, *, actor, status):
    """Teacher's own declaration (spec §15: self-reported, then verified).
    It never makes a session payable on its own."""
    session = _locked_session(session)
    if session.teacher.employee.membership_id != actor.pk:
        raise PermissionDenied("Only the teacher of this session can check in.")
    if status not in (SelfReportStatus.PRESENT, SelfReportStatus.ABSENT):
        raise ValidationError("Invalid status.", code="invalid_status")
    if session.status == SessionStatus.CANCELLED:
        raise ValidationError("This session was cancelled.", code="session_cancelled")
    if session.scheduled_start > timezone.now():
        raise ValidationError("A session cannot be checked in before it starts.", code="session_not_started")
    check_in = _check_in(session)
    if check_in.verified_status != VerificationStatus.PENDING:
        raise ValidationError("This session has already been verified.", code="checkin_already_verified")
    check_in.self_reported_status, check_in.self_reported_at = status, timezone.now()
    check_in.save()
    _audit("SESSION_SELF_CHECKIN", actor, check_in, new={"status": status})
    return check_in


@transaction.atomic
def validate_session(session, *, actor, actual_start=None, actual_end=None, reason=None):
    """Administrative validation: the session was really taught -> COMPLETED
    and payable. Optional actual times (late start, early end) become the
    paid duration."""
    _admin(actor, session.school)
    session = _locked_session(session)
    if session.status == SessionStatus.CANCELLED:
        raise ValidationError("A cancelled session is never payable.", code="session_cancelled")
    if session.scheduled_end > timezone.now():
        raise ValidationError("A session can only be validated once it is over.", code="session_not_finished")
    if (actual_start is None) != (actual_end is None) or (actual_start and actual_end <= actual_start):
        raise ValidationError("Give both actual times, end after start.", code="invalid_times")
    if PayrollSettlement.objects.filter(teaching_session=session).exists():
        raise ValidationError("This session was already paid; use a salary adjustment.", code="session_already_paid")
    check_in = _check_in(session)
    if check_in.verified_status == VerificationStatus.VALIDATED:
        raise ValidationError("This session is already validated.", code="session_already_validated")
    old = {"verified_status": check_in.verified_status, "session_status": session.status}
    if actual_start is not None:
        session.actual_start, session.actual_end = actual_start, actual_end
    session.status = SessionStatus.COMPLETED
    session.save(update_fields=["status", "actual_start", "actual_end", "updated_at"])
    check_in.verified_status = VerificationStatus.VALIDATED
    check_in.verified_at, check_in.verified_by = timezone.now(), actor
    check_in.verification_reason = reason.strip() if reason else None
    check_in.save()
    _audit(
        "SESSION_VALIDATED",
        actor,
        check_in,
        old=old,
        new={"verified_status": "VALIDATED", "duration_minutes": duration_minutes(session)},
    )
    return check_in


@transaction.atomic
def reject_session(session, *, actor, reason):
    """Not taught (or validated by mistake): never payable.

    Revoking a validation is a CORRECTION:
    - in a prepared payroll: allowed, the payroll becomes stale and must be
      recalculated before approval (approve() checks it);
    - in an approved, unpaid payroll: refused — cancel that payroll first;
    - already paid: the payment stays in history, a negative
      SalaryAdjustment is created and deducted from the next payroll."""
    _admin(actor, session.school)
    reason = _reason(reason)
    session = _locked_session(session)
    check_in = _check_in(session)
    previous = check_in.verified_status
    if previous == VerificationStatus.REJECTED:
        raise ValidationError("This session is already rejected.", code="session_already_rejected")
    if (
        previous == VerificationStatus.VALIDATED
        and PayrollLine.objects.filter(
            teaching_session=session, kind=LineKind.EARNED, teacher_payroll__status=PayrollStatus.APPROVED
        ).exists()
    ):
        raise ValidationError(
            "This session is in an approved payroll: cancel that payroll first.", code="session_in_approved_payroll"
        )
    check_in.verified_status, check_in.verification_reason = VerificationStatus.REJECTED, reason
    check_in.verified_at, check_in.verified_by = timezone.now(), actor
    check_in.save()
    if session.status == SessionStatus.COMPLETED:
        session.status = SessionStatus.SCHEDULED
        session.save(update_fields=["status", "updated_at"])
        scheduling._check_now()  # back among scheduled sessions: overlaps re-checked now
    adjustment = None
    settlement = PayrollSettlement.objects.filter(teaching_session=session).first()
    if settlement is not None:
        adjustment = SalaryAdjustment.objects.create(
            school=session.school,
            employee=session.teacher.employee,
            amount=-settlement.amount,
            reason=f"Validation retirée après paiement : {reason}",
            effective_date=timezone.localdate(),
            source=AdjustmentSource.VALIDATION_REVOKED,
            teaching_session=session,
            approved_by=actor,
        )
    _audit(
        "SESSION_VALIDATION_REVOKED" if previous == VerificationStatus.VALIDATED else "SESSION_REJECTED",
        actor,
        check_in,
        old={"verified_status": previous},
        new={"verified_status": "REJECTED", "reason": reason, "adjustment": str(adjustment.pk) if adjustment else None},
    )
    return check_in


def duration_minutes(session):
    """Paid duration: actual times when the administration recorded them,
    else the scheduled times."""
    start = session.actual_start or session.scheduled_start
    end = session.actual_end or session.scheduled_end
    return int((end - start).total_seconds() // 60)


def session_amount(rate, minutes, vacation_minutes):
    """amount = ROUND(rate x minutes / vacation_minutes, 2) — the same
    formula PostgreSQL re-checks on every line."""
    return (rate * minutes / vacation_minutes).quantize(CENT, rounding=ROUND_HALF_UP)


def is_payable(session):
    check_in = getattr(session, "check_in", None)
    return (
        session.status == SessionStatus.COMPLETED
        and check_in is not None
        and check_in.verified_status == VerificationStatus.VALIDATED
    )


# =============================================================================
# Rates (dated, never edited)
# =============================================================================


def teacher_rate_for(teacher, day):
    return (
        TeacherCompensationProfile.objects.filter(teacher=teacher, active=True, effective_from__lte=day)
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=day))
        .first()
    )


def staff_salary_for(staff, day):
    return (
        StaffCompensationProfile.objects.filter(staff=staff, active=True, effective_from__lte=day)
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=day))
        .first()
    )


def _replace_dated(model, owner_filter, effective_from, *, used_after):
    """End the current rate the day before `effective_from` (or deactivate it
    when it starts that very day). Refused if an approved or paid payroll
    already used it on or after that date: paid history is never re-priced."""
    current = list(
        model.objects.select_for_update()
        .filter(active=True, **owner_filter)
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=effective_from))
    )
    for profile in current:
        if profile.effective_from > effective_from:
            raise ValidationError("A later rate already exists.", code="rate_overlap")
        if used_after(profile):
            raise ValidationError(
                "An approved or paid payroll already used this rate after that date.", code="rate_locked_by_payroll"
            )
        if profile.effective_from == effective_from:
            profile.active = False
        else:
            profile.effective_to = effective_from - timedelta(days=1)
        profile.save()
    return current


@transaction.atomic
def set_teacher_rate(teacher, *, actor, academic_year, vacation_rate, effective_from):
    _admin(actor, teacher.school)
    rate = _money(vacation_rate)
    if academic_year.school_id != teacher.school_id or not (
        academic_year.start_date <= effective_from <= academic_year.end_date
    ):
        raise ValidationError("The rate must start inside the academic year.", code="outside_year")

    def used_after(profile):
        return PayrollLine.objects.filter(
            teacher_profile=profile,
            session_date__gte=effective_from,
            teacher_payroll__status__in=[PayrollStatus.APPROVED, PayrollStatus.PAID],
        ).exists()

    replaced = _replace_dated(TeacherCompensationProfile, {"teacher": teacher}, effective_from, used_after=used_after)
    profile = TeacherCompensationProfile.objects.create(
        school=teacher.school,
        teacher=teacher,
        academic_year=academic_year,
        vacation_rate=rate,
        vacation_minutes=teacher.school.configuration.teacher_vacation_duration_minutes,
        currency=teacher.school.currency,
        effective_from=effective_from,
        created_by=actor,
    )
    _audit(
        "TEACHER_RATE_SET",
        actor,
        profile,
        old={"replaced": [{"id": str(p.pk), "rate": str(p.vacation_rate)} for p in replaced]},
        new={
            "rate": str(rate),
            "effective_from": effective_from.isoformat(),
            "vacation_minutes": profile.vacation_minutes,
        },
    )
    return profile


@transaction.atomic
def set_staff_salary(staff, *, actor, monthly_salary, effective_from):
    _admin(actor, staff.school)
    salary = _money(monthly_salary)

    def used_after(profile):
        return PayrollLine.objects.filter(
            staff_profile=profile,
            staff_payroll__payroll_period__end_date__gte=effective_from,
            staff_payroll__status__in=[PayrollStatus.APPROVED, PayrollStatus.PAID],
        ).exists()

    replaced = _replace_dated(StaffCompensationProfile, {"staff": staff}, effective_from, used_after=used_after)
    profile = StaffCompensationProfile.objects.create(
        school=staff.school,
        staff=staff,
        monthly_salary=salary,
        currency=staff.school.currency,
        effective_from=effective_from,
        created_by=actor,
    )
    _audit(
        "STAFF_SALARY_SET",
        actor,
        profile,
        old={"replaced": [{"id": str(p.pk), "salary": str(p.monthly_salary)} for p in replaced]},
        new={"salary": str(salary), "effective_from": effective_from.isoformat()},
    )
    return profile


# =============================================================================
# Periods
# =============================================================================


@transaction.atomic
def create_period(academic_year, *, actor, name, start_date, end_date):
    _admin(actor, academic_year.school)
    if end_date < start_date or not (academic_year.start_date <= start_date and end_date <= academic_year.end_date):
        raise ValidationError("The period must lie inside the academic year.", code="outside_year")
    try:
        with transaction.atomic():
            period = PayrollPeriod.objects.create(
                school=academic_year.school,
                academic_year=academic_year,
                name=name.strip(),
                start_date=start_date,
                end_date=end_date,
            )
    except IntegrityError:
        raise ValidationError("This period overlaps another one or reuses its name.", code="period_overlap") from None
    _audit(
        "PAYROLL_PERIOD_CREATED",
        actor,
        period,
        layer=AuditLayer.ADMINISTRATIVE,
        new={"name": period.name, "start": start_date.isoformat(), "end": end_date.isoformat()},
    )
    return period


def _payrolls_of(period):
    return [*TeacherPayroll.objects.filter(payroll_period=period), *StaffPayroll.objects.filter(payroll_period=period)]


@transaction.atomic
def close_period(period, *, actor):
    """Final: every payroll paid or cancelled; nothing in it can change any
    more. Sessions of the period validated later are paid as catch-up
    ("late") lines in a following period."""
    _admin(actor, period.school)
    period = PayrollPeriod.objects.select_for_update().get(pk=period.pk)
    if period.status == PeriodStatus.CLOSED:
        raise ValidationError("This period is already closed.", code="period_closed")
    if any(p.status in (PayrollStatus.CALCULATED, PayrollStatus.APPROVED) for p in _payrolls_of(period)):
        raise ValidationError("Every payroll must be paid or cancelled first.", code="period_not_settled")
    period.status, period.closed_at, period.closed_by = PeriodStatus.CLOSED, timezone.now(), actor
    period.save()
    _audit("PAYROLL_PERIOD_CLOSED", actor, period, new={"name": period.name})
    return period


def _open_period(period):
    period = PayrollPeriod.objects.select_for_update().get(pk=period.pk)
    if period.status != PeriodStatus.OPEN:
        raise ValidationError("This payroll period is closed.", code="period_closed")
    return period


# =============================================================================
# Deterministic calculation
# =============================================================================


@dataclass
class Calculation:
    lines: list = field(default_factory=list)  # dicts, see _line()
    programmed_amount: Decimal = ZERO
    earned_amount: Decimal = ZERO
    base_salary: Decimal = ZERO
    adjustments_amount: Decimal = ZERO
    scheduled_count: int = 0
    completed_count: int = 0
    payable_count: int = 0
    warnings: list = field(default_factory=list)

    def signature(self):
        """What must not change between calculation and approval."""
        return sorted(
            (
                line["kind"],
                str(line.get("teaching_session") and line["teaching_session"].pk),
                str(line.get("teacher_profile") and line["teacher_profile"].pk),
                str(line.get("staff_profile") and line["staff_profile"].pk),
                str(line.get("adjustment") and line["adjustment"].pk),
                line.get("duration_minutes"),
                str(line["amount"]),
            )
            for line in self.lines
        )


def _late_eligible(school, day):
    """A session dated before the period is paid as catch-up only if its own
    period is closed (or none covers it): no double counting with a still
    open earlier period."""
    own = PayrollPeriod.objects.filter(school=school, start_date__lte=day, end_date__gte=day).first()
    return own is None or own.status == PeriodStatus.CLOSED


def _session_line(kind, session, profile, minutes, *, check_in=None, late=False):
    return {
        "kind": kind,
        "teaching_session": session,
        "check_in": check_in,
        "teacher_profile": profile,
        "session_date": session.date,
        "duration_minutes": minutes,
        "vacation_minutes": profile.vacation_minutes,
        "rate": profile.vacation_rate,
        "amount": session_amount(profile.vacation_rate, minutes, profile.vacation_minutes),
        "late": late,
    }


def _apply_adjustments(calc, employee, base, settled_by=None):
    """Pending corrections, oldest first, as long as the total stays >= 0
    (a recovery larger than the pay waits for the next period)."""
    adjustments = SalaryAdjustment.objects.filter(employee=employee).order_by("created_at", "id")
    if settled_by is not None and settled_by.status == PayrollStatus.PAID:
        key = "settled_teacher_payroll" if isinstance(settled_by, TeacherPayroll) else "settled_staff_payroll"
        adjustments = adjustments.filter(**{key: settled_by})
    else:
        adjustments = adjustments.filter(settled_teacher_payroll__isnull=True, settled_staff_payroll__isnull=True)
    total = base
    for adjustment in adjustments:
        if total + adjustment.amount < 0:
            calc.warnings.append({"code": "adjustment_deferred", "adjustment": str(adjustment.pk)})
            continue
        total += adjustment.amount
        calc.adjustments_amount += adjustment.amount
        calc.lines.append({"kind": LineKind.ADJUSTMENT, "adjustment": adjustment, "amount": adjustment.amount})


def compute_teacher(teacher, period, *, settled_by=None):
    """Pure calculation for one teacher and one period.

    `settled_by`: recompute a PAID payroll (its own settled sessions and
    corrections are then included) — used by reconstruct()."""
    calc = Calculation()
    in_period = TeachingSession.objects.filter(
        teacher=teacher, date__gte=period.start_date, date__lte=period.end_date
    ).select_related("check_in")
    for session in in_period.exclude(status=SessionStatus.CANCELLED).order_by("scheduled_start"):
        calc.scheduled_count += 1
        profile = teacher_rate_for(teacher, session.date)
        if profile is None:
            calc.warnings.append({"code": "missing_rate", "session": str(session.pk), "date": session.date.isoformat()})
            continue
        minutes = int((session.scheduled_end - session.scheduled_start).total_seconds() // 60)
        line = _session_line(LineKind.PROGRAMMED, session, profile, minutes)
        calc.lines.append(line)
        calc.programmed_amount += line["amount"]
    calc.completed_count = in_period.filter(status=SessionStatus.COMPLETED).count()

    # The ONLY payable sessions: validated by the administration, completed,
    # and not paid yet (or paid by `settled_by` when reconstructing it).
    payable = TeachingSession.objects.filter(
        teacher=teacher,
        status=SessionStatus.COMPLETED,
        check_in__verified_status=VerificationStatus.VALIDATED,
        date__lte=period.end_date,
    ).select_related("check_in")
    if settled_by is not None and settled_by.status == PayrollStatus.PAID:
        payable = payable.filter(payroll_settlement__teacher_payroll=settled_by)
    else:
        payable = payable.filter(payroll_settlement__isnull=True)
    for session in payable.order_by("scheduled_start"):
        late = session.date < period.start_date
        if late and not _late_eligible(teacher.school, session.date):
            continue
        profile = teacher_rate_for(teacher, session.date)
        if profile is None:
            calc.warnings.append({"code": "missing_rate", "session": str(session.pk), "date": session.date.isoformat()})
            continue
        line = _session_line(
            LineKind.EARNED, session, profile, duration_minutes(session), check_in=session.check_in, late=late
        )
        calc.lines.append(line)
        calc.earned_amount += line["amount"]
        calc.payable_count += 1
    _apply_adjustments(calc, teacher.employee, calc.earned_amount, settled_by)
    return calc


def compute_staff(staff, period, *, settled_by=None):
    calc = Calculation()
    profile = staff_salary_for(staff, period.end_date)
    if profile is None:
        calc.warnings.append({"code": "missing_salary", "staff": str(staff.pk)})
    else:
        calc.base_salary = profile.monthly_salary
        calc.lines.append({"kind": LineKind.SALARY, "staff_profile": profile, "amount": profile.monthly_salary})
    _apply_adjustments(calc, staff.employee, calc.base_salary, settled_by)
    return calc


def _current_signature(payroll):
    lines = PayrollLine.objects.filter(
        **{"teacher_payroll" if isinstance(payroll, TeacherPayroll) else "staff_payroll": payroll},
        version=payroll.version,
    ).select_related("teaching_session", "teacher_profile", "staff_profile", "adjustment")
    calc = Calculation(
        lines=[
            {
                "kind": line.kind,
                "teaching_session": line.teaching_session,
                "teacher_profile": line.teacher_profile,
                "staff_profile": line.staff_profile,
                "adjustment": line.adjustment,
                "duration_minutes": line.duration_minutes,
                "amount": line.amount,
            }
            for line in lines
        ]
    )
    return calc.signature()


def _compute(payroll, *, settled_by=None):
    if isinstance(payroll, TeacherPayroll):
        return compute_teacher(payroll.teacher, payroll.payroll_period, settled_by=settled_by)
    return compute_staff(payroll.staff, payroll.payroll_period, settled_by=settled_by)


def reconstruct(payroll):
    """True when the stored calculation still equals a fresh calculation
    from the sources (sessions + validations + rates + corrections)."""
    fresh = _compute(payroll, settled_by=payroll if payroll.status == PayrollStatus.PAID else None)
    return fresh.signature() == _current_signature(payroll)


def _write(payroll, calc, actor):
    owner = "teacher_payroll" if isinstance(payroll, TeacherPayroll) else "staff_payroll"
    payroll.adjustments_amount = calc.adjustments_amount
    payroll.calculated_at, payroll.calculated_by = timezone.now(), actor
    if isinstance(payroll, TeacherPayroll):
        payroll.programmed_amount, payroll.earned_amount = calc.programmed_amount, calc.earned_amount
        payroll.net_amount = calc.earned_amount + calc.adjustments_amount
        payroll.scheduled_sessions_count = calc.scheduled_count
        payroll.completed_sessions_count = calc.completed_count
        payroll.payable_sessions_count = calc.payable_count
    else:
        payroll.base_salary = calc.base_salary
        payroll.gross_amount = calc.base_salary + calc.adjustments_amount
    payroll.save()
    for line in calc.lines:
        PayrollLine.objects.create(
            school=payroll.school,
            version=payroll.version,
            teacher=payroll.teacher if owner == "teacher_payroll" and line.get("teaching_session") else None,
            **{owner: payroll},
            **{k: v for k, v in line.items() if k != "kind"},
            kind=line["kind"],
        )


def _employee_payroll_targets(period):
    """Teachers and staff concerned by the period: sessions in it, late
    validated sessions, a salary profile, or pending corrections."""
    school = period.school
    pending = SalaryAdjustment.objects.filter(
        school=school, settled_teacher_payroll__isnull=True, settled_staff_payroll__isnull=True
    ).values("employee_id")
    teachers = (
        TeacherProfile.objects.filter(school=school)
        .filter(
            Q(sessions__date__gte=period.start_date, sessions__date__lte=period.end_date)
            | Q(
                sessions__check_in__verified_status=VerificationStatus.VALIDATED,
                sessions__payroll_settlement__isnull=True,
                sessions__date__lt=period.start_date,
            )
            | Q(employee_id__in=pending)
        )
        .distinct()
    )
    staff = (
        StaffProfile.objects.filter(school=school)
        .filter(
            Q(employee_id__in=pending)
            | Q(
                compensation__active=True,
                compensation__effective_from__lte=period.end_date,
            )
        )
        .exclude(employee__teacher_profile__isnull=False)
        .distinct()
    )
    return list(teachers), list(staff)


@transaction.atomic
def calculate_period(period, *, actor):
    """Prepare (or re-prepare) the payrolls of a period. Idempotent: a payroll
    whose fresh calculation equals its stored one is left untouched;
    otherwise a NEW version of lines is written (old versions kept).
    Approved / paid / cancelled payrolls are never touched."""
    _admin(actor, period.school)
    period = _open_period(period)
    teachers, staff_members = _employee_payroll_targets(period)
    summary = {"created": 0, "recalculated": 0, "unchanged": 0, "frozen": 0, "warnings": []}
    targets = [(TeacherPayroll, "teacher", t, compute_teacher) for t in teachers] + [
        (StaffPayroll, "staff", s, compute_staff) for s in staff_members
    ]
    for model, owner_field, owner, compute in targets:
        calc = compute(owner, period)
        summary["warnings"] += calc.warnings
        payroll = (
            model.objects.select_for_update()
            .filter(payroll_period=period, **{owner_field: owner})
            .exclude(status=PayrollStatus.CANCELLED)
            .first()
        )
        if payroll is None:
            if not calc.lines:
                continue
            payroll = model(
                school=period.school,
                payroll_period=period,
                currency=period.school.currency,
                calculated_at=timezone.now(),
                **{owner_field: owner},
            )
            _write(payroll, calc, actor)
            summary["created"] += 1
            action = "PAYROLL_CALCULATED"
        elif payroll.status != PayrollStatus.CALCULATED:
            summary["frozen"] += 1
            continue
        elif calc.signature() == _current_signature(payroll):
            summary["unchanged"] += 1
            continue
        else:
            payroll.version += 1
            _write(payroll, calc, actor)
            summary["recalculated"] += 1
            action = "PAYROLL_RECALCULATED"
        _audit(
            action,
            actor,
            payroll,
            new={
                "version": payroll.version,
                "payable": str(payroll.payable_amount),
                "adjustments": str(payroll.adjustments_amount),
                "warnings": calc.warnings,
            },
        )
    return summary


# =============================================================================
# Approval, payment, cancellation
# =============================================================================


def _locked(payroll):
    return type(payroll).objects.select_for_update().get(pk=payroll.pk)


def _require_status(payroll, expected):
    if payroll.status == expected:
        return
    codes = {
        PayrollStatus.PAID: "payroll_already_paid",
        PayrollStatus.CANCELLED: "payroll_cancelled",
        PayrollStatus.APPROVED: "payroll_already_approved",
        PayrollStatus.CALCULATED: "payroll_not_approved",
    }
    raise ValidationError(f"Payroll is {payroll.status}.", code=codes[payroll.status])


@transaction.atomic
def approve_payroll(payroll, *, actor):
    """Administrative approval: the stored calculation must still be what the
    sources give today (else 409 payroll_stale: recalculate first)."""
    _admin(actor, payroll.school)
    payroll = _locked(payroll)
    _require_status(payroll, PayrollStatus.CALCULATED)
    _open_period(payroll.payroll_period)
    if not reconstruct(payroll):
        raise ValidationError(
            "The sources changed since the calculation: recalculate the period.", code="payroll_stale"
        )
    payroll.status = PayrollStatus.APPROVED
    payroll.approved_amount = payroll.payable_amount
    payroll.approved_by, payroll.approved_at = actor, timezone.now()
    payroll.save()
    _audit(
        "PAYROLL_APPROVED",
        actor,
        payroll,
        new={"approved_amount": str(payroll.approved_amount), "version": payroll.version},
    )
    return payroll


def _employee(payroll):
    return payroll.teacher.employee if isinstance(payroll, TeacherPayroll) else payroll.staff.employee


@transaction.atomic
def pay_payroll(payroll, *, actor, payout_method, wallet=None):
    """Payment through Finance: debit of the school treasury (+ credit of the
    employee's simulated wallet). The payroll row is locked: a double click
    or two clerks paying together get 409 payroll_already_paid; settlements
    UNIQUE(session) make a second payment of a session impossible anyway."""
    _admin(actor, payroll.school)
    payroll = _locked(payroll)
    _require_status(payroll, PayrollStatus.APPROVED)
    _open_period(payroll.payroll_period)
    employee = _employee(payroll)
    if payout_method == PayoutMethod.WALLET:
        if wallet is None:
            raise ValidationError("A wallet is required.", code="wallet_required")
        wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
        if wallet.school_id != payroll.school_id or wallet.owner_id != employee.membership_id:
            raise PermissionDenied("Salaries are paid only to the employee's own wallet.")
        if wallet.status != AccountStatus.ACTIVE:
            raise ValidationError("This wallet is blocked.", code="wallet_blocked")
    elif payout_method == PayoutMethod.CASH:
        wallet = None
    else:
        raise ValidationError("Unknown payout method.", code="invalid_method")

    reference = f"PAYR-{uuid.uuid4().hex[:12].upper()}"
    amount = payroll.approved_amount
    meta = {"payroll": str(payroll.pk), "employee": str(employee.pk)}
    if amount > 0:
        finance._post(
            finance.get_treasury(payroll.school),
            transaction_type=LedgerType.PAYROLL,
            direction=LedgerDirection.DEBIT,
            amount=amount,
            reference=reference,
            actor=actor,
            metadata=meta,
        )
        if wallet is not None:
            finance._post(
                wallet,
                transaction_type=LedgerType.PAYROLL,
                direction=LedgerDirection.CREDIT,
                amount=amount,
                reference=reference,
                actor=actor,
                metadata=meta,
            )
    payroll.status, payroll.paid_at, payroll.paid_by = PayrollStatus.PAID, timezone.now(), actor
    payroll.payout_method, payroll.wallet, payroll.payment_reference = payout_method, wallet, reference
    payroll.save()

    owner = "teacher_payroll" if isinstance(payroll, TeacherPayroll) else "staff_payroll"
    lines = PayrollLine.objects.filter(**{owner: payroll}, version=payroll.version)
    for line in lines.filter(kind=LineKind.EARNED):
        try:
            with transaction.atomic():
                PayrollSettlement.objects.create(
                    school=payroll.school,
                    teaching_session_id=line.teaching_session_id,
                    teacher_payroll=payroll,
                    line=line,
                    amount=line.amount,
                    settled_at=payroll.paid_at,
                )
        except IntegrityError:
            raise ValidationError("A session of this payroll was already paid.", code="session_already_paid") from None
    for line in lines.filter(kind=LineKind.ADJUSTMENT).select_related("adjustment"):
        adjustment = line.adjustment
        setattr(adjustment, f"settled_{owner}", payroll)
        adjustment.save()
    _audit(
        "PAYROLL_PAID",
        actor,
        payroll,
        new={
            "amount": str(amount),
            "reference": reference,
            "method": payout_method,
            "wallet": str(wallet.pk) if wallet else None,
        },
    )
    return payroll


@transaction.atomic
def cancel_payroll(payroll, *, actor, reason):
    """Prepared or approved (never paid) payroll set aside; its lines stay as
    history and a new calculation can be made."""
    _admin(actor, payroll.school)
    reason = _reason(reason)
    payroll = _locked(payroll)
    if payroll.status not in (PayrollStatus.CALCULATED, PayrollStatus.APPROVED):
        _require_status(payroll, PayrollStatus.CALCULATED)
    _open_period(payroll.payroll_period)
    old = payroll.status
    payroll.status, payroll.cancelled_reason = PayrollStatus.CANCELLED, reason
    payroll.save()
    _audit("PAYROLL_CANCELLED", actor, payroll, old={"status": old}, new={"reason": reason})
    return payroll


@transaction.atomic
def create_adjustment(employee, *, actor, amount, reason, effective_date=None):
    """Manual correction (bonus, recovery of an overpayment...), applied by the
    next paid payroll of the employee."""
    _admin(actor, employee.school)
    adjustment = SalaryAdjustment.objects.create(
        school=employee.school,
        employee=employee,
        amount=_money(amount, allow_negative=True),
        reason=_reason(reason),
        effective_date=effective_date or timezone.localdate(),
        approved_by=actor,
    )
    _audit(
        "SALARY_ADJUSTMENT_CREATED",
        actor,
        adjustment,
        new={"employee": str(employee.pk), "amount": str(adjustment.amount), "reason": adjustment.reason},
    )
    return adjustment


# =============================================================================
# Read model
# =============================================================================


def remuneration(employee, date_from, date_to):
    """Live summary for a date range (no write): programmed, earned (validated,
    not paid yet), paid. Teachers only; staff get their dated salary."""
    teacher = getattr(employee, "teacher_profile", None)
    if teacher is None:
        staff = getattr(employee, "staff_profile", None)
        profile = staff_salary_for(staff, date_to) if staff else None
        return {"kind": "STAFF", "monthly_salary": profile.monthly_salary if profile else None}
    sessions = TeachingSession.objects.filter(teacher=teacher, date__gte=date_from, date__lte=date_to).select_related(
        "check_in"
    )
    programmed = earned = paid = ZERO
    counts = {"scheduled": 0, "validated": 0, "paid": 0, "missing_rate": 0}
    for session in sessions.exclude(status=SessionStatus.CANCELLED):
        profile = teacher_rate_for(teacher, session.date)
        if profile is None:
            counts["missing_rate"] += 1
            continue
        counts["scheduled"] += 1
        planned = int((session.scheduled_end - session.scheduled_start).total_seconds() // 60)
        programmed += session_amount(profile.vacation_rate, planned, profile.vacation_minutes)
        settlement = PayrollSettlement.objects.filter(teaching_session=session).first()
        if settlement is not None:
            counts["paid"] += 1
            paid += settlement.amount
        elif is_payable(session):
            counts["validated"] += 1
            earned += session_amount(profile.vacation_rate, duration_minutes(session), profile.vacation_minutes)
    return {
        "kind": "TEACHER",
        "programmed_amount": programmed,
        "earned_unpaid_amount": earned,
        "paid_amount": paid,
        "sessions": counts,
    }
