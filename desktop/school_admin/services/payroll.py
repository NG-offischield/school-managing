"""Payroll (backend payroll/api.py, ADR 0014 / 0022). Thin client of the
EXISTING payroll engine: the server calculates (programmed, earned, salary,
corrections), checks that an approved payroll still matches its sources
(409 payroll_stale), pays through Finance (treasury debit) and refuses any
second payment. Nothing is computed here.

    Période → Calculer → Préparer (CALCULATED) → Vérifier (détail) → Approuver → Payer

    GET|POST /admin/payroll/periods/   GET /admin/payroll/periods/{id}/   POST …/{id}/close/
    POST /admin/payroll/calculate/ {period}
    GET  /admin/payroll/?period=&status=&kind=&employee=   GET /admin/payroll/{id}/
    POST /admin/payroll/{id}/approve/ | /pay/ {payout_method, wallet?} | /cancel/ {reason}
    GET|POST /admin/payroll/adjustments/   GET /admin/payroll/remuneration/?employee=&date_from=&date_to=
    GET  /admin/payroll/check-ins/?teacher=&status=
"""

from ..api.errors import ValidationFailed
from ..i18n import tr
from ..models import Adjustment, Payroll, PayrollPeriod
from ..money import amount_text, parse_amount, to_decimal


def _require(**fields):
    missing = {name: [tr("Obligatoire.")] for name, value in fields.items() if value in (None, "")}
    if missing:
        raise ValidationFailed("Formulaire incomplet.", details=missing)


class PayrollService:
    def __init__(self, api):
        self.api = api

    # --- periods ----------------------------------------------------------------------
    def periods(self):
        return [PayrollPeriod.from_api(r) for r in self.api.list_all("admin/payroll/periods/")]

    def create_period(self, *, year_id, name, start, end):
        _require(academic_year=year_id, name=(name or "").strip(), start_date=start, end_date=end)
        payload = {
            "academic_year": year_id,
            "name": name.strip(),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        }
        return PayrollPeriod.from_api(self.api.post("admin/payroll/periods/", payload))

    def close_period(self, period_id):
        return PayrollPeriod.from_api(self.api.post(f"admin/payroll/periods/{period_id}/close/"))

    def calculate(self, period_id):
        """{"created", "recalculated", "unchanged", "frozen", "warnings"} as reported by the server."""
        _require(period=period_id)
        return self.api.post("admin/payroll/calculate/", {"period": period_id})

    # --- payrolls ---------------------------------------------------------------------
    def payrolls(self, *, period_id=None, status=None, kind=None, employee_id=None):
        rows = self.api.get(
            "admin/payroll/",
            period=period_id or None,
            status=status or None,
            kind=kind or None,
            employee=employee_id or None,
        )
        return [Payroll.from_api(r) for r in rows or []]

    def payroll(self, payroll_id):
        """Every version of the lines, and whether it still matches its sources."""
        return Payroll.from_api(self.api.get(f"admin/payroll/{payroll_id}/"))

    def approve(self, payroll_id):
        return Payroll.from_api(self.api.post(f"admin/payroll/{payroll_id}/approve/"))

    def pay(self, payroll_id, *, method, wallet_id=None):
        _require(payout_method=method)
        payload = {"payout_method": method, "wallet": wallet_id or None}
        return Payroll.from_api(self.api.post(f"admin/payroll/{payroll_id}/pay/", payload))

    def cancel(self, payroll_id, reason):
        _require(reason=(reason or "").strip())
        return Payroll.from_api(self.api.post(f"admin/payroll/{payroll_id}/cancel/", {"reason": reason.strip()}))

    # --- corrections ------------------------------------------------------------------
    def adjustments(self, *, employee_id=None):
        return [Adjustment.from_api(r) for r in self.api.list_all("admin/payroll/adjustments/", employee=employee_id)]

    def create_adjustment(self, *, employee_id, amount, reason, effective_date=None):
        value = parse_amount(amount) if isinstance(amount, str) else amount
        if value is None:
            raise ValidationFailed("Montant invalide.", details={"amount": [tr("Saisissez un montant (ex. -5000).")]})
        _require(employee=employee_id, reason=(reason or "").strip())
        payload = {"employee": employee_id, "amount": amount_text(value), "reason": reason.strip()}
        if effective_date:
            payload["effective_date"] = effective_date.isoformat()
        return Adjustment.from_api(self.api.post("admin/payroll/adjustments/", payload))

    # --- read-only views (teacher record) ---------------------------------------------
    def remuneration(self, employee_id, date_from, date_to):
        """Programmed / earned (validated, unpaid) / paid amounts of the range, as computed by the server."""
        data = self.api.get(
            "admin/payroll/remuneration/",
            employee=employee_id,
            date_from=date_from.isoformat(),
            date_to=date_to.isoformat(),
        )
        return {k: to_decimal(v) if k.endswith("_amount") or k == "monthly_salary" else v for k, v in data.items()}

    def validated_sessions(self, teacher_id):
        """Number of sessions of the teacher validated by the administration."""
        return len(self.api.list_all("admin/payroll/check-ins/", teacher=teacher_id, status="VALIDATED"))
