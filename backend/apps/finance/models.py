"""Finance (spec §4.9, ADR 0013).

    FeeType ── FeeSchedule            what is charged (the "payment type"), how much, when
    Invoice ── InvoiceLine            obligation of ONE student for a year
    Payment ── PaymentAllocation      money received, spread over invoices
            └─ PaymentRefund          inverse transaction, never a deletion
    SimulationTreasury ── TreasuryTransaction   the school's (simulated) account
    Wallet ── WalletTransaction                 a payer's (simulated) mobile wallet

Money is always DecimalField (never float). Every movement of money is an
append-only ledger row whose balance arithmetic is a PostgreSQL CHECK
(balance_after = balance_before ± amount); balances can never go negative.
`Payment` does not depend on the provider: the provider code and its
reference are data, a real mobile-money provider plugs into
providers.py without changing these tables.
"""

from decimal import Decimal

from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Round
from django.utils import timezone

from apps.core.models import SUPPORTED_CURRENCIES
from common.models import TenantModel

ZERO = Decimal("0.00")


def _money(**kw):
    return models.DecimalField(max_digits=14, decimal_places=2, **kw)


def _currency():
    return models.CharField(max_length=3, default="XAF")


# =============================================================================
# Fees
# =============================================================================


class FeeType(TenantModel):
    """Configurable payment type / reason: TUITION, REGISTRATION, CANTEEN,
    EXCURSION... (spec FeeType). Data, not code."""

    code = models.CharField(max_length=40)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, null=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        constraints = [models.UniqueConstraint(fields=["school", "code"], name="fee_type_school_code_unique")]

    def __str__(self):
        return self.code


class FeeSchedule(TenantModel):
    """Amount of a fee for a year, optionally restricted to a level or a class
    (both NULL = every student of the year)."""

    fee_type = models.ForeignKey(FeeType, on_delete=models.PROTECT, related_name="schedules")
    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT, related_name="+")
    level = models.ForeignKey("academics.Level", on_delete=models.PROTECT, blank=True, null=True, related_name="+")
    school_class = models.ForeignKey(
        "academics.SchoolClass", on_delete=models.PROTECT, blank=True, null=True, related_name="+"
    )
    amount = _money()
    due_date = models.DateField()
    mandatory = models.BooleanField(default=True)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="fee_schedule_amount_positive"),
        ]


# =============================================================================
# Invoices
# =============================================================================


class InvoiceStatus(models.TextChoices):
    ISSUED = "ISSUED", "Émise"
    PARTIALLY_PAID = "PARTIALLY_PAID", "Partiellement payée"
    PAID = "PAID", "Payée"
    CANCELLED = "CANCELLED", "Annulée"


class Invoice(TenantModel):
    """An obligation of one student for one year.

    `amount_paid` is the sum of the invoice's allocations (refunds are negative
    allocations); `balance_due` = total - paid is a PostgreSQL CHECK, as are
    "paid never exceeds total" and the status / balance consistency.
    `payer` is optional (deviation, ADR 0013): any VERIFIED parent with the
    can_pay right may pay a child's invoice.
    """

    invoice_number = models.CharField(max_length=60)
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT, related_name="invoices")
    payer = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.PROTECT, blank=True, null=True, related_name="+"
    )
    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT, related_name="+")
    issue_date = models.DateField(default=timezone.localdate)
    due_date = models.DateField()
    status = models.CharField(max_length=30, choices=InvoiceStatus.choices, default=InvoiceStatus.ISSUED, db_index=True)
    subtotal = _money()
    total_amount = _money()
    amount_paid = _money(default=ZERO)
    balance_due = _money(default=ZERO)
    currency = _currency()
    issued_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )
    cancelled_reason = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["due_date", "invoice_number"]
        constraints = [
            models.UniqueConstraint(fields=["school", "invoice_number"], name="invoice_school_number_unique"),
            models.CheckConstraint(condition=Q(total_amount__gte=0), name="invoice_total_not_negative"),
            models.CheckConstraint(
                condition=Q(amount_paid__gte=0) & Q(amount_paid__lte=F("total_amount")),
                name="invoice_paid_within_total",
            ),
            models.CheckConstraint(
                condition=Q(balance_due=F("total_amount") - F("amount_paid")), name="invoice_balance_consistent"
            ),
            models.CheckConstraint(condition=Q(status__in=InvoiceStatus.values), name="invoice_status_valid"),
            models.CheckConstraint(condition=Q(currency__in=SUPPORTED_CURRENCIES), name="invoice_currency_supported"),
            models.CheckConstraint(
                condition=~Q(status=InvoiceStatus.PAID) | Q(balance_due=0), name="invoice_paid_has_no_balance"
            ),
            models.CheckConstraint(
                condition=~Q(status=InvoiceStatus.CANCELLED) | Q(amount_paid=0), name="invoice_cancelled_unpaid"
            ),
        ]

    def __str__(self):
        return self.invoice_number


