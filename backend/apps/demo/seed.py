"""Builds the demonstration dataset (dataset.py) with the REAL domain services.

Nothing here writes a business table directly: the school is provisioned by
SchoolProvisioningService (ADR 0006), pupils are created by
admin_create_student, parents go through the parent workflow (ADR 0026),
wallets / funding / invoices / payments are Finance's own services (ADR 0013).

Re-running is safe (upsert): each object is looked up by its stable natural
key first. Finance is append-only (ledgers, payments), so there is no
"delete and recreate": what exists is kept, what is missing is added, and the
seeded payments use fixed idempotency keys (a second run replays them).
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone

from apps.academics import services as academics
from apps.academics.models import AcademicYear, AcademicYearStatus, Level, SchoolClass
from apps.accounts.models import SchoolMembership, User
from apps.core.models import School
from apps.core.services import FirstAdmin, SchoolProvisioningService
from apps.finance import services as finance
from apps.finance.models import FeeType, Invoice, InvoiceStatus, LedgerType, TreasuryTransaction, Wallet
from apps.people import parent_workflow
from apps.people import services as people
from apps.people.models import ParentStudent, RegistrationRequest, Student

from . import dataset

PRODUCTION_SETTINGS = "config.settings.production"


@dataclass
class DemoWorld:
    """What the seed created or found, by dataset key (used by the tests and the summary)."""

    school: School = None
    admin: SchoolMembership = None
    year: AcademicYear = None
    classes: dict = field(default_factory=dict)
    students: dict = field(default_factory=dict)
    parents: dict = field(default_factory=dict)  # key -> SchoolMembership
    fee_types: dict = field(default_factory=dict)
    invoices: dict = field(default_factory=dict)
    wallets: dict = field(default_factory=dict)  # parent key -> Wallet
    created: list = field(default_factory=list)  # what this run added (for the report)


def _refuse_production():
    if settings.SETTINGS_MODULE == PRODUCTION_SETTINGS:
        raise ImproperlyConfigured("The demo dataset is never loaded with the production settings.")


def _need_password(password):
    if not password:
        raise ImproperlyConfigured(
            "DEMO_PASSWORD is required to create the demo accounts (it is never stored nor printed)."
        )
    return password


# --- school, admin, year, classes ------------------------------------------------------


def _school(w, password):
    school = School.objects.filter(code=dataset.SCHOOL["code"]).first()
    if school is None:
        provisioned = SchoolProvisioningService().provision(
            **dataset.SCHOOL, admin=FirstAdmin(password=_need_password(password), **dataset.ADMIN)
        )
        w.created.append(f"établissement {dataset.SCHOOL['code']} + administrateur {dataset.ADMIN['username']}")
        school, w.admin = provisioned.school, provisioned.admin_membership
    else:
        w.admin = SchoolMembership.objects.get(school=school, user__username=dataset.ADMIN["username"])
    w.school = school


def _year(w):
    today = timezone.localdate()
    year = AcademicYear.objects.filter(school=w.school, start_date__lte=today, end_date__gte=today).first()
    if year is None:
        start = date(today.year if today.month >= 9 else today.year - 1, 9, 1)
        year = academics.create_academic_year(
            w.school,
            name=f"{start.year}-{start.year + 1}",
            start_date=start,
            end_date=date(start.year + 1, 7, 31),
            status=AcademicYearStatus.ACTIVE,
        )
        w.created.append(f"année {year.name}")
    if not year.is_current:
        year = academics.set_current_year(year)
    w.year = year


def _classes(w):
    levels = {}
    for spec in dataset.LEVELS:
        level = Level.objects.filter(school=w.school, code=spec["code"]).first()
        if level is None:
            level = academics.create_level(w.school, actor=w.admin, **spec)
            w.created.append(f"niveau {spec['code']}")
        levels[spec["code"]] = level
    for spec in dataset.CLASSES:
        klass = SchoolClass.objects.filter(school=w.school, academic_year=w.year, name=spec["name"]).first()
        if klass is None:
            klass = academics.create_class(
                w.school, actor=w.admin, name=spec["name"], level=levels[spec["level"]], academic_year=w.year
            )
            w.created.append(f"classe {spec['name']}")
        w.classes[spec["name"]] = klass


# --- pupils ------------------------------------------------------------------------------


def _students(w):
    for spec in dataset.STUDENTS:
        student = Student.objects.filter(school=w.school, student_number=spec["student_number"]).first()
        if student is None:
            fields = {k: v for k, v in spec.items() if k not in ("key", "class")}
            fields["date_of_birth"] = date.fromisoformat(fields["date_of_birth"])
            # The canonical path of the admin client: identity + enrollment in ONE transaction.
            student = people.admin_create_student(
                w.school, actor=w.admin, enrollment={"school_class": w.classes[spec["class"]]}, **fields
            )
            w.created.append(f"élève {spec['student_number']}")
        w.students[spec["key"]] = student


# --- parents (real workflow, ADR 0026) ------------------------------------------------------


def _parent(w, spec, password):
    user = User.objects.filter(email__iexact=spec["email"]).first()
    if user is None:
        parent_workflow.register_parent(
            first_name=spec["first_name"],
            last_name=spec["last_name"],
            email=spec["email"],
            password=_need_password(password),
            phone=spec["phone"],
            school_code=w.school.code,
        )
        w.created.append(f"compte parent {spec['email']}")
    membership = SchoolMembership.objects.get(school=w.school, user__email__iexact=spec["email"])
    pending = RegistrationRequest.objects.filter(membership=membership, status="PENDING").first()
    if pending is not None:
        parent_workflow.approve_registration(pending, actor=w.admin)
        membership.refresh_from_db()
    w.parents[spec["key"]] = membership
    for child in spec["children"]:
        _link(w, membership, spec, w.students[child["student"]], child["relationship"])


def _link(w, membership, spec, student, relationship):
    if ParentStudent.objects.filter(
        parent__membership=membership, student=student, identity_verified=True, active=True
    ).exists():
        return
    request = parent_workflow.request_link(
        membership,
        student_number=student.student_number,
        date_of_birth=student.date_of_birth,
        relationship_type=relationship,
        document_type="CNI",
        document_number=spec["document"],
    )
    parent_workflow.check_identity(request, actor=w.admin, document_type="CNI", document_number=spec["document"])
    parent_workflow.record_student_approval(request, actor=w.admin, decision="APPROVED", note="Jeu de démonstration")
    parent_workflow.approve_link_request(request, actor=w.admin, **dataset.LINK_RIGHTS)
    w.created.append(f"lien {spec['key']} -> {student.student_number}")


# --- finance (ADR 0013 services only) -------------------------------------------------------


def _fee_types(w):
    for spec in dataset.FEE_TYPES:
        fee_type = FeeType.objects.filter(school=w.school, code=spec["code"]).first()
        if fee_type is None:
            fee_type = finance.create_fee_type(w.school, actor=w.admin, **spec)
            w.created.append(f"motif {spec['code']}")
        w.fee_types[spec["code"]] = fee_type


def _invoices(w):
    today = timezone.localdate()
    for spec in dataset.INVOICES:
        student, fee_type = w.students[spec["student"]], w.fee_types[spec["fee_type"]]
        invoice = (
            Invoice.objects.filter(school=w.school, student=student, lines__fee_type=fee_type)
            .exclude(status=InvoiceStatus.CANCELLED)
            .order_by("issue_date")
            .first()
        )
        if invoice is None:
            invoice = finance.issue_invoice(
                student,
                actor=w.admin,
                due_date=today + timedelta(days=spec["due_in_days"]),
                lines=[{"fee_type": fee_type, "unit_price": spec["amount"]}],
            )
            w.created.append(f"facture {invoice.invoice_number} ({spec['key']})")
        w.invoices[spec["key"]] = invoice


def _wallets(w):
    for spec in dataset.WALLETS:
        wallet = Wallet.objects.filter(
            school=w.school, provider_code=spec["provider"], wallet_identifier=spec["identifier"]
        ).first()
        if wallet is None:
            wallet = finance.create_wallet(
                w.parents[spec["owner"]],
                actor=w.admin,
                provider_code=spec["provider"],
                wallet_identifier=spec["identifier"],
            )
            if spec["balance"] > 0:
                finance.fund_wallet(wallet, spec["balance"], actor=w.admin)
            wallet.refresh_from_db()
            w.created.append(f"wallet {spec['provider']}:{spec['identifier']} ({spec['balance']} XAF)")
        w.wallets[spec["owner"]] = wallet


def _treasury(w):
    funded = TreasuryTransaction.objects.filter(school=w.school, transaction_type=LedgerType.FUNDING).exists()
    if not funded:
        finance.credit_treasury(w.school, dataset.TREASURY_FUNDING, actor=w.admin)
        w.created.append(f"trésorerie +{dataset.TREASURY_FUNDING} XAF")


def _cash_payments(w):
    for spec in dataset.CASH_PAYMENTS:
        invoice = w.invoices[spec["invoice"]]
        outcome = finance.initiate_payment(
            invoice.student,
            actor=w.admin,
            amount=spec["amount"],
            payment_method="CASH",
            idempotency_key=spec["key"],
            invoices=[invoice],
            payer=w.parents[spec["payer"]],
        )
        if not outcome.replayed:
            w.created.append(f"paiement guichet {outcome.payment.payment_reference} ({spec['amount']} XAF)")
        w.invoices[spec["invoice"]] = Invoice.objects.get(pk=invoice.pk)


# --- entry points -----------------------------------------------------------------------


@transaction.atomic
def seed(*, password=None):
    """Create what is missing of the demo dataset; returns the DemoWorld.
    All or nothing: one transaction (a failure leaves no half dataset)."""
    _refuse_production()
    w = DemoWorld()
    _school(w, password)
    _year(w)
    _classes(w)
    _students(w)
    for spec in dataset.PARENTS:
        _parent(w, spec, password)
    _fee_types(w)
    _invoices(w)
    _wallets(w)
    _treasury(w)
    _cash_payments(w)
    return w


@transaction.atomic
def refill_wallets():
    """Top every demo wallet up to its dataset balance (FUNDING, ledger kept).
    A wallet above its target is left as is: Finance has no "withdrawal"."""
    _refuse_production()
    school = School.objects.get(code=dataset.SCHOOL["code"])
    admin = SchoolMembership.objects.get(school=school, user__username=dataset.ADMIN["username"])
    refilled = []
    for spec in dataset.WALLETS:
        wallet = Wallet.objects.get(school=school, provider_code=spec["provider"], wallet_identifier=spec["identifier"])
        missing = spec["balance"] - wallet.balance
        if missing > Decimal("0"):
            finance.fund_wallet(wallet, missing, actor=admin)
            refilled.append((spec["owner"], missing))
    return refilled
