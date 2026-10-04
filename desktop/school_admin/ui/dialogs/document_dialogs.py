"""Documents dialogs (ADR 0023): choose the SOURCE of a document; the server
builds the PDF (school branding only), decides its status and traces it."""

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QRadioButton, QWidget

from ...models import DOCUMENT_KINDS, DOCUMENT_STATUSES, PAYROLL_STATUSES
from ...money import format_money
from ..widgets import FormDialog, button, date_field
from .finance_dialogs import StudentPicker
from .teacher_dialogs import _grid


def _when(moment):
    return f"{moment:%d/%m/%Y %H:%M}" if moment else "—"


class GenerateDocumentDialog(FormDialog):
    """Fields depend on the kind:

    REPORT_CARD         pupil -> one of their report cards
    STUDENT_CARD        pupil
    TIMETABLE           class OR teacher + a day of the week
    PAYMENT_RECEIPT     payment (search by reference / pupil)
    PAYSLIP             payroll (approved or paid)
    STUDENT_ATTENDANCE  pupil + from / to
    CLASS_ATTENDANCE    class + day
    """

    def __init__(self, kind, context, parent=None):
        super().__init__(
            f"Générer — {DOCUMENT_KINDS[kind]}",
            "Le serveur produit le PDF aux couleurs de l'établissement. Un document déjà à jour est réutilisé.",
            parent,
            save_text="Générer",
            width=600,
        )
        self.kind, self.context = kind, context
        self.picker = self.card = self.school_class = self.teacher = self.payment = self.payroll = None
        self.day = self.date_from = self.date_to = None
        if kind in ("REPORT_CARD", "STUDENT_CARD", "STUDENT_ATTENDANCE"):
            self.picker = self.add_field("student", "Élève", StudentPicker(context["search_students"]), required=True)
            self.picker.results.currentIndexChanged.connect(lambda _: self._student_changed())
        if kind == "REPORT_CARD":
            self.card = self.add_field("report_card", "Bulletin", QComboBox(), required=True, width="medium")
            self.card.currentIndexChanged.connect(lambda _: self.refresh_state())
        if kind in ("TIMETABLE", "CLASS_ATTENDANCE"):
            if kind == "TIMETABLE":
                holder = QWidget()
                row = QHBoxLayout(holder)
                row.setContentsMargins(0, 0, 0, 0)
                self.by_class, self.by_teacher = QRadioButton("D'une classe"), QRadioButton("D'un enseignant")
                self.by_class.setChecked(True)
                row.addWidget(self.by_class)
                row.addWidget(self.by_teacher)
                row.addStretch()
                self.add_field("source", "Emploi du temps", holder)
            self.school_class = QComboBox()
            self.school_class.addItem("— choisir —", None)
            for school_class in context["classes"]:
                self.school_class.addItem(school_class.name, school_class.id)
            self.school_class = self.add_field("class", "Classe", self.school_class, required=True, width="medium")
            self.school_class.currentIndexChanged.connect(lambda _: self.refresh_state())
            if kind == "TIMETABLE":
                self.teacher = QComboBox()
                self.teacher.addItem("— choisir —", None)
                for teacher in context["teachers"]:
                    self.teacher.addItem(f"{teacher.name} ({teacher.number})", teacher.id)
                self.teacher = self.add_field("teacher", "Enseignant", self.teacher, width="medium")
                self.teacher.currentIndexChanged.connect(lambda _: self.refresh_state())
                self.by_class.toggled.connect(lambda _: self._source_changed())
                self._source_changed()
            label = "Semaine du" if kind == "TIMETABLE" else "Jour"
            self.day = self.add_field("date", label, date_field(), required=True, width="short")
            self.day.setDate(QDate.currentDate())
        if kind == "STUDENT_ATTENDANCE":
            today = QDate.currentDate()
            self.date_from = self.add_field("date_from", "Du", date_field(), required=True, width="short")
            self.date_to = self.add_field("date_to", "Au", date_field(), required=True, width="short", beside=True)
            self.date_from.setDate(today.addDays(-30))
            self.date_to.setDate(today)
        if kind == "PAYMENT_RECEIPT":
            search = QWidget()
            row = QHBoxLayout(search)
            row.setContentsMargins(0, 0, 0, 0)
            self.payment_text = QLineEdit(placeholderText="Référence, élève ou matricule")
            find = button("Rechercher")
            self.payment = QComboBox()
            self.payment.addItem("— lancez une recherche —", None)
            row.addWidget(self.payment_text, 1)
            row.addWidget(find)
            self.add_field("search", "Paiement", search)
            self.payment = self.add_field("payment", "Paiement réussi", self.payment, required=True)
            find.clicked.connect(self._find_payments)
            self.payment_text.returnPressed.connect(self._find_payments)
            self.payment.currentIndexChanged.connect(lambda _: self.refresh_state())
        if kind == "PAYSLIP":
            self.payroll = QComboBox()
            self.payroll.addItem("— choisir —", None)
            for payroll in context["payrolls"]:
                self.payroll.addItem(
                    f"{payroll.employee_name} · {payroll.period_name} · "
                    f"{PAYROLL_STATUSES.get(payroll.status, payroll.status)} · "
                    f"{format_money(payroll.approved or payroll.payable, payroll.currency)}",
                    payroll.id,
                )
            self.payroll = self.add_field("payroll", "Paie", self.payroll, required=True)
            self.payroll.currentIndexChanged.connect(lambda _: self.refresh_state())
        self.finish()

    # --- loading ---
    def _student_changed(self):
        if self.card is not None:
            self.card.clear()
            student = self.picker.student_id
            if student:
                self.context["load_cards"](student, self.show_cards)
        self.refresh_state()

    def show_cards(self, cards):
        self.card.clear()
        for card in cards:
            self.card.addItem(f"{card.get('period_name', '')} — {card.get('status', '')}", card["id"])
        if not cards:
            self.card.addItem("Aucun bulletin calculé pour cet élève", None)
        self.refresh_state()

    def _find_payments(self):
        text = self.payment_text.text().strip()
        if text:
            self.context["find_payments"](text, self.show_payments)

    def show_payments(self, payments):
        self.payment.clear()
        for payment in payments:
            self.payment.addItem(
                f"{payment.reference} · {payment.student_name} · {format_money(payment.amount, payment.currency)}",
                payment.id,
            )
        if not payments:
            self.payment.addItem("Aucun paiement réussi trouvé", None)
        self.refresh_state()

    def _source_changed(self):
        by_class = self.by_class.isChecked()
        self.school_class.setEnabled(by_class)
        self.teacher.setEnabled(not by_class)
        self.refresh_state()

    # --- state ---
    def missing_fields(self):
        missing = []
        if self.picker is not None and not self.picker.student_id:
            missing.append("Élève")
        if self.card is not None and not self.card.currentData():
            missing.append("Bulletin")
        if self.kind == "TIMETABLE":
            if self.by_class.isChecked() and not self.school_class.currentData():
                missing.append("Classe")
            if self.by_teacher.isChecked() and not self.teacher.currentData():
                missing.append("Enseignant")
        elif self.school_class is not None and not self.school_class.currentData():
            missing.append("Classe")
        if self.payment is not None and not self.payment.currentData():
            missing.append("Paiement")
        if self.payroll is not None and not self.payroll.currentData():
            missing.append("Paie")
        return missing

    def values(self):
        values = {}
        if self.picker is not None:
            values["student"] = self.picker.student_id
        if self.card is not None:
            values = {"report_card": self.card.currentData()}
        if self.kind == "TIMETABLE":
            key = "school_class" if self.by_class.isChecked() else "teacher"
            values[key] = (self.school_class if key == "school_class" else self.teacher).currentData()
        elif self.school_class is not None:
            values["school_class"] = self.school_class.currentData()
        if self.day is not None:
            values["date"] = self.day.date().toPython()
        if self.date_from is not None:
            values["date_from"], values["date_to"] = self.date_from.date().toPython(), self.date_to.date().toPython()
        if self.payment is not None:
            values["payment"] = self.payment.currentData()
        if self.payroll is not None:
            values["payroll"] = self.payroll.currentData()
        return values


