"""Payroll dialogs (ADR 0022). The engine (calculation, approval checks,
payment through Finance) is the server's; these forms only collect choices
and show what the server computed. Amounts: Decimal, formatted."""

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QComboBox, QLabel, QLineEdit, QPlainTextEdit

from ...models import EMPLOYEE_KINDS, LINE_KINDS, PAYOUT_METHODS, PAYROLL_STATUSES
from ...money import format_money, parse_amount
from ..widgets import FormDialog, button, date_field
from .teacher_dialogs import _grid

WORKFLOW = "Période → Calculer → Préparer → Vérifier → Approuver → Payer"


def _day(value):
    return f"{value:%d/%m/%Y}" if value else "—"


class PeriodDialog(FormDialog):
    def __init__(self, years, parent=None):
        super().__init__(
            "Nouvelle période de paie",
            "Fenêtre de calcul (souvent un mois). Les périodes d'une école ne se chevauchent pas.",
            parent,
            width=560,
        )
        self.year = QComboBox()
        for year in years:
            self.year.addItem(year.name, year.id)
            if year.is_current:
                self.year.setCurrentIndex(self.year.count() - 1)
        self.year = self.add_field("year", "Année scolaire", self.year, required=True, width="medium")
        self.name = self.add_field("name", "Nom", QLineEdit(placeholderText="ex. Octobre 2025"), required=True)
        today = QDate.currentDate()
        self.start = self.add_field("start", "Du", date_field(), required=True, width="short")
        self.end = self.add_field("end", "Au", date_field(), required=True, width="short", beside=True)
        self.start.setDate(QDate(today.year(), today.month(), 1))
        self.end.setDate(QDate(today.year(), today.month(), today.daysInMonth()))
        self.name.textChanged.connect(self.refresh_state)
        self.start.dateChanged.connect(lambda _: self.refresh_state())
        self.end.dateChanged.connect(lambda _: self.refresh_state())
        self.finish()

    def missing_fields(self):
        missing = [] if self.year.currentData() else ["Année scolaire"]
        missing += [] if self.name.text().strip() else ["Nom"]
        if self.end.date() < self.start.date():
            self.status.setText("La fin doit suivre le début.")
            missing.append("dates (la fin doit suivre le début)")
        return missing

    def values(self):
        return {
            "year_id": self.year.currentData(),
            "name": self.name.text().strip(),
            "start": self.start.date().toPython(),
            "end": self.end.date().toPython(),
        }


class PayDialog(FormDialog):
    """Pay an approved payroll: the server debits the treasury (and credits
    the employee's own simulated wallet) — once."""

    def __init__(self, payroll, wallets, parent=None):
        super().__init__(
            f"Payer — {payroll.employee_name}",
            "Le paiement passe par la Finance (débit de la trésorerie de l'école). Un second paiement est impossible.",
            parent,
            save_text="Payer",
            width=560,
        )
        self.body.addWidget(
            _grid(
                [
                    ("Période", payroll.period_name),
                    ("Montant approuvé", format_money(payroll.approved, payroll.currency)),
                ]
            )
        )
        self.method = QComboBox()
        for code, label in PAYOUT_METHODS.items():
            self.method.addItem(label, code)
        self.method = self.add_field("method", "Mode de versement", self.method, required=True, width="medium")
        self.wallet = QComboBox()
        for wallet in wallets:
            self.wallet.addItem(f"{wallet.code} — {wallet.owner_name}", wallet.id)
        self.wallet = self.add_field(
            "wallet",
            "Wallet de l'employé",
            self.wallet,
            help_text="Seul le wallet de l'employé est accepté (règle du serveur)."
            if wallets
            else "Aucun wallet au nom de l'employé : versement en espèces / hors système.",
        )
        if not wallets:
            self.method.model().item(self.method.findData("WALLET")).setEnabled(False)
        self.method.currentIndexChanged.connect(lambda _: self._changed())
        self._changed()
        self.finish()

    def _changed(self):
        self.wallet.setEnabled(self.method.currentData() == "WALLET")
        self.refresh_state()

    def missing_fields(self):
        return ["Wallet"] if self.method.currentData() == "WALLET" and not self.wallet.currentData() else []

    def values(self):
        method = self.method.currentData()
        return {"method": method, "wallet_id": self.wallet.currentData() if method == "WALLET" else None}


