"""Administration → Finance (ADR 0022): the admin face of the EXISTING finance
domain (ADR 0013). Tabs:

    Vue d'ensemble  treasury, collected, outstanding, failures; recent treasury movements
    Paiements       history (server pagination, search, status / mode / period filters),
                    detail, new payment (cash, or the admin's own simulated wallet), refund
    Factures        obligations: issue, collect, cancel (refused by the server once paid)
    Remboursements  inverse transactions with their original payment
    Wallets         simulated wallets of the school (identifiers masked)
    Motifs          fee types

Every financial decision is the server's: the outcome of a payment (succeeded,
declined, insufficient funds, timeout, provider error) is shown as returned.
Amounts are Decimal (from the API's strings), never floats.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
)

from ...api.errors import NetworkError
from ...i18n import Tr, tr
from ...models import INVOICE_STATUSES, LEDGER_TYPES, PAYMENT_METHODS, PAYMENT_STATUSES, SIMULATION_BEHAVIORS, Metric
from ...money import format_money, to_decimal
from ...services.finance import PERIODS
from ..dialogs.finance_dialogs import (
    FeeTypeDialog,
    InvoiceDetailDialog,
    InvoiceDialog,
    PaymentDetailDialog,
    PaymentDialog,
    RefundDialog,
)
from ..dialogs.teacher_dialogs import ask_reason
from ..theme import TOKENS, TokenColours
from ..widgets import Page, button
from .catalog_base import STATUS_COLUMN_TITLE, CatalogPage, PagedCatalogPage
from .dashboard_page import MetricCard
from .planning_page import _combo

PAYMENT_COLOURS = TokenColours(SUCCEEDED="success", PENDING="warning")


def coloured(text, colour, tooltip=""):
    item = QTableWidgetItem(text)
    item.setForeground(QBrush(QColor(colour)))
    if tooltip:
        item.setToolTip(tooltip)
    return item


def money_cell(value, currency):
    """Right-aligned amount, sorted by its Decimal value."""
    return (format_money(value, currency), value if value is not None else to_decimal("0"))


def _period_combo():
    combo = _combo(tr("Filtrer par période"), PERIODS[""], 150)
    for key, label in PERIODS.items():
        if key:
            combo.addItem(label, key)
    return combo


# =============================================================================
# Overview
# =============================================================================


class OverviewPage(Page):
    title = Tr("Vue d'ensemble")

    def __init__(self, finance, runner, parent=None, **kwargs):
        super().__init__(runner, parent, **kwargs)
        self.finance = finance
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(QLabel(tr("Vue financière"), objectName="pageTitle"))
        subtitle = QLabel(
            tr("Chiffres calculés par le serveur (montants exacts, jamais estimés)."), objectName="subtitle"
        )
        subtitle.setWordWrap(True)
        titles.addWidget(subtitle)
        head.addLayout(titles, 1)
        self.refresh_button = button(tr("Actualiser"), tooltip=tr("Recharger (F5)"))
        self.refresh_button.clicked.connect(self.reload)
        head.addWidget(self.refresh_button, 0, Qt.AlignTop)
        self.layout_.addLayout(head)
        self.layout_.addWidget(self.banner)
        self.grid = QGridLayout()
        self.grid.setSpacing(12)
        self.layout_.addLayout(self.grid)
        self.layout_.addWidget(QLabel(tr("Mouvements récents de la trésorerie"), objectName="sectionTitle"))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            [tr("Date"), tr("Opération"), tr("Référence"), tr("Montant"), tr("Solde après")]
        )
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for index in range(5):
            header.setSectionResizeMode(index, QHeaderView.Stretch if index == 2 else QHeaderView.ResizeToContents)
        self.layout_.addWidget(self.table, 1)
        self.cards = []
        self.metrics = []

    def set_busy(self, busy):
        super().set_busy(busy)
        self.refresh_button.setEnabled(not busy)

    def reload(self):
        self.call(
            lambda: (self.finance.dashboard(), self.finance.treasury()),
            self.show,
            action=tr("Impossible de charger la vue financière"),
        )

    def show(self, loaded):
        data, (balance, currency, entries) = loaded
        currency = data.get("currency") or currency
        failed = data.get("failed_payments", 0) or 0
        overdue = data.get("overdue_invoices", 0) or 0
        by_status = data.get("payments_by_status") or {}
        self.metrics = [
            Metric(tr("Trésorerie"), format_money(balance, currency), tr("solde de l'école")),
            Metric(
                tr("Encaissé net"), format_money(data.get("net_collected"), currency), tr("paiements − remboursements")
            ),
            Metric(
                tr("Reste à encaisser"),
                format_money(data.get("outstanding"), currency),
                tr("{0} facture(s) en retard", overdue) if overdue else tr("aucune facture en retard"),
            ),
            Metric(tr("Remboursé"), format_money(data.get("refunded"), currency), tr("transactions inverses")),
            Metric(
                tr("Paiements en attente / échoués"),
                f"{by_status.get('PENDING', 0)} / {failed}",
                tr("refusés, fonds insuffisants, délais, erreurs"),
            ),
        ]
        for card in self.cards:
            self.grid.removeWidget(card)
            card.deleteLater()
        self.cards = [MetricCard(m) for m in self.metrics]
        columns = 3 if self.width() < 1000 else 5
        for index, card in enumerate(self.cards):
            self.grid.addWidget(card, index // columns, index % columns)
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            sign = "+" if entry.direction == "CREDIT" else "−"
            cells = [
                f"{entry.at:%d/%m/%Y %H:%M}" if entry.at else "—",
                LEDGER_TYPES.get(entry.kind, entry.kind),
                entry.reference,
                f"{sign} {format_money(entry.amount, currency)}",
                format_money(entry.balance_after, currency),
            ]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column == 3:
                    item.setForeground(QBrush(QColor(TOKENS.success if sign == "+" else TOKENS.danger)))
                self.table.setItem(row, column, item)


# =============================================================================
# Payments (and the shared « collect a payment » flow)
# =============================================================================


class PaymentFlow:
    """New payment → server outcome shown as is; refund. Used by Paiements and Factures."""

    retry = None  # values of an attempt whose outcome is unknown (network): same key on retry

    def ask(self, kind, **context):
        if kind == "payment":
            dialog = PaymentDialog(
                context["fee_types"],
                context["wallets"],
                self.search_students,
                self.load_obligations,
                self,
                student=context.get("student"),
                invoice=context.get("invoice"),
                retry=context.get("retry"),
            )
        elif kind == "refund":
            dialog = RefundDialog(context["payment"], self)
        elif kind == "payment_detail":
            dialog = PaymentDetailDialog(context["payment"], self, can_refund=True)
            return dialog.action if dialog.exec() == QDialog.Accepted else None
        elif kind == "invoice":
            dialog = InvoiceDialog(context["fee_types"], self.search_students, self)
        elif kind == "invoice_detail":
            dialog = InvoiceDetailDialog(context["invoice"], self)
            return dialog.action if dialog.exec() == QDialog.Accepted else None
        elif kind == "cancel_invoice":
            return ask_reason(
                self,
                tr("Annuler la facture {0} ?", context["invoice"].number),
                tr("Possible seulement sans paiement."),
                danger=True,
            )
        else:
            raise ValueError(kind)
        return dialog.values() if dialog.exec() == QDialog.Accepted else None

    def search_students(self, text, done):
        self.call(lambda: self.finance.find_students(text), done, action=tr("Impossible de rechercher les élèves"))

    def load_obligations(self, student_id, done):
        self.call(lambda: self.finance.obligations(student_id), done, action=tr("Impossible de charger les factures"))

    def collect(self, student=None, invoice=None):
        retry = self.retry if student is None else None

        def open_form(lists):
            fee_types, wallets = lists
            values = self.ask(
                "payment", fee_types=fee_types, wallets=wallets, student=student, invoice=invoice, retry=retry
            )
            if values:
                self.send_payment(values)

        self.call(
            lambda: (self.finance.fee_types(), self.finance.my_wallets()),
            open_form,
            action=tr("Impossible de préparer le paiement"),
        )

    def send_payment(self, values):
        def attempt():
            try:
                return self.finance.initiate(**values)
            except NetworkError:
                self.retry = values  # outcome unknown: the retry reuses the key
                raise

        self.call(attempt, self.paid, action=tr("Paiement sans réponse du serveur"))

    def paid(self, payment):
        self.retry = None
        amount = format_money(payment.amount, payment.currency)
        if payment.replayed:
            self.banner.show_message(
                "info",
                tr("Ce paiement était déjà enregistré ({0}) : aucun nouveau débit.", payment.status_label),
                title=tr("Paiement {0}", payment.reference),
            )
        elif payment.status == "SUCCEEDED":
            self.success(tr("Paiement réussi — {0} · {1} · {2}.", payment.reference, amount, payment.student_name))
        else:
            detail = payment.failure_reason or tr("Aucun mouvement d'argent.")
            self.banner.show_message(
                "warning" if payment.failed else "info",
                tr("{0} · {1} — {2} Le paiement est enregistré avec ce résultat.", payment.reference, amount, detail),
                title=tr("Paiement {0}", payment.status_label.lower()),
            )
        self.after_payment(payment)

    def after_payment(self, payment):
        self.reload()

    def refund_payment(self, payment):
        values = self.ask("refund", payment=payment)
        if values:
            self.call(
                lambda: self.finance.refund(payment.id, **values),
                lambda refund: (
                    self.success(
                        tr(
                            "Remboursement de {0} enregistré (paiement {1}). L'historique est conservé.",
                            format_money(refund.amount, payment.currency),
                            payment.reference,
                        )
                    ),
                    self.reload(),
                ),
                action=tr("Impossible de rembourser le paiement"),
            )

    def show_payment(self, payment_id):
        def show(payment):
            if self.ask("payment_detail", payment=payment) == "refund":
                self.refund_payment(payment)

        self.call(lambda: self.finance.payment(payment_id), show, action=tr("Impossible de charger le paiement"))


class PaymentsPage(PaymentFlow, PagedCatalogPage):
    title = Tr("Paiements")
    description = Tr("Historique des paiements. Un échec est un résultat enregistré, jamais supprimé.")
    columns = Tr(["Référence", "Élève", "Montant", "Mode", "Date", STATUS_COLUMN_TITLE])
    noun = "paiement"
    feminine = False
    search_placeholder = Tr("Rechercher par référence, élève ou matricule…")
    status_filters = Tr([("Statut : tous", None), *((label, code) for code, label in PAYMENT_STATUSES.items())])
    has_toggle = False

    def __init__(self, finance, runner, parent=None, **kwargs):
        self.finance = finance
        super().__init__(runner, parent, **kwargs)
        self.edit_button.hide()
        self.add_button.setText(tr("Nouveau paiement…"))
        self.add_button.setToolTip(tr("Encaisser un paiement (Ctrl+N)"))
        self.detail_button.clicked.connect(self.open_row)
        self.refund_button.clicked.connect(lambda: self.selected() and self.refund_payment(self.selected()))

    def stretch_columns(self):
        return {1}

    def leading_actions(self):
        self.detail_button = button(tr("Détail"), tooltip=tr("Détail du paiement (Entrée)"))
        return [self.detail_button]

    def extra_actions(self):
        self.refund_button = button(tr("Rembourser…"), "danger")
        return [self.refund_button]

    def add_filters(self, layout):
        self.method_filter = _combo(tr("Filtrer par mode"), tr("Mode : tous"), 130)
        for code, label in PAYMENT_METHODS.items():
            self.method_filter.addItem(label, code)
        self.period_filter = _period_combo()
        for combo in (self.method_filter, self.period_filter):
            combo.currentIndexChanged.connect(lambda _: self.reload_first_page())
            layout.addWidget(combo)

    def update_extra_actions(self, row):
        if hasattr(self, "refund_button"):
            self.detail_button.setEnabled(row is not None)
            refundable = row is not None and row.refundable > 0
            self.refund_button.setEnabled(refundable)
            self.refund_button.setToolTip(
                tr("Sélectionnez un paiement réussi non entièrement remboursé.") if not refundable else ""
            )

    def is_filtered(self):
        return super().is_filtered() or bool(self.method_filter.currentData() or self.period_filter.currentData())

    def status_cell(self, row):
        colour = PAYMENT_COLOURS.get(row.status, TOKENS.danger if row.failed else TOKENS.text_secondary)
        return coloured(row.status_label, colour, row.failure_reason)

    def fetch(self):
        return self.finance.payments(
            page=self.page_number,
            search=self.search.text(),
            status=self.status.currentData(),
            method=self.method_filter.currentData(),
            period=self.period_filter.currentData() or "",
        )

    def cells(self, row):
        when = row.completed_at or row.initiated_at
        return [
            row.reference,
            row.student_name,
            money_cell(row.amount, row.currency),
            PAYMENT_METHODS.get(row.method, row.method),
            f"{when:%d/%m/%Y %H:%M}" if when else "—",
            "",
        ]

    def describe_row(self, row):
        return row.reference

    def open_row(self):
        row = self.selected()
        if row is not None:
            self.show_payment(row.id)

    def add(self):
        self.collect()

    def after_payment(self, payment):
        self.call(
            self.fetch,
            lambda result: (self.show_rows(result), self.select_id(payment.id)),
            action=tr("Impossible de charger les paiements"),
        )

    def edit(self):
        self.open_row()


# =============================================================================
# Invoices (obligations)
# =============================================================================


class InvoicesPage(PaymentFlow, PagedCatalogPage):
    title = Tr("Factures")
    description = Tr("Obligations des élèves. Une facture payée ne s'annule pas : on rembourse.")
    columns = Tr(["N°", "Élève", "Émise le", "Échéance", "Total", "Payé", "Reste", STATUS_COLUMN_TITLE])
    noun = "facture"
    search_placeholder = Tr("Rechercher par numéro, élève ou matricule…")
    status_filters = Tr([("Statut : tous", None), *((label, code) for code, label in INVOICE_STATUSES.items())])
    narrow_hidden = (2, 5)  # issue date, paid: in the invoice's detail
    has_toggle = False

    def __init__(self, finance, runner, parent=None, **kwargs):
        self.finance = finance
        super().__init__(runner, parent, **kwargs)
        self.edit_button.hide()
        self.add_button.setText(tr("Nouvelle facture…"))
        self.detail_button.clicked.connect(self.open_row)
        self.collect_button.clicked.connect(self.collect_selected)
        self.cancel_button.clicked.connect(self.cancel_invoice)

    def stretch_columns(self):
        return {1}

    def leading_actions(self):
        self.detail_button = button(tr("Détail"), tooltip=tr("Détail de la facture (Entrée)"))
        return [self.detail_button]

    def extra_actions(self):
        self.cancel_button = button(tr("Annuler…"), "danger")
        self.collect_button = button(tr("Encaisser…"))
        return [self.cancel_button, self.collect_button]

    def add_filters(self, layout):
        self.period_filter = _period_combo()
        self.period_filter.setToolTip(tr("Filtrer par date d'émission"))
        self.period_filter.currentIndexChanged.connect(lambda _: self.reload_first_page())
        layout.addWidget(self.period_filter)

    def update_extra_actions(self, row):
        if hasattr(self, "collect_button"):
            self.detail_button.setEnabled(row is not None)
            for widget in (self.collect_button, self.cancel_button):
                widget.setEnabled(row is not None and row.active)
                widget.setToolTip(
                    tr("Sélectionnez une facture émise ou partiellement payée.") if not (row and row.active) else ""
                )

    def is_filtered(self):
        return super().is_filtered() or bool(self.period_filter.currentData())

    def status_cell(self, row):
        colour = {"PAID": TOKENS.success, "ISSUED": TOKENS.warning, "PARTIALLY_PAID": TOKENS.warning}.get(
            row.status, TOKENS.text_secondary
        )
        late = row.overdue(self.finance.today())
        return coloured(row.status_label + (tr(" · en retard") if late else ""), TOKENS.danger if late else colour)

    def fetch(self):
        return self.finance.invoices(
            page=self.page_number,
            search=self.search.text(),
            status=self.status.currentData(),
            period=self.period_filter.currentData() or "",
        )

    def cells(self, row):
        return [
            row.number,
            row.student_name,
            (
                f"{row.issue_date:%d/%m/%Y}" if row.issue_date else "—",
                row.issue_date.isoformat() if row.issue_date else "",
            ),
            (f"{row.due_date:%d/%m/%Y}" if row.due_date else "—", row.due_date.isoformat() if row.due_date else ""),
            money_cell(row.total, row.currency),
            money_cell(row.paid, row.currency),
            money_cell(row.balance, row.currency),
            "",
        ]

    def open_row(self):
        row = self.selected()
        if row is None:
            return

        def show(invoice):
            if self.ask("invoice_detail", invoice=invoice) == "pay":
                self.collect((invoice.student_id, invoice.student_name), invoice.id)

        self.call(lambda: self.finance.invoice(row.id), show, action=tr("Impossible de charger la facture"))

    def edit(self):
        self.open_row()

    def collect_selected(self):
        row = self.selected()
        if row is not None and row.active:
            self.collect((row.student_id, row.student_name), row.id)

    def add(self):
        def open_form(fee_types):
            values = self.ask("invoice", fee_types=fee_types)
            if values:
                self.call(
                    lambda: self.finance.issue_invoice(**values),
                    lambda invoice: self._reselect(
                        invoice.id,
                        tr(
                            "Facture {0} émise : {1} pour {2}.",
                            invoice.number,
                            format_money(invoice.total, invoice.currency),
                            invoice.student_name,
                        ),
                    ),
                    action=tr("Impossible d'émettre la facture"),
                )

        self.call(self.finance.fee_types, open_form, action=tr("Impossible de charger les motifs de frais"))

    def cancel_invoice(self):
        row = self.selected()
        if row is None:
            return
        values = self.ask("cancel_invoice", invoice=row)
        if values:
            self.call(
                lambda: self.finance.cancel_invoice(row.id, values["reason"]),
                lambda invoice: self._reselect(invoice.id, tr("Facture {0} annulée.", invoice.number)),
                action=tr("Impossible d'annuler la facture"),
            )


# =============================================================================
# Refunds
# =============================================================================


class RefundsPage(PaymentFlow, PagedCatalogPage):
    title = Tr("Remboursements")
    description = Tr("Transactions inverses : le paiement d'origine reste dans l'historique.")
    columns = Tr(["Date", "Paiement d'origine", "Élève", "Remboursé", "Montant initial", "Motif"])
    narrow_hidden = (4,)  # original amount: in the payment's detail
    noun = "remboursement"
    feminine = False
    search_placeholder = Tr("Rechercher par paiement, élève ou motif…")
    status_filters = Tr([("Tous", None)])
    has_toggle = False

    def __init__(self, finance, runner, parent=None, **kwargs):
        self.finance = finance
        super().__init__(runner, parent, **kwargs)
        self.status.hide()
        self.edit_button.hide()
        self.add_button.hide()
        self.origin_button.clicked.connect(self.open_row)

    def stretch_columns(self):
        return {2, 5}

    def leading_actions(self):
        self.origin_button = button(tr("Paiement d'origine"), tooltip=tr("Détail du paiement remboursé (Entrée)"))
        return [self.origin_button]

    def add_filters(self, layout):
        self.period_filter = _period_combo()
        self.period_filter.currentIndexChanged.connect(lambda _: self.reload_first_page())
        layout.addWidget(self.period_filter)

    def update_extra_actions(self, row):
        if hasattr(self, "origin_button"):
            self.origin_button.setEnabled(row is not None)

    def is_filtered(self):
        return bool(self.search.text().strip() or self.period_filter.currentData())

    def fetch(self):
        return self.finance.refunds(
            page=self.page_number, search=self.search.text(), period=self.period_filter.currentData() or ""
        )

    def cells(self, row):
        return [
            (
                f"{row.completed_at:%d/%m/%Y %H:%M}" if row.completed_at else "—",
                row.completed_at.isoformat() if row.completed_at else "",
            ),
            row.payment_reference,
            row.student_name,
            money_cell(row.amount, row.currency),
            money_cell(row.payment_amount, row.currency),
            row.reason,
        ]

    def open_row(self):
        row = self.selected()
        if row is not None:
            self.show_payment(row.payment_id)

    def edit(self):
        self.open_row()


# =============================================================================
# Wallets, fee types
# =============================================================================


class WalletsPage(CatalogPage):
    title = Tr("Wallets")
    description = Tr("Portefeuilles simulés de l'école (lecture seule). Les identifiants sont masqués.")
    columns = Tr(["Propriétaire", "Fournisseur", "Identifiant", "Solde", "Simulation", STATUS_COLUMN_TITLE])
    noun = "wallet"
    feminine = False
    search_placeholder = Tr("Rechercher par propriétaire ou fournisseur…")
    has_toggle = False

    def __init__(self, finance, runner, parent=None, **kwargs):
        self.finance = finance
        super().__init__(runner, parent, **kwargs)
        self.edit_button.hide()
        self.add_button.hide()

    def stretch_columns(self):
        return {0}

    def status_cell(self, row):
        return coloured(
            tr("●  Actif") if row.active else tr("○  Bloqué"), TOKENS.success if row.active else TOKENS.danger
        )

    def fetch(self):
        rows = self.finance.wallets()
        wanted = self.status.currentData()
        if wanted is not None:
            rows = [r for r in rows if r.active == wanted]
        search = self.search.text().strip().lower()
        return [r for r in rows if search in f"{r.owner_name} {r.provider}".lower()] if search else rows

    def cells(self, row):
        return [
            row.owner_name or "—",
            row.provider,
            row.masked,
            money_cell(row.balance, row.currency),
            SIMULATION_BEHAVIORS.get(row.behavior, row.behavior),
            "",
        ]

    def open_row(self):
        pass


class FeeTypesPage(CatalogPage):
    title = Tr("Motifs de frais")
    description = Tr("Scolarité, inscription, cantine… utilisés par les factures et les paiements sans facture.")
    columns = Tr(["Code", "Nom", "Description", STATUS_COLUMN_TITLE])
    noun = "motif"
    feminine = False
    has_toggle = False

    def __init__(self, finance, runner, parent=None, **kwargs):
        self.finance = finance
        super().__init__(runner, parent, **kwargs)
        self.edit_button.hide()

    def stretch_columns(self):
        return {1, 2}

    def fetch(self):
        rows = self.finance.fee_types()
        wanted = self.status.currentData()
        if wanted is not None:
            rows = [r for r in rows if r.active == wanted]
        search = self.search.text().strip().lower()
        return [r for r in rows if search in f"{r.code} {r.name}".lower()] if search else rows

    def cells(self, row):
        return [row.code, row.name, row.description, ""]

    def ask(self):
        dialog = FeeTypeDialog(self)
        return dialog.values() if dialog.exec() == QDialog.Accepted else None

    def add(self):
        values = self.ask()
        if values:
            self.call(
                lambda: self.finance.create_fee_type(**values),
                lambda fee: self._saved(fee, tr("créé")),
                action=tr("Impossible de créer le motif"),
            )

    def open_row(self):
        pass


# =============================================================================
# The page
# =============================================================================


class FinancePage(Page):
    title = Tr("Finance")

    def __init__(self, finance, runner, parent=None, **kwargs):
        super().__init__(runner, parent, **kwargs)
        self.layout_.setContentsMargins(0, 8, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.overview = OverviewPage(finance, runner, **kwargs)
        self.payments = PaymentsPage(finance, runner, **kwargs)
        self.invoices = InvoicesPage(finance, runner, **kwargs)
        self.refunds = RefundsPage(finance, runner, **kwargs)
        self.wallets = WalletsPage(finance, runner, **kwargs)
        self.fee_types = FeeTypesPage(finance, runner, **kwargs)
        for page, label in (
            (self.overview, tr("Vue d'ensemble")),
            (self.payments, tr("Paiements")),
            (self.invoices, tr("Factures")),
            (self.refunds, tr("Remboursements")),
            (self.wallets, tr("Wallets")),
            (self.fee_types, tr("Motifs")),
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