class ComputeReportCardsDialog(FormDialog):
    """Gradebook API: (re)compute the DRAFT report cards of a class for a period."""

    def __init__(self, classes, periods, parent=None):
        super().__init__(
            "Calculer les bulletins",
            "Le serveur calcule les moyennes et les rangs (bulletins provisoires ; un bulletin validé est figé).",
            parent,
            save_text="Calculer",
            width=520,
        )
        self.school_class = QComboBox()
        self.school_class.addItem("— choisir —", None)
        for school_class in classes:
            self.school_class.addItem(school_class.name, school_class.id)
        self.school_class = self.add_field("class", "Classe", self.school_class, required=True, width="medium")
        self.period = QComboBox()
        self.period.addItem("— choisir —", None)
        for period in periods:
            self.period.addItem(period.get("name", ""), period["id"])
        self.period = self.add_field("period", "Période", self.period, required=True, width="medium")
        for combo in (self.school_class, self.period):
            combo.currentIndexChanged.connect(lambda _: self.refresh_state())
        self.finish()

    def missing_fields(self):
        missing = [] if self.school_class.currentData() else ["Classe"]
        return missing + ([] if self.period.currentData() else ["Période"])

    def values(self):
        return {"class_id": self.school_class.currentData(), "period_id": self.period.currentData()}


