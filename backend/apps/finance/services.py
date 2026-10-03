"""Finance services (ADR 0013).

Rights (spec §8 matrix, using the verified parent links of the people phase):
- ADMIN / SUPER_ADMIN of the school: everything (fees, invoices, cash at the
  desk, refunds, wallets funding, dashboard);
- a payer = a member whose parent profile has an ACTIVE, VERIFIED link with
  `can_pay` to the student (parent, or a teacher / staff member who is also
  that parent) — pays with their OWN wallet;
- finance READ for a child requires the link's `can_view_financial_data`;
- everybody else: no financial right.

Money moves only through `_post()` (locked account row + append-only ledger
line whose arithmetic PostgreSQL checks). Every sensitive operation writes an
AuditLog row in the same transaction.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Sum
from django.utils import timezone

from apps.academics.models import AcademicYear
from apps.audit.models import AuditLayer
from apps.audit.services import record_audit
from apps.core.models import School
from apps.people.models import EnrollmentStatus, ParentStudent, StudentEnrollment, StudentStatus
from common.permissions import ADMIN_ROLES, membership_has_role, require_role

from .models import (
    FAILED_STATUSES,
    MONEY_RECEIVED,
    ZERO,
    FeeSchedule,
    FeeType,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    LedgerDirection,
    LedgerType,
    Payment,
    PaymentAllocation,
    PaymentMethod,
    PaymentRefund,
    PaymentStatus,
    SimulationTreasury,
    TreasuryTransaction,
    Wallet,
    WalletTransaction,
)
from .providers import provider_for

CENT = Decimal("0.01")


def _money(value):
    value = Decimal(str(value))
    if value.as_tuple().exponent < -2:
        raise ValidationError("Amounts have at most 2 decimals.", code="invalid_amount")
    if value <= 0:
        raise ValidationError("The amount must be positive.", code="invalid_amount")
    return value.quantize(CENT)


def _is_admin(membership, school):
    return membership is not None and membership.school_id == school.pk and membership_has_role(membership, ADMIN_ROLES)


def _link(membership, student, right):
    return ParentStudent.objects.filter(
        parent__membership=membership,
        parent__membership__status="ACTIVE",
        student=student,
        active=True,
        identity_verified=True,
        **{right: True},
    ).exists()


def can_pay(membership, student):
    return _is_admin(membership, student.school) or _link(membership, student, "can_pay")


def can_view_finance(membership, student):
    return _is_admin(membership, student.school) or _link(membership, student, "can_view_financial_data")


def _audit(action, actor, entity, new=None, old=None, layer=AuditLayer.BUSINESS):
    record_audit(action, actor=actor, entity=entity, new=new, old=old, layer=layer)


# =============================================================================
# Ledgers
# =============================================================================


def get_treasury(school):
    treasury, _ = SimulationTreasury.objects.get_or_create(school=school, defaults={"currency": school.currency})
    return treasury


def _post(account, *, transaction_type, direction, amount, reference, actor, metadata=None):
    """Move money on a Wallet or the SimulationTreasury: lock the account
    row, write the ledger line, update the balance. PostgreSQL checks the
    arithmetic and that no balance goes negative."""
    model = type(account)
    account = model.objects.select_for_update().get(pk=account.pk)
    before = account.balance
    after = before + amount if direction == LedgerDirection.CREDIT else before - amount
    if after < 0:
        raise ValidationError("Insufficient balance on this account.", code="insufficient_balance")
    ledger_model, fk = (WalletTransaction, "wallet") if model is Wallet else (TreasuryTransaction, "treasury")
    entry = ledger_model.objects.create(
        school=account.school,
        transaction_type=transaction_type,
        direction=direction,
        amount=amount,
        currency=account.currency,
        reference=reference,
        balance_before=before,
        balance_after=after,
        created_by=actor,
        metadata=metadata or {},
        **{fk: account},
    )
    account.balance = after
    account.save(update_fields=["balance", "updated_at"])
    return entry


@transaction.atomic
def create_wallet(owner, *, actor, provider_code, wallet_identifier, simulation_behavior="NORMAL"):
    """Simulated wallets are created by the administration (V1)."""
    require_role(actor, ADMIN_ROLES, school=owner.school)
    wallet = Wallet.objects.create(
        school=owner.school,
        owner=owner,
        provider_code=provider_code,
        wallet_identifier=wallet_identifier,
        currency=owner.school.currency,
        simulation_behavior=simulation_behavior,
    )
    _audit("WALLET_CREATED", actor, wallet, new={"owner": str(owner.pk), "provider": provider_code})
    return wallet


@transaction.atomic
def fund_wallet(wallet, amount, *, actor):
    """Simulation only: money "arrives" on a payer's wallet."""
    require_role(actor, ADMIN_ROLES, school=wallet.school)
    entry = _post(
        wallet,
        transaction_type=LedgerType.FUNDING,
        direction=LedgerDirection.CREDIT,
        amount=_money(amount),
        reference=f"FUND-{uuid.uuid4().hex[:12].upper()}",
        actor=actor,
    )
    _audit("WALLET_FUNDED", actor, wallet, new={"amount": str(entry.amount), "balance": str(entry.balance_after)})
    return entry