class PayrollDetailDialog(FormDialog):
    """Vérifier: what the server calculated, every version of the lines kept.
    Buttons close it with `action` = approve / pay / cancel."""

    def __init__(self, payroll, parent=None):
        super().__init__(
            f"Paie — {payroll.employee_name} · {payroll.period_name}", WORKFLOW, parent, save_text="Fermer", width=640
        )
        self.action = None
        self.cancel_button.hide()
        money = lambda value: format_money(value, payroll.currency) if value is not None else "—"  # noqa: E731
        rows = [
            ("Statut", PAYROLL_STATUSES.get(payroll.status, payroll.status)),
            ("Type", EMPLOYEE_KINDS.get(payroll.kind, payroll.kind)),
            ("Version du calcul", str(payroll.version)),
        ]
        if payroll.kind == "TEACHER":
            rows += [
                ("Rémunération programmée", f"{money(payroll.programmed)} ({payroll.scheduled_count} séance(s))"),
                ("Rémunération acquise", f"{money(payroll.earned)} ({payroll.payable_count} séance(s) validée(s))"),
            ]
        else:
            rows.append(("Salaire fixe", money(payroll.base_salary)))
        rows += [
            ("Corrections", money(payroll.adjustments)),
            ("À payer", money(payroll.payable)),
            ("Montant approuvé", money(payroll.approved) if payroll.status in ("APPROVED", "PAID") else "—"),
        ]
        if payroll.paid_at:
            rows.append(("Payée le", f"{payroll.paid_at:%d/%m/%Y %H:%M} · {payroll.payment_reference}"))
        if payroll.cancelled_reason:
            rows.append(("Motif d'annulation", payroll.cancelled_reason))
        self.body.addWidget(_grid(rows))
        if payroll.reconstructible is False and payroll.status == "CALCULATED":
            warning = QLabel(
                "Les données ont changé depuis ce calcul : recalculez la période avant d'approuver.", objectName="help"
            )
            warning.setWordWrap(True)
            self.body.addWidget(warning)
        current = [line for line in payroll.lines if line.version == payroll.version]
        older = len({line.version for line in payroll.lines if line.version != payroll.version})
        self.add_section("Lignes du calcul", f"{older} version(s) antérieure(s) conservée(s)." if older else "")
        self.body.addWidget(
            _grid(
                [
                    (
                        LINE_KINDS.get(line.kind, line.kind) + (" (rattrapage)" if line.late else ""),
                        " · ".join(
                            part
                            for part in (
                                _day(line.session_date) if line.session_date else "",
                                f"{line.minutes} min" if line.minutes else "",
                                money(line.amount),
                            )
                            if part
                        ),
                    )
                    for line in current
                ]
            )
            if current
            else QLabel("Aucune ligne.", objectName="help")
        )
        actions = {
            "CALCULATED": [("approve", "Approuver", "primary"), ("cancel", "Annuler la paie…", "danger")],
            "APPROVED": [("pay", "Payer…", "primary"), ("cancel", "Annuler la paie…", "danger")],
        }.get(payroll.status, [])
        self.buttons = {}
        for name, text, variant in actions:
            widget = button(text, variant)
            widget.clicked.connect(lambda _=False, n=name: self._start(n))
            self.buttons[name] = widget
            self.body.addWidget(widget, 0, Qt.AlignLeft)
        self.finish(required_note=False)

    def _start(self, action):
        self.action = action
        self.accept()


