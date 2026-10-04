"""Finance dialogs (ADR 0022). Forms collect what the API needs; every
financial decision (may this person pay, outcome of the provider, amounts
that can still be paid or refunded) is the server's. Amounts are typed as
text and read as Decimal — never float."""

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QWidget,
)

from ...models import INVOICE_STATUSES, PAYMENT_METHODS
from ...money import ZERO, format_money, parse_amount
from ...services.finance import new_idempotency_key
from ..widgets import FormDialog, button, date_field
from .teacher_dialogs import _grid


def _when(moment):
    return f"{moment:%d/%m/%Y %H:%M}" if moment else "—"


def _amount_field(placeholder="ex. 15000"):
    field = QLineEdit(placeholderText=placeholder)
    field.setAlignment(Qt.AlignRight)
    return field


class StudentPicker(QWidget):
    """Search box + results: the server searches (students/?search=)."""

    def __init__(self, search, parent=None):
        super().__init__(parent)
        self.search = search
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.text = QLineEdit(placeholderText="Nom, prénom ou matricule")
        self.find_button = button("Rechercher")
        self.results = QComboBox()
        self.results.setMinimumWidth(220)
        self.results.addItem("— lancez une recherche —", None)
        row.addWidget(self.text, 1)
        row.addWidget(self.find_button)
        row.addWidget(self.results, 2)
        self.find_button.clicked.connect(self.run)
        self.text.returnPressed.connect(self.run)

    def run(self):
        if self.text.text().strip():
            self.search(self.text.text(), self.show)

    def show(self, rows):
        self.results.clear()
        if not rows:
            self.results.addItem("Aucun élève trouvé", None)
        for student_id, label in rows:
            self.results.addItem(label, student_id)

    def set_fixed(self, student_id, label):
        self.results.clear()
        self.results.addItem(label, student_id)
        for widget in (self.text, self.find_button, self.results):
            widget.setEnabled(False)

    @property
    def student_id(self):
        return self.results.currentData()


