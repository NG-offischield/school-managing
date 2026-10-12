"""Administration → Paie (ADR 0022): the admin face of the EXISTING payroll
engine (ADR 0014), paid through the EXISTING finance domain. Tabs:

    Périodes     periods: new, Calculer (prepare / re-prepare, idempotent), Clôturer
    Paies        prepared / approved / paid / cancelled payrolls: Vérifier (detail),
                 Approuver, Payer (treasury debit, once), Annuler
    Corrections  bonuses and recoveries, applied by the next paid payroll

    Période → Calculer → Préparer → Vérifier → Approuver → Payer

The server calculates and refuses (409 payroll_stale when the sources changed
since the calculation, payroll_already_paid on a second payment…); the
screens show its figures and its answers. Amounts: Decimal, never floats.
"""

from PySide6.QtWidgets import QDialog, QLabel, QTabWidget

from ...i18n import Labels, Tr, tr
from ...models import EMPLOYEE_KINDS, PAYROLL_STATUSES, PERIOD_STATUSES
from ...money import format_money
from ..dialogs.payroll_dialogs import WORKFLOW, AdjustmentDialog, PayDialog, PayrollDetailDialog, PeriodDialog
from ..dialogs.teacher_dialogs import ask_reason
from ..theme import TOKENS, TokenColours
from ..widgets import Page, button
from .catalog_base import STATUS_COLUMN_TITLE, CatalogPage
from .finance_page import coloured, money_cell
from .planning_page import _combo, _refill

WARNINGS = Labels(
    {
        "missing_rate": "séance(s) sans taux de vacation",
        "missing_salary": "employé(s) sans salaire défini",
        "adjustment_deferred": "correction(s) reportée(s) (paie insuffisante)",
    }
)
PAYROLL_COLOURS = TokenColours(CALCULATED="warning", APPROVED="primary", PAID="success")


def calculation_text(summary):
    parts = [
        tr("{0} créée(s)", summary.get("created", 0)),
        tr("{0} recalculée(s)", summary.get("recalculated", 0)),
        tr("{0} inchangée(s)", summary.get("unchanged", 0)),
        tr("{0} déjà approuvée(s) ou payée(s), non modifiée(s)", summary.get("frozen", 0)),
    ]
    counts = {}
    for warning in summary.get("warnings") or []:
        counts[warning.get("code")] = counts.get(warning.get("code"), 0) + 1
    notes = [f"{n} {WARNINGS.get(code, code)}" for code, n in counts.items()]
    return (
        tr("Calcul terminé : ") + ", ".join(parts) + "." + (tr(" Attention : {0}.", ", ".join(notes)) if notes else "")
    )


# =============================================================================
# Periods
# =============================================================================