@transaction.atomic
def credit_treasury(school, amount, *, actor):
    require_role(actor, ADMIN_ROLES, school=school)
    treasury = get_treasury(school)
    entry = _post(
        treasury,
        transaction_type=LedgerType.FUNDING,
        direction=LedgerDirection.CREDIT,
        amount=_money(amount),
        reference=f"TFUND-{uuid.uuid4().hex[:12].upper()}",
        actor=actor,
    )
    _audit("TREASURY_CREDITED", actor, treasury, new={"amount": str(entry.amount)})
    return entry


# =============================================================================
# Fees and invoices
# =============================================================================


@transaction.atomic
def create_fee_type(school, *, actor, code, name, description=None):
    require_role(actor, ADMIN_ROLES, school=school)
    code = code.strip().upper()
    if FeeType.objects.filter(school=school, code=code).exists():
        raise ValidationError(f"A fee type {code} already exists.", code="duplicate_code")
    fee_type = FeeType.objects.create(school=school, code=code, name=name, description=description)
    _audit("FEE_TYPE_CREATED", actor, fee_type, new={"code": code}, layer=AuditLayer.ADMINISTRATIVE)
    return fee_type


@transaction.atomic
def create_fee_schedule(
    fee_type, *, actor, academic_year, amount, due_date, level=None, school_class=None, mandatory=True
):
    require_role(actor, ADMIN_ROLES, school=fee_type.school)
    schedule = FeeSchedule.objects.create(
        school=fee_type.school,
        fee_type=fee_type,
        academic_year=academic_year,
        level=level,
        school_class=school_class,
        amount=_money(amount),
        due_date=due_date,
        mandatory=mandatory,
    )
    _audit(
        "FEE_SCHEDULE_CREATED", actor, schedule, new={"amount": str(schedule.amount)}, layer=AuditLayer.ADMINISTRATIVE
    )
    return schedule


def _next_invoice_number(school, year):
    # Lock the school row: two simultaneous issuances never get the same number.
    School.objects.select_for_update().get(pk=school.pk)
    count = Invoice.objects.filter(school=school, academic_year=year).count()
    return f"F{year.start_date:%y}-{count + 1:06d}"


def _current_year(school):
    year = AcademicYear.objects.filter(school=school, is_current=True).first()
    if year is None:
        raise ValidationError("The school has no current academic year.", code="no_current_year")
    return year


def _recompute(invoice):
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    paid = invoice.allocations.aggregate(s=Sum("amount"))["s"] or ZERO
    invoice.amount_paid = paid
    invoice.balance_due = invoice.total_amount - paid
    if invoice.status != InvoiceStatus.CANCELLED:
        if paid == 0:
            invoice.status = InvoiceStatus.ISSUED
        elif invoice.balance_due == 0:
            invoice.status = InvoiceStatus.PAID
        else:
            invoice.status = InvoiceStatus.PARTIALLY_PAID
    invoice.save(update_fields=["amount_paid", "balance_due", "status", "updated_at"])
    return invoice


@transaction.atomic
def issue_invoice(student, *, actor, lines, due_date, payer=None):
    """lines: [{fee_type, description, quantity?, unit_price, fee_schedule?}]."""
    require_role(actor, ADMIN_ROLES, school=student.school)
    if not lines:
        raise ValidationError("An invoice needs at least one line.", code="invoice_empty")
    school = student.school
    year = _current_year(school)
    prepared = []
    for line in lines:
        fee_type = line["fee_type"]
        if fee_type.school_id != school.pk or not fee_type.active:
            raise ValidationError("Invalid fee type.", code="fee_type_invalid")
        quantity = Decimal(str(line.get("quantity", "1.00")))
        unit_price = Decimal(str(line["unit_price"])).quantize(CENT)
        prepared.append((fee_type, line, quantity, unit_price, (quantity * unit_price).quantize(CENT)))
    total = sum(p[4] for p in prepared)
    invoice = Invoice.objects.create(
        school=school,
        invoice_number=_next_invoice_number(school, year),
        student=student,
        payer=payer,
        academic_year=year,
        due_date=due_date,
        subtotal=total,
        total_amount=total,
        amount_paid=ZERO,
        balance_due=total,
        currency=school.currency,
        issued_by=actor,
    )
    for fee_type, line, quantity, unit_price, line_total in prepared:
        InvoiceLine.objects.create(
            school=school,
            invoice=invoice,
            fee_type=fee_type,
            fee_schedule=line.get("fee_schedule"),
            description=line.get("description") or fee_type.name,
            quantity=quantity,
            unit_price=unit_price,
            total=line_total,
        )
    _audit("INVOICE_ISSUED", actor, invoice, new={"number": invoice.invoice_number, "total": str(total)})
    return invoice