class PaymentDialog(FormDialog):
    """Record a payment: cash at the desk, or with one of the logged-in
    administrator's own (simulated) wallets. One idempotency key per intent:
    `retry` reuses the key of an attempt whose outcome is unknown (network),
    so the server replays instead of charging twice."""

    def __init__(
        self,
        fee_types,
        wallets,
        search,
        load_obligations,
        parent=None,
        *,
        student=None,
        invoice=None,
        retry=None,
    ):
        super().__init__(
            "Nouveau paiement",
            "Le serveur décide de l'issue (réussi, refusé, fonds insuffisants, délai dépassé, erreur fournisseur) "
            "et l'enregistre dans tous les cas.",
            parent,
            save_text="Envoyer le paiement",
            width=640,
        )
        self.load_obligations = load_obligations
        self.key = (retry or {}).get("idempotency_key") or new_idempotency_key()
        self.invoices = []
        self.picker = self.add_field("student", "Élève", StudentPicker(search), required=True)
        self.add_section("Objet du paiement")
        self.invoice_list = QListWidget()
        self.invoice_list.setMaximumHeight(120)
        self.invoice_list.setAccessibleName("Factures ouvertes")
        self.invoice_list = self.add_field(
            "invoices", "Factures ouvertes", self.invoice_list, help_text="Cochez les factures réglées par ce paiement."
        )
        self.fee_type = QComboBox()
        self.fee_type.addItem("— aucun (factures cochées) —", None)
        for fee in fee_types:
            if fee.active:
                self.fee_type.addItem(f"{fee.code} — {fee.name}", fee.id)
        self.fee_type = self.add_field(
            "fee_type", "Motif sans facture", self.fee_type, help_text="Seulement si aucune facture n'est cochée."
        )
        self.add_section("Règlement")
        self.amount = self.add_field("amount", "Montant", _amount_field(), required=True, width="short")
        self.method = QComboBox()
        for code, label in PAYMENT_METHODS.items():
            self.method.addItem(label, code)
        self.method = self.add_field("method", "Mode", self.method, required=True, width="medium", beside=True)
        self.wallet = QComboBox()
        for wallet in wallets:
            self.wallet.addItem(f"{wallet.code} — solde {format_money(wallet.balance, wallet.currency)}", wallet.id)
        self.wallet = self.add_field(
            "wallet",
            "Portefeuille",
            self.wallet,
            help_text="Vos propres portefeuilles uniquement (règle du serveur)."
            if wallets
            else "Vous n'avez aucun portefeuille : paiement en espèces uniquement.",
        )
        if not wallets:
            self.method.model().item(self.method.findData("WALLET")).setEnabled(False)
        self.retry_note = QLabel("", objectName="help")
        self.retry_note.setWordWrap(True)
        self.body.addWidget(self.retry_note)
        self.picker.results.currentIndexChanged.connect(lambda _: self._student_changed())
        self.invoice_list.itemChanged.connect(lambda _: self._invoices_changed())
        for signal in (self.amount.textChanged, self.method.currentIndexChanged, self.wallet.currentIndexChanged):
            signal.connect(lambda *_: self.refresh_state())
        self.method.currentIndexChanged.connect(lambda _: self._method_changed())
        if student is not None:
            self.picker.set_fixed(*student)
            self._student_changed(preselect=invoice)
        if retry:
            self._restore(retry)
        self._method_changed()
        self.finish()

    # --- loading --------------------------------------------------------------------
    def _student_changed(self, preselect=None):
        self.invoice_list.clear()
        self.invoices = []
        if self.picker.student_id:
            self.load_obligations(self.picker.student_id, lambda rows: self.show_invoices(rows, preselect))
        self.refresh_state()

    def show_invoices(self, invoices, preselect=None):
        self.invoices = invoices
        self.invoice_list.blockSignals(True)
        self.invoice_list.clear()
        for invoice in invoices:
            due = f"{invoice.due_date:%d/%m/%Y}" if invoice.due_date else "—"
            item = QListWidgetItem(
                f"{invoice.number} · échéance {due} · reste {format_money(invoice.balance, invoice.currency)}"
            )
            item.setData(Qt.UserRole, invoice.id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if invoice.id == preselect else Qt.Unchecked)
            self.invoice_list.addItem(item)
        if not invoices:
            self.invoice_list.addItem(QListWidgetItem("Aucune facture ouverte pour cet élève."))
        self.invoice_list.blockSignals(False)
        self._invoices_changed()

    def _invoices_changed(self):
        """Suggest the selected balances as the amount (the user may change it)."""
        chosen = [i for i in self.invoices if i.id in self.invoice_ids]
        if chosen:
            self.amount.setText(str(sum((i.balance for i in chosen), ZERO)))
        self.fee_type.setEnabled(not chosen)
        self.refresh_state()

    def _method_changed(self):
        self.wallet.setEnabled(self.method.currentData() == "WALLET")
        self.refresh_state()

    def _restore(self, values):
        self.amount.setText(values.get("amount", ""))
        self.method.setCurrentIndex(max(0, self.method.findData(values.get("method"))))
        self.retry_note.setText(
            "Nouvelle tentative du même paiement : le serveur rejouera le premier envoi s'il avait abouti "
            "(aucun double débit)."
        )

    # --- state ----------------------------------------------------------------------
    @property
    def invoice_ids(self):
        ids = []
        for index in range(self.invoice_list.count()):
            item = self.invoice_list.item(index)
            if item.data(Qt.UserRole) and item.checkState() == Qt.Checked:
                ids.append(item.data(Qt.UserRole))
        return ids

    def missing_fields(self):
        missing = []
        if not self.picker.student_id:
            missing.append("Élève")
        if parse_amount(self.amount.text()) is None:
            missing.append("Montant")
        if self.method.currentData() == "WALLET" and not self.wallet.currentData():
            missing.append("Portefeuille")
        return missing

    def values(self):
        return {
            "student_id": self.picker.student_id,
            "amount": self.amount.text().strip(),
            "method": self.method.currentData(),
            "idempotency_key": self.key,
            "invoice_ids": self.invoice_ids,
            "fee_type_id": None if self.invoice_ids else self.fee_type.currentData(),
            "wallet_id": self.wallet.currentData() if self.method.currentData() == "WALLET" else None,
        }