class AdjustmentDialog(FormDialog):
    """Manual correction (bonus +, recovery −): applied by the employee's next paid payroll."""

    def __init__(self, employees, parent=None):
        super().__init__(
            "Nouvelle correction",
            "Prime (montant positif) ou retenue (montant négatif). Elle s'applique à la prochaine paie payée.",
            parent,
            width=560,
        )
        self.employee = QComboBox()
        self.employee.addItem("— choisir —", None)
        for employee_id, label in employees:
            self.employee.addItem(label, employee_id)
        self.employee = self.add_field("employee", "Employé", self.employee, required=True, width="medium")
        self.amount = QLineEdit(placeholderText="ex. 15000 ou -5000")
        self.amount.setAlignment(Qt.AlignRight)
        self.amount = self.add_field("amount", "Montant", self.amount, required=True, width="short")
        self.effective = self.add_field("effective", "Date d'effet", date_field(), width="short", beside=True)
        self.effective.setDate(QDate.currentDate())
        reason = QPlainTextEdit(placeholderText="Motif (obligatoire)")
        reason.setFixedHeight(72)
        reason.setTabChangesFocus(True)
        self.reason = self.add_field("reason", "Motif", reason, required=True)
        self.employee.currentIndexChanged.connect(lambda _: self.refresh_state())
        self.amount.textChanged.connect(self.refresh_state)
        self.reason.textChanged.connect(self.refresh_state)
        self.finish()

    def missing_fields(self):
        missing = [] if self.employee.currentData() else ["Employé"]
        missing += [] if parse_amount(self.amount.text()) is not None else ["Montant"]
        return missing + ([] if self.reason.toPlainText().strip() else ["Motif"])

    def values(self):
        return {
            "employee_id": self.employee.currentData(),
            "amount": self.amount.text().strip(),
            "reason": self.reason.toPlainText().strip(),
            "effective_date": self.effective.date().toPython(),
        }


class TeacherPayDialog(FormDialog):
    """Read-only remuneration of one teacher (from the teacher record): the
    server's figures for the range, its payrolls and validated sessions."""

    def __init__(self, teacher, summary, payrolls, validated, date_from, date_to, parent=None):
        super().__init__(
            f"Rémunération — {teacher.name}",
            f"Lecture seule, du {_day(date_from)} au {_day(date_to)}. La paie se gère dans le module Paie.",
            parent,
            save_text="Fermer",
            width=640,
        )
        self.cancel_button.hide()
        currency = next((p.currency for p in payrolls), "")
        money = lambda value: format_money(value, currency) if value is not None else "—"  # noqa: E731
        if summary is None:
            self.body.addWidget(QLabel("Rémunération non disponible (droits ou données).", objectName="help"))
        else:
            sessions = summary.get("sessions") or {}
            self.body.addWidget(
                _grid(
                    [
                        (
                            "Programmée",
                            f"{money(summary.get('programmed_amount'))} ({sessions.get('scheduled', 0)} séance(s))",
                        ),
                        (
                            "Acquise (validée, non payée)",
                            f"{money(summary.get('earned_unpaid_amount'))} ({sessions.get('validated', 0)} séance(s))",
                        ),
                        ("Payée", f"{money(summary.get('paid_amount'))} ({sessions.get('paid', 0)} séance(s))"),
                        ("Séances sans taux", str(sessions.get("missing_rate", 0))),
                        ("Séances validées (total)", str(validated)),
                    ]
                )
            )
        self.add_section("Paies")
        self.body.addWidget(
            _grid(
                [
                    (
                        p.period_name,
                        f"{PAYROLL_STATUSES.get(p.status, p.status)} · à payer {money(p.payable)}"
                        + (f" · payée le {p.paid_at:%d/%m/%Y}" if p.paid_at else ""),
                    )
                    for p in payrolls
                ]
            )
            if payrolls
            else QLabel("Aucune paie calculée pour cet enseignant.", objectName="help")
        )
        self.finish(required_note=False)
