"""Payroll — teachers' and staff remuneration (spec §4.8, §6.10, ADR 0014).

    TeachingSession (scheduling)              the ONLY session system
      └── TeacherSessionCheckIn               self-report + ADMINISTRATIVE validation
    TeacherCompensationProfile                vacation rate of a teacher, dated
    StaffCompensationProfile                  monthly salary of a staff member, dated
    PayrollPeriod                             calculation window (OPEN -> CLOSED)
      ├── TeacherPayroll ┐                    one per employee and period:
      └── StaffPayroll   ┘                    CALCULATED -> APPROVED -> PAID (or CANCELLED)
            └── PayrollLine                   append-only calculation trace (versioned)
    PayrollSettlement                         one row per PAID session: a session is paid once
    SalaryAdjustment                          corrections (manual, or automatic when a paid
                                              session's validation is revoked)

The five money states the school asked to keep apart:

    programmed  sessions planned (not cancelled) x rate     TeacherPayroll.programmed_amount
    earned      sessions VALIDATED by the administration    TeacherPayroll.earned_amount
    prepared    payroll CALCULATED (lines written)          status = CALCULATED
    approved    administrative approval, amount frozen      status = APPROVED, approved_amount
    paid        money moved through Finance (treasury)      status = PAID, payment_reference

Determinism: an EARNED line is a pure function of
(session times, check-in validation, compensation profile):
    amount = ROUND(vacation_rate x duration_minutes / vacation_minutes, 2)
PostgreSQL re-checks the arithmetic (CHECK) and, by trigger, that the session
is validated and not cancelled when the line is written.
"""

from decimal import Decimal

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeBoundary, RangeOperators
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Round

from apps.scheduling.models import DateSpan
from common.models import TenantModel

ZERO = Decimal("0.00")


def _money(**kw):
    return models.DecimalField(max_digits=14, decimal_places=2, **kw)


def _span(start="effective_from", end="effective_to"):
    return DateSpan(start, end, RangeBoundary(inclusive_lower=True, inclusive_upper=True))


# =============================================================================
# Administrative validation of the sessions
# =============================================================================


class SelfReportStatus(models.TextChoices):
    PENDING = "PENDING", "Non déclarée"
    PRESENT = "PRESENT", "Présent"
    ABSENT = "ABSENT", "Absent"


class VerificationStatus(models.TextChoices):
    PENDING = "PENDING", "À valider"
    VALIDATED = "VALIDATED", "Validée"  # the ONLY state that makes a session payable
    REJECTED = "REJECTED", "Rejetée"


class TeacherSessionCheckIn(TenantModel):
    """Teacher self check-in and administrative validation of ONE session
    (spec §4.5). It hangs on the existing TeachingSession: no parallel
    session table.

    `teacher` is the teacher who actually taught (session.teacher, i.e. the
    substitute if any). A composite FK (session, teacher) -> session(id,
    teacher) keeps them equal: once a check-in exists, the session's teacher
    cannot silently change.
    Changes of the verification are corrections: audited (AuditLog), and
    once the session has been paid they produce a SalaryAdjustment.
    """

    teaching_session = models.OneToOneField(
        "scheduling.TeachingSession", on_delete=models.PROTECT, related_name="check_in"
    )
    teacher = models.ForeignKey("people.TeacherProfile", on_delete=models.PROTECT, related_name="check_ins")
    self_reported_at = models.DateTimeField(blank=True, null=True)
    self_reported_status = models.CharField(
        max_length=20, choices=SelfReportStatus.choices, default=SelfReportStatus.PENDING
    )
    verified_at = models.DateTimeField(blank=True, null=True)
    verified_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )
    verified_status = models.CharField(
        max_length=30, choices=VerificationStatus.choices, default=VerificationStatus.PENDING, db_index=True
    )
    verification_reason = models.TextField(blank=True, null=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(self_reported_status__in=SelfReportStatus.values), name="checkin_self_status_valid"
            ),
            models.CheckConstraint(
                condition=Q(verified_status__in=VerificationStatus.values), name="checkin_verified_status_valid"
            ),
            models.CheckConstraint(
                condition=Q(verified_status=VerificationStatus.PENDING)
                | (Q(verified_at__isnull=False) & Q(verified_by__isnull=False)),
                name="checkin_verification_has_author",
            ),
            models.CheckConstraint(
                condition=~Q(verified_status=VerificationStatus.REJECTED)
                | (Q(verification_reason__isnull=False) & ~Q(verification_reason="")),
                name="checkin_rejection_has_reason",
            ),
        ]