class RefundDialog(FormDialog):
    """Refund (part of) a payment: an inverse transaction — nothing is deleted."""

    def __init__(self, payment, parent=None):
        super().__init__(
            f"Rembourser le paiement {payment.reference}",
            "Le remboursement est une transaction inverse : le paiement d'origine et son historique sont conservés.",
            parent,
            save_text="Rembourser",
            width=560,
        )
        self.body.addWidget(
            _grid(
                [
                    ("Paiement d'origine", payment.reference),
                    ("Élève", payment.student_name),
                    ("Montant payé", format_money(payment.amount, payment.currency)),
                    ("Déjà remboursé", format_money(payment.refunded, payment.currency)),
                    ("Mode", PAYMENT_METHODS.get(payment.method, payment.method)),
                    ("Date", _when(payment.completed_at or payment.initiated_at)),
                ]
            )
        )
        self.amount = self.add_field("amount", "Montant à rembourser", _amount_field(), required=True, width="short")
        self.amount.setText(str(payment.refundable))
        reason = QPlainTextEdit(placeholderText="Motif (obligatoire)")
        reason.setFixedHeight(72)
        reason.setTabChangesFocus(True)
        self.reason = self.add_field("reason", "Motif", reason, required=True)
        self.amount.textChanged.connect(self.refresh_state)
        self.reason.textChanged.connect(self.refresh_state)
        self.finish()
        self.reason.setFocus()

    def missing_fields(self):
        missing = [] if parse_amount(self.amount.text()) is not None else ["Montant"]
        return missing + ([] if self.reason.toPlainText().strip() else ["Motif"])

    def values(self):
        return {"amount": self.amount.text().strip(), "reason": self.reason.toPlainText().strip()}


class InvoiceDialog(FormDialog):
    """Issue an invoice (obligation) of one line for a student."""

    def __init__(self, fee_types, search, parent=None):
        super().__init__("Nouvelle facture", "Une obligation de paiement pour un élève.", parent, width=600)
        self.picker = self.add_field("student", "Élève", StudentPicker(search), required=True)
        self.fee_type = QComboBox()
        self.fee_type.addItem("— choisir —", None)
        for fee in fee_types:
            if fee.active:
                self.fee_type.addItem(f"{fee.code} — {fee.name}", fee.id)
        self.fee_type = self.add_field("fee_type", "Motif", self.fee_type, required=True, width="medium")
        self.description = self.add_field(
            "description", "Libellé", QLineEdit(placeholderText="ex. Scolarité 1er trimestre"), width="medium"
        )
        self.amount = self.add_field("amount", "Montant", _amount_field(), required=True, width="short")
        self.due_date = self.add_field("due_date", "Échéance", date_field(), required=True, width="short", beside=True)
        self.due_date.setDate(QDate.currentDate().addDays(30))
        self.picker.results.currentIndexChanged.connect(lambda _: self.refresh_state())
        self.fee_type.currentIndexChanged.connect(lambda _: self.refresh_state())
        self.amount.textChanged.connect(self.refresh_state)
        self.finish()

    def missing_fields(self):
        missing = [] if self.picker.student_id else ["Élève"]
        missing += [] if self.fee_type.currentData() else ["Motif"]
        return missing + ([] if parse_amount(self.amount.text()) is not None else ["Montant"])

    def values(self):
        return {
            "student_id": self.picker.student_id,
            "fee_type_id": self.fee_type.currentData(),
            "description": self.description.text().strip(),
            "amount": self.amount.text().strip(),
            "due_date": self.due_date.date().toPython(),
        }