class PeriodsPage(CatalogPage):
    title = Tr("Périodes de paie")
    description = Tr(
        "Période → Calculer → Préparer → Vérifier → Approuver → Payer. "
        "Calculer prépare (ou met à jour) les paies de la période."
    )
    columns = Tr(["Nom", "Du", "Au", STATUS_COLUMN_TITLE])
    noun = "période"
    search_placeholder = Tr("Rechercher une période…")
    status_filters = Tr([("Toutes", None), ("Ouvertes", "OPEN"), ("Clôturées", "CLOSED")])
    has_toggle = False

    def __init__(self, payroll, references, runner, parent=None, *, show_payrolls=None, **kwargs):
        self.payroll, self.references = payroll, references
        self.show_payrolls = show_payrolls or (lambda period: None)
        super().__init__(runner, parent, **kwargs)
        self.edit_button.hide()
        self.add_button.setText(tr("Nouvelle période…"))
        self.calculate_button.clicked.connect(self.calculate)
        self.close_button.clicked.connect(self.close_period)
        self.payrolls_button.clicked.connect(self.open_row)

    def leading_actions(self):
        self.payrolls_button = button(tr("Voir les paies"), tooltip=tr("Paies de la période (Entrée)"))
        return [self.payrolls_button]

    def extra_actions(self):
        self.close_button = button(tr("Clôturer…"), "danger")
        self.calculate_button = button(tr("Calculer"), "primary")
        return [self.close_button, self.calculate_button]

    def update_extra_actions(self, row):
        if hasattr(self, "calculate_button"):
            self.payrolls_button.setEnabled(row is not None)
            for widget in (self.calculate_button, self.close_button):
                widget.setEnabled(row is not None and row.active)
                widget.setToolTip(tr("Sélectionnez une période ouverte.") if not (row and row.active) else "")

    def status_cell(self, row):
        return coloured(
            PERIOD_STATUSES.get(row.status, row.status), TOKENS.success if row.active else TOKENS.text_secondary
        )

    def fetch(self):
        rows = self.payroll.periods()
        wanted = self.status.currentData()
        if wanted:
            rows = [r for r in rows if r.status == wanted]
        search = self.search.text().strip().lower()
        return [r for r in rows if search in r.name.lower()] if search else rows

    def cells(self, row):
        return [
            row.name,
            (f"{row.start:%d/%m/%Y}" if row.start else "—", row.start.isoformat() if row.start else ""),
            (f"{row.end:%d/%m/%Y}" if row.end else "—", row.end.isoformat() if row.end else ""),
            "",
        ]

    def describe_row(self, row):
        return row.name

    def ask(self, kind, **context):
        if kind == "period":
            dialog = PeriodDialog(context["years"], self)
            return dialog.values() if dialog.exec() == QDialog.Accepted else None
        return self.confirm(
            self,
            tr("Clôturer « {0} » ?", context["period"].name),
            tr(
                "Une période clôturée ne peut plus être modifiée. Le serveur refusera tant qu'une paie n'est ni "
                "payée ni annulée."
            ),
            confirm_text=tr("Clôturer"),
            danger=True,
        )

    def add(self):
        def open_form(years):
            values = self.ask("period", years=years)
            if values:
                self.call(
                    lambda: self.payroll.create_period(**values),
                    lambda period: self._saved(period, tr("créée")),
                    action=tr("Impossible de créer la période"),
                )

        self.call(
            lambda: self.references.years(open_only=True), open_form, action=tr("Impossible de charger les années")
        )

    def calculate(self):
        row = self.selected()
        if row is None:
            return
        self.call(
            lambda: self.payroll.calculate(row.id),
            lambda summary: (self.banner.show_message("success", calculation_text(summary)), self.show_payrolls(row)),
            action=tr("Impossible de calculer la période"),
        )

    def close_period(self):
        row = self.selected()
        if row is not None and self.ask("close", period=row):
            self.call(
                lambda: self.payroll.close_period(row.id),
                lambda period: self._saved(period, tr("clôturée")),
                action=tr("Impossible de clôturer la période"),
            )

    def open_row(self):
        row = self.selected()
        if row is not None:
            self.show_payrolls(row)

    def edit(self):
        self.open_row()

    def _saved(self, saved, verb):
        self.success(tr("Période « {0} » {1}.", saved.name, verb))
        self.call(
            self.fetch,
            lambda rows: (self.show_rows(rows), self.select_id(saved.id)),
            action=tr("Impossible de charger"),
        )


# =============================================================================
# Payrolls
# =============================================================================