@transaction.atomic
def generate_invoices(school_class, *, actor):
    """Invoice every enrolled student of a class for the active fee schedules
    of the class's year that apply to it (whole year, its level, or the class)
    and are not invoiced yet. Idempotent."""
    require_role(actor, ADMIN_ROLES, school=school_class.school)
    schedules = [
        s
        for s in FeeSchedule.objects.filter(
            school=school_class.school, academic_year=school_class.academic_year, active=True, fee_type__active=True
        ).select_related("fee_type")
        if (s.school_class_id in (None, school_class.pk)) and (s.level_id in (None, school_class.level_id))
    ]
    created = []
    enrollments = (
        StudentEnrollment.objects.filter(school_class=school_class)
        .exclude(status=EnrollmentStatus.WITHDRAWN)
        .select_related("student")
    )
    for enrollment in enrollments:
        student = enrollment.student
        already = set(
            InvoiceLine.objects.filter(invoice__student=student, fee_schedule__in=schedules)
            .exclude(invoice__status=InvoiceStatus.CANCELLED)
            .values_list("fee_schedule_id", flat=True)
        )
        missing = [s for s in schedules if s.pk not in already]
        if missing and student.status == StudentStatus.ACTIVE:
            created.append(
                issue_invoice(
                    student,
                    actor=actor,
                    due_date=min(s.due_date for s in missing),
                    lines=[
                        {
                            "fee_type": s.fee_type,
                            "unit_price": s.amount,
                            "fee_schedule": s,
                            "description": s.fee_type.name,
                        }
                        for s in missing
                    ],
                )
            )
    return created


@transaction.atomic
def cancel_invoice(invoice, *, actor, reason):
    require_role(actor, ADMIN_ROLES, school=invoice.school)
    if not reason or not reason.strip():
        raise ValidationError("A reason is required.", code="reason_required")
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.status == InvoiceStatus.CANCELLED:
        raise ValidationError("This invoice is already cancelled.", code="invoice_cancelled")
    if invoice.allocations.exists():
        raise ValidationError(
            "An invoice with payments cannot be cancelled; refund first.", code="invoice_has_payments"
        )
    invoice.status = InvoiceStatus.CANCELLED
    invoice.cancelled_reason = reason.strip()
    invoice.save(update_fields=["status", "cancelled_reason", "updated_at"])
    _audit("INVOICE_CANCELLED", actor, invoice, new={"reason": reason.strip()})
    return invoice


# =============================================================================
# Payments
# =============================================================================


@dataclass
class PaymentOutcome:
    payment: Payment
    replayed: bool  # True: same idempotency key, existing payment returned