# =============================================================================
# Rates
# =============================================================================


class TeacherCompensationProfile(TenantModel):
    """Vacation rate of a teacher (spec §4.8), DATED.

    A rate is never edited: changing it ends the current row (effective_to)
    and starts a new one, so every paid line keeps pointing at the rate it
    used. `vacation_minutes` (a copy of SchoolConfiguration.
    teacher_vacation_duration_minutes when the rate is set) makes the
    calculation independent of later configuration changes.
    Deviation (ADR 0014): spec UNIQUE(teacher, academic_year) replaced by a
    no-overlap exclusion on the effective dates, to keep the rate history.
    """

    teacher = models.ForeignKey("people.TeacherProfile", on_delete=models.PROTECT, related_name="compensation")
    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT, related_name="+")
    vacation_rate = models.DecimalField(max_digits=12, decimal_places=2)
    vacation_minutes = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="XAF")
    effective_from = models.DateField()
    effective_to = models.DateField(blank=True, null=True)
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )

    class Meta:
        ordering = ["effective_from"]
        constraints = [
            models.CheckConstraint(condition=Q(vacation_rate__gt=0), name="teacher_rate_positive"),
            models.CheckConstraint(condition=Q(vacation_minutes__gt=0), name="teacher_rate_minutes_positive"),
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True) | Q(effective_to__gte=F("effective_from")),
                name="teacher_rate_dates_ordered",
            ),
            ExclusionConstraint(
                name="teacher_rate_no_overlap",
                expressions=[("teacher", RangeOperators.EQUAL), (_span(), RangeOperators.OVERLAPS)],
                condition=Q(active=True),
            ),
        ]


class StaffCompensationProfile(TenantModel):
    """Monthly salary of a staff member, DATED like the teacher rate.
    Addition (ADR 0014): EmployeeProfile.base_salary has no history, so it
    cannot make a past payroll reconstructible; it stays informative."""

    staff = models.ForeignKey("people.StaffProfile", on_delete=models.PROTECT, related_name="compensation")
    monthly_salary = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="XAF")
    effective_from = models.DateField()
    effective_to = models.DateField(blank=True, null=True)
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )

    class Meta:
        ordering = ["effective_from"]
        constraints = [
            models.CheckConstraint(condition=Q(monthly_salary__gt=0), name="staff_salary_positive"),
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True) | Q(effective_to__gte=F("effective_from")),
                name="staff_salary_dates_ordered",
            ),
            ExclusionConstraint(
                name="staff_salary_no_overlap",
                expressions=[("staff", RangeOperators.EQUAL), (_span(), RangeOperators.OVERLAPS)],
                condition=Q(active=True),
            ),
        ]


# =============================================================================
# Periods and payrolls
# =============================================================================


class PeriodStatus(models.TextChoices):
    OPEN = "OPEN", "Ouverte"
    CLOSED = "CLOSED", "Clôturée"


class PayrollPeriod(TenantModel):
    """Calculation window (spec §4.8). Periods of a school never overlap, so
    a session date belongs to at most one period. CLOSED is final: no
    payroll can be created or changed in it any more (trigger)."""

    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT, related_name="+")
    name = models.CharField(max_length=80)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=30, choices=PeriodStatus.choices, default=PeriodStatus.OPEN, db_index=True)
    closed_at = models.DateTimeField(blank=True, null=True)
    closed_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )

    class Meta:
        ordering = ["start_date"]
        constraints = [
            models.UniqueConstraint(fields=["school", "academic_year", "name"], name="payroll_period_name_unique"),
            models.CheckConstraint(condition=Q(end_date__gte=F("start_date")), name="payroll_period_dates_ordered"),
            models.CheckConstraint(condition=Q(status__in=PeriodStatus.values), name="payroll_period_status_valid"),
            models.CheckConstraint(
                condition=Q(status=PeriodStatus.OPEN) | Q(closed_at__isnull=False), name="payroll_period_closed_at"
            ),
            ExclusionConstraint(
                name="payroll_period_no_overlap",
                expressions=[
                    ("school", RangeOperators.EQUAL),
                    (_span("start_date", "end_date"), RangeOperators.OVERLAPS),
                ],
            ),
        ]

    def __str__(self):
        return self.name