class PayrollsPage(CatalogPage):
    title = Tr("Paies")
    description = Tr(
        "Vérifier le détail, puis approuver et payer. Un paiement passe par la trésorerie, une seule fois."
    )
    columns = Tr(["Employé", "Type", "Période", "Programmé", "Acquis", "Corrections", "À payer", STATUS_COLUMN_TITLE])
    noun = "paie"
    search_placeholder = Tr("Rechercher un employé…")
    status_filters = Tr([("Statut : tous", None), *((label, code) for code, label in PAYROLL_STATUSES.items())])
    narrow_hidden = (1, 5)  # type, corrections: in the payroll's detail
    has_toggle = False

    def __init__(self, payroll, finance, runner, parent=None, **kwargs):
        self.payroll, self.finance = payroll, finance
        super().__init__(runner, parent, **kwargs)
        self.edit_button.hide()
        self.add_button.hide()
        self.detail_button.clicked.connect(self.open_row)
        self.approve_button.clicked.connect(lambda: self.run_action("approve"))
        self.pay_button.clicked.connect(lambda: self.run_action("pay"))
        self.cancel_button.clicked.connect(lambda: self.run_action("cancel"))

    def stretch_columns(self):
        return {0}

    def leading_actions(self):
        self.detail_button = button(tr("Vérifier"), tooltip=tr("Détail du calcul (Entrée)"))
        return [self.detail_button]

    def extra_actions(self):
        self.cancel_button = button(tr("Annuler…"), "danger")
        self.approve_button = button(tr("Approuver"))
        self.pay_button = button(tr("Payer…"), "primary")
        return [self.cancel_button, self.approve_button, self.pay_button]

    def add_filters(self, layout):
        self.period_filter = _combo(tr("Filtrer par période"), tr("Période : toutes"), 150)
        self.kind_filter = _combo(tr("Filtrer par type"), tr("Type : tous"), 120)
        for code, label in EMPLOYEE_KINDS.items():
            self.kind_filter.addItem(label, code)
        for combo in (self.period_filter, self.kind_filter):
            combo.currentIndexChanged.connect(lambda _: self.reload())
            layout.addWidget(combo)

    def update_extra_actions(self, row):
        if hasattr(self, "pay_button"):
            status = row.status if row else None
            self.detail_button.setEnabled(row is not None)
            self.approve_button.setEnabled(status == "CALCULATED")
            self.pay_button.setEnabled(status == "APPROVED")
            self.cancel_button.setEnabled(status in ("CALCULATED", "APPROVED"))
            self.approve_button.setToolTip(tr("Seule une paie préparée s'approuve.") if status != "CALCULATED" else "")
            self.pay_button.setToolTip(tr("Seule une paie approuvée se paie.") if status != "APPROVED" else "")

    def is_filtered(self):
        return super().is_filtered() or bool(self.period_filter.currentData() or self.kind_filter.currentData())

    def status_cell(self, row):
        return coloured(row.status_label, PAYROLL_COLOURS.get(row.status, TOKENS.text_secondary))

    def activate(self):
        self.call(self.payroll.periods, self._fill, action=tr("Impossible de charger les périodes"))

    def _fill(self, periods):
        _refill(self.period_filter, tr("Période : toutes"), [(p.name, p.id) for p in periods])
        self.reload()

    def show_period(self, period):
        if self.period_filter.findData(period.id) < 0:
            self.period_filter.addItem(period.name, period.id)
        self.period_filter.blockSignals(True)
        self.period_filter.setCurrentIndex(self.period_filter.findData(period.id))
        self.period_filter.blockSignals(False)

    def fetch(self):
        rows = self.payroll.payrolls(
            period_id=self.period_filter.currentData(),
            status=self.status.currentData(),
            kind=self.kind_filter.currentData(),
        )
        search = self.search.text().strip().lower()
        return [r for r in rows if search in r.employee_name.lower()] if search else rows

    def cells(self, row):
        dash = ("—", 0)
        return [
            row.employee_name,
            EMPLOYEE_KINDS.get(row.kind, row.kind),
            row.period_name,
            money_cell(row.programmed, row.currency) if row.programmed is not None else dash,
            money_cell(row.earned if row.kind == "TEACHER" else row.base_salary, row.currency),
            money_cell(row.adjustments, row.currency),
            money_cell(row.payable, row.currency),
            "",
        ]

    def describe_row(self, row):
        return row.code

    def ask(self, kind, **context):
        if kind == "detail":
            dialog = PayrollDetailDialog(context["payroll"], self)
            return dialog.action if dialog.exec() == QDialog.Accepted else None
        if kind == "pay":
            dialog = PayDialog(context["payroll"], context["wallets"], self)
            return dialog.values() if dialog.exec() == QDialog.Accepted else None
        if kind == "cancel":
            return ask_reason(
                self,
                tr("Annuler la paie de {0} ?", context["payroll"].employee_name),
                tr("Les lignes restent dans l'historique ; un nouveau calcul reste possible."),
                danger=True,
            )
        return self.confirm(
            self,
            tr("Approuver la paie de {0} ?", context["payroll"].employee_name),
            tr(
                "Montant à approuver : {0}. Le serveur vérifie d'abord que le calcul correspond toujours aux données.",
                format_money(context["payroll"].payable, context["payroll"].currency),
            ),
            confirm_text=tr("Approuver"),
        )

    def open_row(self):
        row = self.selected()
        if row is None:
            return

        def show(payroll):
            action = self.ask("detail", payroll=payroll)
            if action:
                self.run_action(action, payroll)

        self.call(lambda: self.payroll.payroll(row.id), show, action=tr("Impossible de charger la paie"))

    def edit(self):
        self.open_row()

    def run_action(self, name, payroll=None):
        row = payroll or self.selected()
        if row is None:
            return
        if name == "approve":
            if self.ask("approve", payroll=row):
                self.call(
                    lambda: self.payroll.approve(row.id),
                    lambda saved: self._done(
                        saved, tr("Paie approuvée : {0}.", format_money(saved.approved, saved.currency))
                    ),
                    action=tr("Impossible d'approuver la paie"),
                )
        elif name == "pay":

            def open_form(wallets):
                own = [w for w in wallets if w.active and w.owner_name == row.employee_name]
                values = self.ask("pay", payroll=row, wallets=own)
                if values:
                    self.call(
                        lambda: self.payroll.pay(row.id, **values),
                        lambda saved: self._done(
                            saved,
                            tr(
                                "Paie payée : {0} (référence {1}).",
                                format_money(saved.approved, saved.currency),
                                saved.payment_reference,
                            ),
                        ),
                        action=tr("Impossible de payer la paie"),
                    )

            self.call(self.finance.wallets, open_form, action=tr("Impossible de charger les wallets"))
        elif name == "cancel":
            values = self.ask("cancel", payroll=row)
            if values:
                self.call(
                    lambda: self.payroll.cancel(row.id, values["reason"]),
                    lambda saved: self._done(saved, tr("Paie annulée (historique conservé).")),
                    action=tr("Impossible d'annuler la paie"),
                )

    def _done(self, saved, message):
        self.success(f"{saved.employee_name} · {saved.period_name} — {message}")
        self.call(
            self.fetch,
            lambda rows: (self.show_rows(rows), self.select_id(saved.id)),
            action=tr("Impossible de charger"),
        )