class DocumentDetailDialog(FormDialog):
    """Read-only metadata; buttons close it with `action` = download / regenerate."""

    def __init__(self, document, parent=None):
        super().__init__(document.title, document.kind_label, parent, save_text="Fermer", width=600)
        self.cancel_button.hide()
        self.action = None
        self.body.addWidget(
            _grid(
                [
                    ("Statut", DOCUMENT_STATUSES.get(document.status, document.status)),
                    ("Version", str(document.version)),
                    ("Généré le", _when(document.generated_at)),
                    ("Fichier", f"{document.file_name} ({max(1, document.size_bytes // 1024)} Ko)"),
                    ("Code de vérification", document.verification_code or "—"),
                    ("Empreinte SHA-256", f"{document.sha256[:16]}…" if document.sha256 else "—"),
                ]
            )
        )
        note = QLabel(
            "Le document porte l'identité de l'établissement. Un document officiel est figé ; "
            "un document provisoire peut être regénéré, l'ancien reste dans l'historique.",
            objectName="help",
        )
        note.setWordWrap(True)
        self.body.addWidget(note)
        row = QWidget()
        actions = QHBoxLayout(row)
        actions.setContentsMargins(0, 0, 0, 0)
        self.download_button = button("Télécharger le PDF…", "primary")
        self.regenerate_button = button("Regénérer")
        self.regenerate_button.setEnabled(document.status == "PROVISIONAL")
        self.regenerate_button.setToolTip(
            "" if document.status == "PROVISIONAL" else "Seul un document provisoire se regénère."
        )
        for widget in (self.download_button, self.regenerate_button):
            actions.addWidget(widget)
        actions.addStretch()
        self.body.addWidget(row, 0, Qt.AlignLeft)
        self.download_button.clicked.connect(lambda: self._start("download"))
        self.regenerate_button.clicked.connect(lambda: self._start("regenerate"))
        self.finish(required_note=False)

    def _start(self, action):
        self.action = action
        self.accept()


class VerifyDialog(FormDialog):
    def __init__(self, parent=None):
        super().__init__(
            "Vérifier un document",
            "Saisissez le code de vérification imprimé sur le document.",
            parent,
            save_text="Vérifier",
            width=480,
        )
        self.code = self.add_field(
            "code", "Code", QLineEdit(placeholderText="ex. 7KQ2-M9XA"), required=True, width="medium"
        )
        self.code.textChanged.connect(self.refresh_state)
        self.finish()

    def missing_fields(self):
        return [] if self.code.text().strip() else ["Code"]

    def values(self):
        return {"code": self.code.text().strip()}