def _fingerprint(**parts):
    canonical = json.dumps({k: str(v) for k, v in sorted(parts.items())}, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def initiate_payment(
    student, *, actor, amount, payment_method, idempotency_key, wallet=None, invoices=(), fee_type=None, payer=None
):
    """Initiate (and, with the synchronous providers of V1, complete) a payment.

    Idempotency: the client generates `idempotency_key` once per payment
    intent. Same key + same request -> the existing payment is returned
    (replayed=True), whatever its status; same key + different request ->
    409 idempotency_conflict. A concurrent double submission hits the unique
    constraint and is resolved the same way.

    Failures (declined, insufficient funds, timeout, provider error) are
    RESULTS, recorded on the payment and returned — not exceptions.
    """
    school = student.school
    if actor is None or actor.school_id != school.pk:
        raise PermissionDenied("Not a member of this school.")
    if not can_pay(actor, student):
        raise PermissionDenied("You are not allowed to pay for this student.")
    key = (idempotency_key or "").strip()
    if not key:
        raise ValidationError("An idempotency key is required.", code="idempotency_key_required")
    amount = _money(amount)
    invoices = list(invoices)
    fingerprint = _fingerprint(
        student=student.pk,
        amount=amount,
        method=payment_method,
        wallet=getattr(wallet, "pk", None),
        invoices=sorted(str(i.pk) for i in invoices),
        fee_type=getattr(fee_type, "pk", None),
    )

    existing = Payment.objects.filter(school=school, idempotency_key=key).first()
    if existing is not None:
        return _replay(existing, fingerprint)

    try:
        with transaction.atomic():
            return PaymentOutcome(
                _execute(student, actor, amount, payment_method, key, fingerprint, wallet, invoices, fee_type, payer),
                replayed=False,
            )
    except IntegrityError:
        # Lost a race against an identical concurrent submission.
        existing = Payment.objects.filter(school=school, idempotency_key=key).first()
        if existing is None:
            raise
        return _replay(existing, fingerprint)


def _replay(existing, fingerprint):
    if existing.request_fingerprint != fingerprint:
        raise ValidationError(
            "This idempotency key was already used for a different payment.", code="idempotency_conflict"
        )
    return PaymentOutcome(existing, replayed=True)


def _execute(student, actor, amount, method, key, fingerprint, wallet, invoices, fee_type, payer):
    school = student.school
    is_admin = _is_admin(actor, school)
    if method == PaymentMethod.CASH:
        if not is_admin:
            raise PermissionDenied("Cash payments are recorded by the administration.")
        wallet = None
        payer = payer or actor
        if payer.school_id != school.pk:
            raise PermissionDenied("Payer of another school.")
    elif method == PaymentMethod.WALLET:
        if wallet is None:
            raise ValidationError("A wallet is required.", code="wallet_required")
        # Lock the wallet: the provider decision and the debit see the same balance.
        wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
        if wallet.school_id != school.pk or wallet.owner_id != actor.pk:
            raise PermissionDenied("You can only pay with your own wallet.")
        payer = actor
    else:
        raise ValidationError("Unknown payment method.", code="invalid_method")

    for invoice in invoices:
        if invoice.school_id != school.pk or invoice.student_id != student.pk:
            raise ValidationError("An invoice does not belong to this student.", code="invoice_other_student")
        if invoice.status not in (InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID):
            raise ValidationError("An invoice is not payable.", code="invoice_not_payable")
    if invoices:
        outstanding = sum(Invoice.objects.get(pk=i.pk).balance_due for i in invoices)
        if amount > outstanding:
            raise ValidationError("The amount exceeds the outstanding balance.", code="amount_exceeds_balance")
    elif fee_type is None or fee_type.school_id != school.pk or not fee_type.active:
        raise ValidationError("A payment settles invoices or has an active fee type.", code="payment_reason_required")

    provider = provider_for(method)
    reference = f"PAY-{uuid.uuid4().hex[:12].upper()}"
    payment = Payment.objects.create(
        school=school,
        payment_reference=reference,
        idempotency_key=key,
        request_fingerprint=fingerprint,
        student=student,
        payer=payer,
        initiated_by=actor,
        fee_type=fee_type,
        wallet=wallet,
        amount=amount,
        currency=school.currency,
        payment_method=method,
        provider=provider.code,
    )
    result = provider.charge(wallet=wallet, amount=amount, reference=reference)
    payment.completed_at = timezone.now()
    payment.provider_reference = result.provider_reference

    if result.status != PaymentStatus.SUCCEEDED:
        payment.status, payment.failure_reason = result.status, result.message
        payment.save()
        _audit("PAYMENT_FAILED", actor, payment, new={"status": result.status, "amount": str(amount)})
        return payment

    if provider.moves_simulated_wallet:
        _post(
            wallet,
            transaction_type=LedgerType.PAYMENT,
            direction=LedgerDirection.DEBIT,
            amount=amount,
            reference=reference,
            actor=actor,
            metadata={"payment": str(payment.pk)},
        )
    _post(
        get_treasury(school),
        transaction_type=LedgerType.PAYMENT,
        direction=LedgerDirection.CREDIT,
        amount=amount,
        reference=reference,
        actor=actor,
        metadata={"payment": str(payment.pk)},
    )

    remaining = amount
    for invoice in sorted(invoices, key=lambda i: (i.due_date, i.invoice_number)):
        if remaining <= 0:
            break
        balance = Invoice.objects.get(pk=invoice.pk).balance_due
        part = min(balance, remaining)
        if part > 0:
            PaymentAllocation.objects.create(
                school=school, payment=payment, invoice=invoice, student=student, amount=part
            )
            _recompute(invoice)
            remaining -= part

    payment.status = PaymentStatus.SUCCEEDED
    payment.save()
    _audit(
        "PAYMENT_SUCCEEDED",
        actor,
        payment,
        new={"amount": str(amount), "reference": reference, "invoices": [str(i.pk) for i in invoices]},
    )
    return payment


# =============================================================================
# Refunds
# =============================================================================


@transaction.atomic
def refund_payment(payment, *, actor, amount, reason):
    """Inverse transaction: a PaymentRefund + reversed ledger lines + negative
    allocations (latest first). The original payment row is never rewritten:
    only its refunded_amount / status progress (enforced by a trigger)."""
    require_role(actor, ADMIN_ROLES, school=payment.school)
    if not reason or not reason.strip():
        raise ValidationError("A reason is required.", code="reason_required")
    amount = _money(amount)
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.status not in (PaymentStatus.SUCCEEDED, PaymentStatus.PARTIALLY_REFUNDED):
        raise ValidationError("This payment cannot be refunded.", code="payment_not_refundable")
    if amount > payment.amount - payment.refunded_amount:
        raise ValidationError("The refund exceeds what remains of the payment.", code="refund_exceeds_payment")

    reference = f"REF-{uuid.uuid4().hex[:12].upper()}"
    refund = PaymentRefund.objects.create(
        school=payment.school,
        payment=payment,
        amount=amount,
        reason=reason.strip(),
        created_by=actor,
        completed_at=timezone.now(),
        inverse_transaction_reference=reference,
    )
    _post(
        get_treasury(payment.school),
        transaction_type=LedgerType.REFUND,
        direction=LedgerDirection.DEBIT,
        amount=amount,
        reference=reference,
        actor=actor,
        metadata={"payment": str(payment.pk), "refund": str(refund.pk)},
    )
    if payment.wallet_id and provider_for(payment.payment_method).moves_simulated_wallet:
        _post(
            payment.wallet,
            transaction_type=LedgerType.REFUND,
            direction=LedgerDirection.CREDIT,
            amount=amount,
            reference=reference,
            actor=actor,
            metadata={"payment": str(payment.pk), "refund": str(refund.pk)},
        )

    remaining = amount
    for allocation in payment.allocations.filter(refund__isnull=True).order_by("-allocated_at"):
        net = allocation.amount + (
            PaymentAllocation.objects.filter(
                payment=payment, invoice=allocation.invoice, refund__isnull=False
            ).aggregate(s=Sum("amount"))["s"]
            or ZERO
        )
        part = min(net, remaining)
        if part > 0:
            PaymentAllocation.objects.create(
                school=payment.school,
                payment=payment,
                invoice=allocation.invoice,
                student=payment.student,
                refund=refund,
                amount=-part,
            )
            _recompute(allocation.invoice)
            remaining -= part
        if remaining <= 0:
            break

    payment.refunded_amount += amount
    payment.status = (
        PaymentStatus.REFUNDED if payment.refunded_amount == payment.amount else PaymentStatus.PARTIALLY_REFUNDED
    )
    payment.save(update_fields=["refunded_amount", "status", "updated_at"])
    _audit(
        "PAYMENT_REFUNDED",
        actor,
        refund,
        new={"payment": str(payment.pk), "amount": str(amount), "reason": reason.strip()},
    )
    return refund


# =============================================================================
# Read models
# =============================================================================


def solvency(student):
    """UP_TO_DATE / OVERDUE: does the student have an overdue unpaid
    invoice (used in the QR scan answer, spec §7)?"""
    today = timezone.localdate()
    overdue = Invoice.objects.filter(
        student=student, status__in=[InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID], due_date__lt=today
    ).exists()
    return "OVERDUE" if overdue else "UP_TO_DATE"


def dashboard(school):
    payments = Payment.objects.filter(school=school)
    invoices = Invoice.objects.filter(school=school).exclude(status=InvoiceStatus.CANCELLED)
    open_invoices = invoices.filter(status__in=[InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID])
    collected = payments.filter(status__in=MONEY_RECEIVED).aggregate(s=Sum("amount"))["s"] or ZERO
    refunded = PaymentRefund.objects.filter(school=school).aggregate(s=Sum("amount"))["s"] or ZERO
    return {
        "currency": school.currency,
        "treasury_balance": get_treasury(school).balance,
        "collected": collected,
        "refunded": refunded,
        "net_collected": collected - refunded,
        "invoiced_total": invoices.aggregate(s=Sum("total_amount"))["s"] or ZERO,
        "outstanding": open_invoices.aggregate(s=Sum("balance_due"))["s"] or ZERO,
        "overdue_invoices": open_invoices.filter(due_date__lt=timezone.localdate()).count(),
        "payments_by_status": dict(payments.values_list("status").annotate(n=Count("id"))),
        "failed_payments": payments.filter(status__in=FAILED_STATUSES).count(),
    }
