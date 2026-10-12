"""Finance (backend finance/api.py, ADR 0013 / 0022). Thin client: the server
decides everything — who may pay, the provider's outcome (succeeded,
declined, insufficient funds, timeout, provider error), allocations,
refundable amounts, idempotency. This module only checks that required
fields are filled and that an amount is a number, then relays the answer.
Amounts travel as strings and are read as Decimal (money.py).

    GET  /admin/finance/dashboard/ | /admin/finance/treasury/
    GET  /finance/payments/?status=&payment_method=&search=&date_from=&date_to=   (paginated)
    POST /finance/payments/                  {student, amount, payment_method, invoices|fee_type, wallet?,
                                              idempotency_key}  -> 201 whatever the outcome, 200 = replay
    POST /admin/finance/payments/{id}/refund/ {amount, reason}
    GET  /finance/invoices/?status=&search=&date_from=&date_to=   POST /admin/finance/invoices/
    POST /admin/finance/invoices/{id}/cancel/   GET /finance/students/{id}/obligations/
    GET  /admin/finance/refunds/   GET|POST /admin/finance/fee-types/
    GET  /admin/finance/wallets/ (school)   GET /finance/wallets/ (the caller's own)
"""

import uuid
from datetime import date, timedelta

from ..api.errors import ValidationFailed
from ..i18n import Labels, tr
from ..models import FeeType, Invoice, Payment, Refund, TreasuryEntry, Wallet
from ..money import amount_text, parse_amount, to_decimal

PERIODS = Labels(
    {
        "": "Période : toutes",
        "today": "Aujourd'hui",
        "7": "7 derniers jours",
        "30": "30 derniers jours",
        "month": "Ce mois-ci",
    }
)


def period_range(key, today):
    """(date_from, date_to) of a period filter — a display filter, not a rule."""
    if key == "today":
        return today, today
    if key in ("7", "30"):
        return today - timedelta(days=int(key) - 1), today
    if key == "month":
        return today.replace(day=1), today
    return None, None


def _require(**fields):
    missing = {name: [tr("Obligatoire.")] for name, value in fields.items() if value in (None, "", [])}
    if missing:
        raise ValidationFailed("Formulaire incomplet.", details=missing)


def _amount(text, field="amount"):
    value = parse_amount(text) if not hasattr(text, "as_tuple") else text
    if value is None:
        raise ValidationFailed(
            "Montant invalide.", details={field: [tr("Saisissez un montant (ex. 15000 ou 15000,50).")]}
        )
    return amount_text(value)


def new_idempotency_key():
    """One key per payment INTENT: a retry of the same intent reuses it."""
    return str(uuid.uuid4())