class InvoiceLine(TenantModel):
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="lines")
    fee_type = models.ForeignKey(FeeType, on_delete=models.PROTECT, related_name="+")
    # Set when generated from a schedule: one line per student and schedule.
    fee_schedule = models.ForeignKey(FeeSchedule, on_delete=models.PROTECT, blank=True, null=True, related_name="+")
    description = models.TextField()
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("1.00"))
    unit_price = _money()
    total = _money()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="invoice_line_quantity_positive"),
            models.CheckConstraint(condition=Q(unit_price__gte=0), name="invoice_line_price_not_negative"),
            models.CheckConstraint(
                condition=Q(total=Round(F("quantity") * F("unit_price"), 2)), name="invoice_line_total_consistent"
            ),
        ]


# =============================================================================
# Simulated accounts
# =============================================================================


class AccountStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Actif"
    BLOCKED = "BLOCKED", "Bloqué"


class SimulationTreasury(TenantModel):
    """The school's (simulated) account: credited by payments, debited by
    refunds. One per school; balance never negative (CHECK)."""

    balance = models.DecimalField(max_digits=18, decimal_places=2, default=ZERO)
    currency = _currency()
    status = models.CharField(max_length=20, choices=AccountStatus.choices, default=AccountStatus.ACTIVE)

    class Meta:
        verbose_name_plural = "simulation treasuries"
        constraints = [
            models.UniqueConstraint(fields=["school"], name="treasury_one_per_school"),
            models.CheckConstraint(condition=Q(balance__gte=0), name="treasury_balance_not_negative"),
        ]


class SimulationBehavior(models.TextChoices):
    """Deterministic outcome of the SIMULATION provider for this wallet (tests,
    demos). INSUFFICIENT_FUNDS needs no setting: it follows the balance."""

    NORMAL = "NORMAL", "Normal"
    DECLINE = "DECLINE", "Refus systématique"
    TIMEOUT = "TIMEOUT", "Délai dépassé"
    PROVIDER_ERROR = "PROVIDER_ERROR", "Erreur fournisseur"


class Wallet(TenantModel):
    """A payer's mobile-money wallet — simulated in V1 (FAKE_ORANGE, FAKE_MTN)."""

    owner = models.ForeignKey("accounts.SchoolMembership", on_delete=models.PROTECT, related_name="wallets")
    wallet_type = models.CharField(max_length=30, default="MOBILE_MONEY")
    provider_code = models.CharField(max_length=30)
    wallet_identifier = models.CharField(max_length=120, db_index=True)
    balance = models.DecimalField(max_digits=18, decimal_places=2, default=ZERO)
    currency = _currency()
    status = models.CharField(max_length=20, choices=AccountStatus.choices, default=AccountStatus.ACTIVE)
    simulation_behavior = models.CharField(
        max_length=20, choices=SimulationBehavior.choices, default=SimulationBehavior.NORMAL
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school", "provider_code", "wallet_identifier"], name="wallet_identifier_unique"
            ),
            models.CheckConstraint(condition=Q(balance__gte=0), name="wallet_balance_not_negative"),
            models.CheckConstraint(
                condition=Q(simulation_behavior__in=SimulationBehavior.values), name="wallet_behavior_valid"
            ),
        ]

    def __str__(self):
        return f"{self.provider_code}:{self.wallet_identifier}"


class LedgerType(models.TextChoices):
    FUNDING = "FUNDING", "Approvisionnement (simulation)"
    PAYMENT = "PAYMENT", "Paiement"
    REFUND = "REFUND", "Remboursement"