class PayrollStatus(models.TextChoices):
    CALCULATED = "CALCULATED", "Préparée"
    APPROVED = "APPROVED", "Validée"
    PAID = "PAID", "Payée"
    CANCELLED = "CANCELLED", "Annulée"


class PayoutMethod(models.TextChoices):
    WALLET = "WALLET", "Wallet (simulation)"
    CASH = "CASH", "Espèces / hors système"


ACTIVE_PAYROLL = ~Q(status=PayrollStatus.CANCELLED)


class PayrollBase(TenantModel):
    """Shared lifecycle of TeacherPayroll and StaffPayroll.

    `version` counts the calculations: each recalculation writes new
    PayrollLine rows with the new version, old ones stay (trace).
    `adjustments_amount` = sum of the SalaryAdjustment applied by this
    calculation. Once APPROVED the amounts are frozen (trigger); PAID and
    CANCELLED are final."""

    payroll_period = models.ForeignKey(PayrollPeriod, on_delete=models.PROTECT, related_name="+")
    version = models.PositiveIntegerField(default=1)
    adjustments_amount = _money(default=ZERO)
    approved_amount = _money(default=ZERO)
    status = models.CharField(
        max_length=30, choices=PayrollStatus.choices, default=PayrollStatus.CALCULATED, db_index=True
    )
    calculated_at = models.DateTimeField()
    calculated_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )
    approved_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )
    approved_at = models.DateTimeField(blank=True, null=True)
    paid_at = models.DateTimeField(blank=True, null=True)
    paid_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )
    payout_method = models.CharField(max_length=20, choices=PayoutMethod.choices, blank=True, null=True)
    wallet = models.ForeignKey("finance.Wallet", on_delete=models.PROTECT, blank=True, null=True, related_name="+")
    payment_reference = models.CharField(max_length=100, blank=True, null=True)
    cancelled_reason = models.TextField(blank=True, null=True)
    currency = models.CharField(max_length=3, default="XAF")

    class Meta:
        abstract = True

    @property
    def is_teacher(self):
        return isinstance(self, TeacherPayroll)


def _payroll_constraints(prefix, total):
    """`total` = the payable amount column (net_amount / gross_amount)."""
    return [
        models.CheckConstraint(condition=Q(status__in=PayrollStatus.values), name=f"{prefix}_status_valid"),
        models.CheckConstraint(condition=Q(**{f"{total}__gte": 0}), name=f"{prefix}_total_not_negative"),
        models.CheckConstraint(condition=Q(approved_amount__gte=0), name=f"{prefix}_approved_not_negative"),
        # Approved / paid: the frozen amount IS the calculated total, with its author.
        models.CheckConstraint(
            condition=~Q(status__in=[PayrollStatus.APPROVED, PayrollStatus.PAID])
            | (Q(approved_amount=F(total)) & Q(approved_at__isnull=False) & Q(approved_by__isnull=False)),
            name=f"{prefix}_approval_consistent",
        ),
        models.CheckConstraint(
            condition=~Q(status=PayrollStatus.PAID)
            | (Q(paid_at__isnull=False) & Q(payment_reference__isnull=False) & Q(payout_method__isnull=False)),
            name=f"{prefix}_payment_consistent",
        ),
        models.CheckConstraint(
            condition=~Q(payout_method=PayoutMethod.WALLET) | Q(wallet__isnull=False),
            name=f"{prefix}_wallet_payout_has_wallet",
        ),
        models.CheckConstraint(
            condition=~Q(status=PayrollStatus.CANCELLED) | Q(cancelled_reason__isnull=False),
            name=f"{prefix}_cancel_has_reason",
        ),
        models.UniqueConstraint(fields=["school", "payment_reference"], name=f"{prefix}_payment_reference_unique"),
    ]