class FinanceService:
    PAGE_SIZE = 50

    def __init__(self, api, *, today=None):
        self.api = api
        self.today = today or date.today

    # --- overview -------------------------------------------------------------------
    def dashboard(self):
        return self.api.get("admin/finance/dashboard/")

    def treasury(self):
        data = self.api.get("admin/finance/treasury/")
        entries = [TreasuryEntry.from_api(r) for r in data.get("recent_transactions") or []]
        return to_decimal(data.get("balance")), data.get("currency", ""), entries

    # --- payments -------------------------------------------------------------------
    def payments(self, *, page=1, search=None, status=None, method=None, period=""):
        date_from, date_to = period_range(period, self.today())
        rows, total = self.api.page(
            "finance/payments/",
            page=page,
            page_size=self.PAGE_SIZE,
            search=(search or "").strip() or None,
            status=status or None,
            payment_method=method or None,
            date_from=date_from.isoformat() if date_from else None,
            date_to=date_to.isoformat() if date_to else None,
        )
        return [Payment.from_api(r) for r in rows], total

    def payment(self, payment_id):
        return Payment.from_api(self.api.get(f"finance/payments/{payment_id}/"))

    def initiate(
        self, *, student_id, amount, method, idempotency_key, invoice_ids=(), fee_type_id=None, wallet_id=None
    ):
        """Initiate a payment. A failed outcome is a RESULT (status on the
        returned payment), not an exception."""
        _require(student=student_id, payment_method=method, idempotency_key=idempotency_key)
        payload = {
            "student": student_id,
            "amount": _amount(amount),
            "payment_method": method,
            "invoices": list(invoice_ids),
            "fee_type": fee_type_id or None,
            "wallet": wallet_id or None,
            "idempotency_key": idempotency_key,
        }
        return Payment.from_api(self.api.post("finance/payments/", payload))

    def refund(self, payment_id, *, amount, reason):
        _require(reason=(reason or "").strip())
        payload = {"amount": _amount(amount), "reason": reason.strip()}
        return Refund.from_api(self.api.post(f"admin/finance/payments/{payment_id}/refund/", payload))

    def refunds(self, *, page=1, search=None, period=""):
        date_from, date_to = period_range(period, self.today())
        rows, total = self.api.page(
            "admin/finance/refunds/",
            page=page,
            page_size=self.PAGE_SIZE,
            search=(search or "").strip() or None,
            date_from=date_from.isoformat() if date_from else None,
            date_to=date_to.isoformat() if date_to else None,
        )
        return [Refund.from_api(r) for r in rows], total

    # --- invoices (obligations) -----------------------------------------------------
    def invoices(self, *, page=1, search=None, status=None, period=""):
        date_from, date_to = period_range(period, self.today())
        rows, total = self.api.page(
            "finance/invoices/",
            page=page,
            page_size=self.PAGE_SIZE,
            search=(search or "").strip() or None,
            status=status or None,
            date_from=date_from.isoformat() if date_from else None,
            date_to=date_to.isoformat() if date_to else None,
        )
        return [Invoice.from_api(r) for r in rows], total

    def invoice(self, invoice_id):
        return Invoice.from_api(self.api.get(f"finance/invoices/{invoice_id}/"))

    def obligations(self, student_id):
        """Open invoices of a student (balance and solvency computed by the server)."""
        data = self.api.get(f"finance/students/{student_id}/obligations/")
        return [Invoice.from_api(r) for r in data.get("open_invoices") or []]

    def issue_invoice(self, *, student_id, due_date, fee_type_id, amount, description=None):
        _require(student=student_id, due_date=due_date, fee_type=fee_type_id)
        line = {"fee_type": fee_type_id, "unit_price": _amount(amount, "unit_price"), "quantity": "1"}
        if (description or "").strip():
            line["description"] = description.strip()
        payload = {"student": student_id, "due_date": due_date.isoformat(), "lines": [line]}
        return Invoice.from_api(self.api.post("admin/finance/invoices/", payload))

    def cancel_invoice(self, invoice_id, reason):
        _require(reason=(reason or "").strip())
        return Invoice.from_api(self.api.post(f"admin/finance/invoices/{invoice_id}/cancel/", {"reason": reason}))

    # --- references -----------------------------------------------------------------
    def fee_types(self):
        return [FeeType.from_api(r) for r in self.api.list_all("admin/finance/fee-types/")]

    def create_fee_type(self, *, code, name, description=None):
        _require(code=(code or "").strip(), name=(name or "").strip())
        payload = {"code": code.strip(), "name": name.strip(), "description": (description or "").strip() or None}
        return FeeType.from_api(self.api.post("admin/finance/fee-types/", payload))

    def wallets(self):
        return [Wallet.from_api(r) for r in self.api.list_all("admin/finance/wallets/")]

    def my_wallets(self):
        """The logged-in administrator's own wallets (the only ones they may pay with)."""
        return [Wallet.from_api(r) for r in self.api.list_all("finance/wallets/")]

    def find_students(self, text):
        """(id, label) of the students matching `text` (server search, first page)."""
        rows, _ = self.api.page("students/", page=1, page_size=20, search=(text or "").strip() or None)
        return [
            (r["id"], f"{r.get('last_name', '')} {r.get('first_name', '')} ({r.get('student_number', '')})".strip())
            for r in rows
        ]