# =============================================================================
# Corrections
# =============================================================================


class AdjustmentsPage(CatalogPage):
    title = Tr("Corrections")
    description = Tr("Primes (+) et retenues (−) : jamais modifiées, appliquées par la prochaine paie payée.")
    columns = Tr(["Employé", "Montant", "Motif", "Date d'effet", STATUS_COLUMN_TITLE])
    noun = "correction"
    search_placeholder = Tr("Rechercher par employé ou motif…")
    status_filters = Tr([("Toutes", None), ("En attente", True), ("Appliquées", False)])
    has_toggle = False

    def __init__(self, payroll, teachers, runner, parent=None, **kwargs):
        self.payroll, self.teachers = payroll, teachers
        self.names = {}
        super().__init__(runner, parent, **kwargs)
        self.edit_button.hide()
        self.add_button.setText(tr("Nouvelle correction…"))

    def stretch_columns(self):
        return {2}

    def status_cell(self, row):
        return coloured(
            tr("En attente") if row.active else tr("Appliquée"), TOKENS.warning if row.active else TOKENS.success
        )

    def _employees(self):
        names = {t.employee_id: f"{t.name} ({t.number})" for t in self.teachers.all(status=None) if t.employee_id}
        for p in self.payroll.payrolls():
            names.setdefault(p.employee_id, p.employee_name)
        return names

    def fetch(self):
        self.names = self._employees()
        rows = self.payroll.adjustments()
        wanted = self.status.currentData()
        if wanted is not None:
            rows = [r for r in rows if r.active == wanted]
        search = self.search.text().strip().lower()
        if search:
            rows = [r for r in rows if search in f"{self.names.get(r.employee_id, '')} {r.reason}".lower()]
        return rows

    def cells(self, row):
        return [
            self.names.get(row.employee_id, "?"),
            (format_money(row.amount), row.amount),
            row.reason,
            (
                f"{row.effective_date:%d/%m/%Y}" if row.effective_date else "—",
                row.effective_date.isoformat() if row.effective_date else "",
            ),
            "",
        ]

    def ask(self, employees):
        dialog = AdjustmentDialog(employees, self)
        return dialog.values() if dialog.exec() == QDialog.Accepted else None

    def add(self):
        def open_form(names):
            values = self.ask(sorted(((i, n) for i, n in names.items()), key=lambda pair: pair[1]))
            if values:
                self.call(
                    lambda: self.payroll.create_adjustment(**values),
                    lambda saved: (
                        self.success(tr("Correction de {0} enregistrée.", format_money(saved.amount))),
                        self.reload(),
                    ),
                    action=tr("Impossible d'enregistrer la correction"),
                )

        self.call(self._employees, open_form, action=tr("Impossible de charger les employés"))

    def open_row(self):
        pass


# =============================================================================
# The page
# =============================================================================


class PayrollPage(Page):
    title = Tr("Paie")

    def __init__(self, payroll, finance, references, teachers, runner, parent=None, **kwargs):
        super().__init__(runner, parent, **kwargs)
        self.layout_.setContentsMargins(0, 8, 0, 0)
        self.workflow = QLabel(tr(WORKFLOW), objectName="subtitle")
        self.workflow.setContentsMargins(28, 0, 28, 0)
        self.layout_.addWidget(self.workflow)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.periods = PeriodsPage(payroll, references, runner, show_payrolls=self.show_payrolls, **kwargs)
        self.payrolls = PayrollsPage(payroll, finance, runner, **kwargs)
        self.adjustments = AdjustmentsPage(payroll, teachers, runner, **kwargs)
        for page, label in (
            (self.periods, tr("Périodes")),
            (self.payrolls, tr("Paies")),
            (self.adjustments, tr("Corrections")),
        ):
            self.tabs.addTab(page, label)
            page.session_expired.connect(self.session_expired.emit)
        self.layout_.addWidget(self.tabs)
        self.tabs.currentChanged.connect(lambda _: self.tabs.currentWidget().activate())

    def activate(self):
        self.tabs.currentWidget().activate()

    def open_tab(self, name):
        page = getattr(self, name)
        self.tabs.setCurrentWidget(page)
        return page

    def show_payrolls(self, period):
        """From a period: the Paies tab, filtered on it."""
        self.payrolls.show_period(period)
        if self.tabs.currentWidget() is self.payrolls:
            self.payrolls.reload()
        else:
            self.tabs.setCurrentWidget(self.payrolls)