class TeacherPayroll(PayrollBase):
    """Teacher remuneration of a period (spec §4.8).

    Addition (ADR 0014): `adjustments_amount` and `net_amount` =
    earned_amount + adjustments_amount (corrections of earlier periods)."""

    teacher = models.ForeignKey("people.TeacherProfile", on_delete=models.PROTECT, related_name="payrolls")
    scheduled_sessions_count = models.PositiveIntegerField(default=0)
    completed_sessions_count = models.PositiveIntegerField(default=0)
    payable_sessions_count = models.PositiveIntegerField(default=0)
    programmed_amount = _money(default=ZERO)
    earned_amount = _money(default=ZERO)
    net_amount = _money(default=ZERO)

    class Meta:
        constraints = [
            *_payroll_constraints("teacher_payroll", "net_amount"),
            # Spec UNIQUE(teacher, payroll_period), among non-cancelled payrolls
            # (a cancelled one stays as history, a new one can be calculated).
            models.UniqueConstraint(
                fields=["teacher", "payroll_period"], condition=ACTIVE_PAYROLL, name="teacher_payroll_unique"
            ),
            models.CheckConstraint(condition=Q(programmed_amount__gte=0), name="teacher_payroll_programmed_ok"),
            models.CheckConstraint(condition=Q(earned_amount__gte=0), name="teacher_payroll_earned_ok"),
            models.CheckConstraint(
                condition=Q(net_amount=F("earned_amount") + F("adjustments_amount")),
                name="teacher_payroll_net_consistent",
            ),
        ]

    @property
    def payable_amount(self):
        return self.net_amount


class StaffPayroll(PayrollBase):
    """Fixed salary of a staff member for a period (spec §4.8):
    gross_amount = base_salary + adjustments_amount."""

    staff = models.ForeignKey("people.StaffProfile", on_delete=models.PROTECT, related_name="payrolls")
    base_salary = _money(default=ZERO)
    gross_amount = _money(default=ZERO)

    class Meta:
        constraints = [
            *_payroll_constraints("staff_payroll", "gross_amount"),
            models.UniqueConstraint(
                fields=["staff", "payroll_period"], condition=ACTIVE_PAYROLL, name="staff_payroll_unique"
            ),
            models.CheckConstraint(condition=Q(base_salary__gte=0), name="staff_payroll_base_ok"),
            models.CheckConstraint(
                condition=Q(gross_amount=F("base_salary") + F("adjustments_amount")),
                name="staff_payroll_gross_consistent",
            ),
        ]

    @property
    def payable_amount(self):
        return self.gross_amount


# =============================================================================
# Calculation trace, settlements, corrections
# =============================================================================


class AdjustmentSource(models.TextChoices):
    MANUAL = "MANUAL", "Correction manuelle"
    VALIDATION_REVOKED = "VALIDATION_REVOKED", "Validation retirée après paiement"


class SalaryAdjustment(TenantModel):
    """Additive or corrective salary history (spec §4.6).

    Never edited: it is created, then applied by ONE paid payroll
    (`settled_*` set once, trigger). Negative = amount to recover."""

    employee = models.ForeignKey("people.EmployeeProfile", on_delete=models.PROTECT, related_name="adjustments")
    amount = _money()
    reason = models.TextField()
    effective_date = models.DateField()
    source = models.CharField(max_length=30, choices=AdjustmentSource.choices, default=AdjustmentSource.MANUAL)
    teaching_session = models.ForeignKey(
        "scheduling.TeachingSession", on_delete=models.PROTECT, blank=True, null=True, related_name="+"
    )
    approved_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )
    settled_teacher_payroll = models.ForeignKey(
        TeacherPayroll, on_delete=models.PROTECT, blank=True, null=True, related_name="settled_adjustments"
    )
    settled_staff_payroll = models.ForeignKey(
        StaffPayroll, on_delete=models.PROTECT, blank=True, null=True, related_name="settled_adjustments"
    )

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(condition=~Q(amount=0), name="adjustment_amount_not_zero"),
            models.CheckConstraint(condition=~Q(reason=""), name="adjustment_reason_required"),
            models.CheckConstraint(condition=Q(source__in=AdjustmentSource.values), name="adjustment_source_valid"),
            models.CheckConstraint(
                condition=Q(settled_teacher_payroll__isnull=True) | Q(settled_staff_payroll__isnull=True),
                name="adjustment_settled_once",
            ),
            models.CheckConstraint(
                condition=~Q(source=AdjustmentSource.VALIDATION_REVOKED) | Q(teaching_session__isnull=False),
                name="adjustment_revocation_has_session",
            ),
        ]


class LineKind(models.TextChoices):
    PROGRAMMED = "PROGRAMMED", "Séance programmée"  # information: planned, not cancelled
    EARNED = "EARNED", "Séance validée (acquise)"  # payable
    SALARY = "SALARY", "Salaire fixe"
    ADJUSTMENT = "ADJUSTMENT", "Correction"