class LedgerDirection(models.TextChoices):
    CREDIT = "CREDIT", "Crédit"
    DEBIT = "DEBIT", "Débit"


def _ledger_constraints(prefix):
    return [
        models.CheckConstraint(condition=Q(amount__gt=0), name=f"{prefix}_amount_positive"),
        models.CheckConstraint(condition=Q(balance_after__gte=0), name=f"{prefix}_balance_not_negative"),
        models.CheckConstraint(
            condition=(Q(direction=LedgerDirection.CREDIT) & Q(balance_after=F("balance_before") + F("amount")))
            | (Q(direction=LedgerDirection.DEBIT) & Q(balance_after=F("balance_before") - F("amount"))),
            name=f"{prefix}_arithmetic",
        ),
        models.CheckConstraint(condition=Q(transaction_type__in=LedgerType.values), name=f"{prefix}_type_valid"),
    ]


class LedgerEntry(TenantModel):
    transaction_type = models.CharField(max_length=30, choices=LedgerType.choices, db_index=True)
    direction = models.CharField(max_length=10, choices=LedgerDirection.choices)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = _currency()
    reference = models.CharField(max_length=100, db_index=True)
    balance_before = models.DecimalField(max_digits=18, decimal_places=2)
    balance_after = models.DecimalField(max_digits=18, decimal_places=2)
    created_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )
    metadata = models.JSONField(default=dict)

    class Meta:
        abstract = True
        ordering = ["created_at"]


class WalletTransaction(LedgerEntry):
    """Immutable ledger line of a wallet (spec WalletTransaction)."""

    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, related_name="transactions")

    class Meta(LedgerEntry.Meta):
        constraints = _ledger_constraints("wallet_tx")


class TreasuryTransaction(LedgerEntry):
    """Immutable ledger line of the school treasury (addition, ADR 0013)."""

    treasury = models.ForeignKey(SimulationTreasury, on_delete=models.PROTECT, related_name="transactions")

    class Meta(LedgerEntry.Meta):
        constraints = _ledger_constraints("treasury_tx")


# =============================================================================
# Payments
# =============================================================================


class PaymentMethod(models.TextChoices):
    WALLET = "WALLET", "Portefeuille mobile"
    CASH = "CASH", "Espèces (guichet)"


class PaymentStatus(models.TextChoices):
    PENDING = "PENDING", "Créé / en attente"
    SUCCEEDED = "SUCCEEDED", "Réussi"
    DECLINED = "DECLINED", "Refusé"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS", "Fonds insuffisants"
    TIMEOUT = "TIMEOUT", "Délai dépassé"
    PROVIDER_ERROR = "PROVIDER_ERROR", "Erreur fournisseur"
    CANCELLED = "CANCELLED", "Annulé"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED", "Partiellement remboursé"
    REFUNDED = "REFUNDED", "Remboursé"


FAILED_STATUSES = [
    PaymentStatus.DECLINED,
    PaymentStatus.INSUFFICIENT_FUNDS,
    PaymentStatus.TIMEOUT,
    PaymentStatus.PROVIDER_ERROR,
    PaymentStatus.CANCELLED,
]
MONEY_RECEIVED = [PaymentStatus.SUCCEEDED, PaymentStatus.PARTIALLY_REFUNDED, PaymentStatus.REFUNDED]