class FeeTypeDialog(FormDialog):
    def __init__(self, parent=None):
        super().__init__("Nouveau motif de frais", "Scolarité, inscription, cantine, transport…", parent, width=520)
        self.code = self.add_field("code", "Code", QLineEdit(placeholderText="ex. SCOL"), required=True, width="short")
        self.name = self.add_field("name", "Nom", QLineEdit(), required=True, width="medium", beside=True)
        self.description = self.add_field("description", "Description", QLineEdit())
        for field in (self.code, self.name):
            field.textChanged.connect(self.refresh_state)
        self.finish()

    def missing_fields(self):
        return [label for label, field in (("Code", self.code), ("Nom", self.name)) if not field.text().strip()]

    def values(self):
        return {
            "code": self.code.text().strip(),
            "name": self.name.text().strip(),
            "description": self.description.text(),
        }


class PaymentDetailDialog(FormDialog):
    """Read-only detail of a payment; « Rembourser… » closes it with action = "refund"."""

    def __init__(self, payment, parent=None, *, can_refund=False):
        super().__init__(f"Paiement {payment.reference}", "", parent, save_text="Fermer", width=620)
        self.action = None
        self.cancel_button.hide()
        rows = [
            ("Statut", payment.status_label),
            ("Élève", payment.student_name),
            ("Montant", format_money(payment.amount, payment.currency)),
            ("Remboursé", format_money(payment.refunded, payment.currency)),
            ("Mode", PAYMENT_METHODS.get(payment.method, payment.method)),
            ("Fournisseur", payment.provider or "—"),
            ("Initié le", _when(payment.initiated_at)),
            ("Terminé le", _when(payment.completed_at)),
        ]
        if payment.failure_reason:
            rows.append(("Motif de l'échec", payment.failure_reason))
        if payment.provider_reference:
            rows.append(("Référence fournisseur", payment.provider_reference))
        self.body.addWidget(_grid(rows))
        self.add_section("Imputations")
        self.body.addWidget(
            _grid(
                [
                    (number or "—", ("Remboursement " if refund else "") + format_money(amount, payment.currency))
                    for number, amount, refund in payment.allocations
                ]
            )
            if payment.allocations
            else QLabel("Aucune facture (paiement sur motif) ou paiement échoué.", objectName="help")
        )
        self.add_section("Remboursements", "Transactions inverses : rien n'est supprimé.")
        self.body.addWidget(
            _grid(
                [
                    (_when(r.completed_at), f"{format_money(r.amount, payment.currency)} — {r.reason}")
                    for r in payment.refunds
                ]
            )
            if payment.refunds
            else QLabel("Aucun remboursement.", objectName="help")
        )
        if can_refund and payment.refundable > 0:
            refund = button("Rembourser…", "danger")
            refund.clicked.connect(lambda: self._start("refund"))
            self.body.addWidget(refund, 0, Qt.AlignLeft)
        self.finish(required_note=False)

    def _start(self, action):
        self.action = action
        self.accept()


class InvoiceDetailDialog(FormDialog):
    def __init__(self, invoice, parent=None):
        super().__init__(f"Facture {invoice.number}", "", parent, save_text="Fermer", width=580)
        self.action = None
        self.cancel_button.hide()
        rows = [
            ("Statut", INVOICE_STATUSES.get(invoice.status, invoice.status)),
            ("Élève", invoice.student_name),
            ("Émise le", f"{invoice.issue_date:%d/%m/%Y}" if invoice.issue_date else "—"),
            ("Échéance", f"{invoice.due_date:%d/%m/%Y}" if invoice.due_date else "—"),
            ("Total", format_money(invoice.total, invoice.currency)),
            ("Payé", format_money(invoice.paid, invoice.currency)),
            ("Reste à payer", format_money(invoice.balance, invoice.currency)),
        ]
        if invoice.cancelled_reason:
            rows.append(("Motif d'annulation", invoice.cancelled_reason))
        self.body.addWidget(_grid(rows))
        self.add_section("Lignes")
        self.body.addWidget(_grid([(label, format_money(total, invoice.currency)) for label, total in invoice.lines]))
        if invoice.active:
            collect = button("Encaisser…", "primary")
            collect.clicked.connect(lambda: self._start("pay"))
            self.body.addWidget(collect, 0, Qt.AlignLeft)
        self.finish(required_note=False)

    def _start(self, action):
        self.action = action
        self.accept()