class PayrollLine(TenantModel):
    """One element of ONE calculation (append-only, versioned).

    Session lines carry everything needed to recompute them: the session,
    the check-in, the profile used, the duration and the rate. PostgreSQL
    re-checks the arithmetic, and by trigger that an EARNED line is written
    only for a VALIDATED, COMPLETED (never cancelled) session.
    """

    teacher_payroll = models.ForeignKey(
        TeacherPayroll, on_delete=models.PROTECT, blank=True, null=True, related_name="lines"
    )
    staff_payroll = models.ForeignKey(
        StaffPayroll, on_delete=models.PROTECT, blank=True, null=True, related_name="lines"
    )
    version = models.PositiveIntegerField()
    kind = models.CharField(max_length=20, choices=LineKind.choices)
    teacher = models.ForeignKey(
        "people.TeacherProfile", on_delete=models.PROTECT, blank=True, null=True, related_name="+"
    )
    teaching_session = models.ForeignKey(
        "scheduling.TeachingSession", on_delete=models.PROTECT, blank=True, null=True, related_name="payroll_lines"
    )
    check_in = models.ForeignKey(
        TeacherSessionCheckIn, on_delete=models.PROTECT, blank=True, null=True, related_name="+"
    )
    teacher_profile = models.ForeignKey(
        TeacherCompensationProfile, on_delete=models.PROTECT, blank=True, null=True, related_name="+"
    )
    staff_profile = models.ForeignKey(
        StaffCompensationProfile, on_delete=models.PROTECT, blank=True, null=True, related_name="+"
    )
    adjustment = models.ForeignKey(SalaryAdjustment, on_delete=models.PROTECT, blank=True, null=True, related_name="+")
    session_date = models.DateField(blank=True, null=True)
    duration_minutes = models.PositiveIntegerField(blank=True, null=True)
    vacation_minutes = models.PositiveIntegerField(blank=True, null=True)
    rate = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    amount = _money()
    # Session from an earlier, closed period validated late (catch-up).
    late = models.BooleanField(default=False)

    class Meta:
        ordering = ["version", "kind", "session_date"]
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=LineKind.values), name="payroll_line_kind_valid"),
            models.CheckConstraint(
                condition=(Q(teacher_payroll__isnull=False) & Q(staff_payroll__isnull=True))
                | (Q(teacher_payroll__isnull=True) & Q(staff_payroll__isnull=False)),
                name="payroll_line_one_payroll",
            ),
            # Session lines: complete trace + arithmetic checked by PostgreSQL.
            models.CheckConstraint(
                condition=~Q(kind__in=[LineKind.PROGRAMMED, LineKind.EARNED])
                | (
                    Q(teacher_payroll__isnull=False)
                    & Q(teaching_session__isnull=False)
                    & Q(teacher_profile__isnull=False)
                    & Q(duration_minutes__gt=0)
                    & Q(vacation_minutes__gt=0)
                    & Q(rate__gt=0)
                    & Q(amount=Round(F("rate") * F("duration_minutes") / F("vacation_minutes"), 2))
                ),
                name="payroll_line_session_arithmetic",
            ),
            models.CheckConstraint(
                condition=~Q(kind=LineKind.EARNED) | Q(check_in__isnull=False), name="payroll_line_earned_validated"
            ),
            models.CheckConstraint(
                condition=~Q(kind=LineKind.SALARY)
                | (Q(staff_payroll__isnull=False) & Q(staff_profile__isnull=False) & Q(amount__gt=0)),
                name="payroll_line_salary_has_profile",
            ),
            models.CheckConstraint(
                condition=~Q(kind=LineKind.ADJUSTMENT) | (Q(adjustment__isnull=False) & ~Q(amount=0)),
                name="payroll_line_adjustment_linked",
            ),
        ]


class PayrollSettlement(TenantModel):
    """Written when a teacher payroll is PAID: one row per paid session.
    UNIQUE(teaching_session) is the database guarantee that a session is
    never paid twice, whatever the period, the payroll or the code path."""

    teaching_session = models.OneToOneField(
        "scheduling.TeachingSession", on_delete=models.PROTECT, related_name="payroll_settlement"
    )
    teacher_payroll = models.ForeignKey(TeacherPayroll, on_delete=models.PROTECT, related_name="settlements")
    line = models.OneToOneField(PayrollLine, on_delete=models.PROTECT, related_name="+")
    amount = _money()
    settled_at = models.DateTimeField()

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="settlement_amount_positive")]