class Payment(TenantModel):
    """A payment, independent of the provider (spec Payment).

    Links: student, payer (whose money), initiated_by (who clicked: the payer
    or an administrator at the desk), fee_type (reason when not settling
    invoices), wallet, internal `payment_reference`, provider reference.

    Idempotency: UNIQUE(school, idempotency_key) — a client retry with the
    same key never creates a second payment. A trigger forbids DELETE and,
    once the payment left PENDING, any change except the refund progression
    (refunded_amount up, status SUCCEEDED -> PARTIALLY_REFUNDED -> REFUNDED).
    """

    payment_reference = models.CharField(max_length=100)
    idempotency_key = models.CharField(max_length=120)
    request_fingerprint = models.CharField(max_length=64)  # detects key reuse with another request
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT, related_name="payments")
    payer = models.ForeignKey("accounts.SchoolMembership", on_delete=models.PROTECT, related_name="payments_made")
    initiated_by = models.ForeignKey("accounts.SchoolMembership", on_delete=models.PROTECT, related_name="+")
    fee_type = models.ForeignKey(FeeType, on_delete=models.PROTECT, blank=True, null=True, related_name="+")
    wallet = models.ForeignKey(Wallet, on_delete=models.PROTECT, blank=True, null=True, related_name="payments")
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    refunded_amount = models.DecimalField(max_digits=18, decimal_places=2, default=ZERO)
    currency = _currency()
    payment_method = models.CharField(max_length=30, choices=PaymentMethod.choices)
    provider = models.CharField(max_length=50)
    status = models.CharField(
        max_length=30, choices=PaymentStatus.choices, default=PaymentStatus.PENDING, db_index=True
    )
    initiated_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(blank=True, null=True)
    failure_reason = models.TextField(blank=True, null=True)
    provider_reference = models.CharField(max_length=120, blank=True, null=True)

    class Meta:
        ordering = ["-initiated_at"]
        constraints = [
            models.UniqueConstraint(fields=["school", "payment_reference"], name="payment_reference_unique"),
            models.UniqueConstraint(fields=["school", "idempotency_key"], name="payment_idempotency_unique"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="payment_amount_positive"),
            models.CheckConstraint(
                condition=Q(refunded_amount__gte=0) & Q(refunded_amount__lte=F("amount")),
                name="payment_refunded_within_amount",
            ),
            models.CheckConstraint(condition=Q(status__in=PaymentStatus.values), name="payment_status_valid"),
            models.CheckConstraint(condition=Q(payment_method__in=PaymentMethod.values), name="payment_method_valid"),
            models.CheckConstraint(condition=Q(currency__in=SUPPORTED_CURRENCIES), name="payment_currency_supported"),
            models.CheckConstraint(
                condition=~Q(payment_method=PaymentMethod.WALLET) | Q(wallet__isnull=False),
                name="payment_wallet_required",
            ),
            models.CheckConstraint(
                condition=Q(status=PaymentStatus.PENDING) | Q(completed_at__isnull=False),
                name="payment_completion_dated",
            ),
            models.CheckConstraint(
                condition=Q(refunded_amount=0)
                | Q(status__in=[PaymentStatus.PARTIALLY_REFUNDED, PaymentStatus.REFUNDED]),
                name="payment_refund_status_consistent",
            ),
        ]

    def __str__(self):
        return self.payment_reference


class PaymentAllocation(TenantModel):
    """Part of a payment settling one invoice. Refunds append NEGATIVE
    allocations linked to the refund — history is never rewritten.
    `student` copy + composite keys: the invoice and the payment belong to
    the same student."""

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="allocations")
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="allocations")
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT, related_name="+")
    refund = models.ForeignKey(
        "PaymentRefund", on_delete=models.PROTECT, blank=True, null=True, related_name="allocations"
    )
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    allocated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(Q(refund__isnull=True) & Q(amount__gt=0)) | (Q(refund__isnull=False) & Q(amount__lt=0)),
                name="allocation_sign_matches_refund",
            ),
        ]


class RefundStatus(models.TextChoices):
    COMPLETED = "COMPLETED", "Effectué"
    FAILED = "FAILED", "Échoué"


class PaymentRefund(TenantModel):
    """Inverse transaction of a payment (spec PaymentRefund): the original
    payment stays untouched (except its refunded_amount / status progression).
    Append-only (trigger)."""

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="refunds")
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    reason = models.TextField()
    status = models.CharField(max_length=30, choices=RefundStatus.choices, default=RefundStatus.COMPLETED)
    created_by = models.ForeignKey("accounts.SchoolMembership", on_delete=models.PROTECT, related_name="+")
    completed_at = models.DateTimeField(blank=True, null=True)
    inverse_transaction_reference = models.CharField(max_length=120, blank=True, null=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="refund_amount_positive"),
            models.CheckConstraint(condition=~Q(reason=""), name="refund_reason_required"),
            models.CheckConstraint(condition=Q(status__in=RefundStatus.values), name="refund_status_valid"),
        ]
