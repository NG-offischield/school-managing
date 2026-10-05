"""Dialogs of Gestion académique → Parents (ADR 0026): link request record,
identity check against the physical document, pupil's designation, approval
with the parent's rights. The server re-checks every rule."""

from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QWidget

from ...models import IDENTITY_DOCUMENTS, STUDENT_APPROVALS
from ..widgets import FormDialog, button, set_variant
from .teacher_dialogs import _grid


def _when(moment):
    return f"{moment:%d/%m/%Y %H:%M}" if moment else "—"


class LinkRequestDialog(FormDialog):
    """Record of a link request; the buttons offered follow its state."""

    def __init__(self, request, parent=None):
        super().__init__(
            f"Rattachement — {request.parent_name or 'parent'} → {request.student_name}",
            "",
            parent,
            save_text="Fermer",
            width=640,
        )
        self.action = None
        self.cancel_button.hide()
        self.add_section("Demande")
        self.body.addWidget(
            _grid(
                [
                    ("Statut", request.status_label),
                    ("Élève", f"{request.student_name} ({request.student_number})"),
                    ("Classe", request.class_name or "—"),
                    ("Lien déclaré", request.relationship_label),
                    ("Reçue le", _when(request.created_at)),
                ]
                + ([("Motif de la décision", request.decision_reason)] if request.decision_reason else [])
            )
        )
        self.add_section("Parent")
        self.body.addWidget(
            _grid(
                [
                    ("Nom", request.parent_name or "—"),
                    ("E-mail", request.parent_email or "—"),
                    ("Téléphone", request.parent_phone or "—"),
                ]
            )
        )
        self.add_section(
            "Vérifications",
            "Les trois conditions du serveur : identité vérifiée, désignation par l'élève, décision de l'école.",
        )
        identity = [("Identité", request.identity_label)]
        if request.document_type:
            identity.append(("Pièce déclarée", IDENTITY_DOCUMENTS.get(request.document_type, request.document_type)))
        if request.identity_failed_checks:
            identity.append(("Écarts constatés", str(request.identity_failed_checks)))
        if request.sponsored:
            identity.append(("Parrain", request.sponsor_name or "parent vérifié"))
        identity.append(("Désignation par l'élève", request.approval_label))
        if request.student_approval_note:
            identity.append(("Note", request.student_approval_note))
        self.body.addWidget(_grid(identity))

        self.action_buttons = {}
        if request.pending:
            actions = []
            if request.identity_status == "PENDING":
                actions.append(("verify_identity", "Vérifier l'identité…"))
            actions.append(("student_approval", "Désignation par l'élève…"))
            if request.ready:
                actions.append(("approve", "Valider le rattachement…"))
            actions.append(("reject", "Refuser…"))
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(8)
            for name, text in actions:
                widget = button(text, "primary" if name == "approve" else "secondary")
                if name == "reject":
                    set_variant(widget, "danger")
                widget.clicked.connect(lambda _=False, name=name: self._start(name))
                self.action_buttons[name] = widget
                line.addWidget(widget)
            line.addStretch()
            self.body.addWidget(row)
        self.finish(required_note=False)

    def _start(self, action):
        self.action = action
        self.accept()


class IdentityCheckDialog(FormDialog):
    """The administration types the number of the ORIGINAL document shown at
    the counter; the server compares it with what the parent declared."""

    def __init__(self, request, parent=None):
        super().__init__(
            "Vérifier l'identité du parent",
            f"{request.parent_name} — demande pour {request.student_name}. Demandez la pièce ORIGINALE et "
            "recopiez son numéro : le serveur le compare à celui déclaré par le parent. Le numéro n'est pas "
            "conservé ; après 3 écarts, la vérification est refusée.",
            parent,
            save_text="Comparer",
            width=560,
        )
        self.document_type = QComboBox()
        for code, label in IDENTITY_DOCUMENTS.items():
            self.document_type.addItem(label, code)
        index = self.document_type.findData(request.document_type)
        self.document_type.setCurrentIndex(max(index, 0))
        self.add_field("document_type", "Type de pièce présentée", self.document_type, required=True)
        self.number = QLineEdit(placeholderText="ex. 112233445")
        self.number.setMaxLength(60)
        self.add_field(
            "document_number",
            "Numéro de la pièce",
            self.number,
            required=True,
            width="medium",
            help_text="Espaces et tirets sont ignorés.",
        )
        self.number.textChanged.connect(self.refresh_state)
        self.finish()
        self.number.setFocus()

    def missing_fields(self):
        return [] if self.number.text().strip() else ["Numéro de la pièce"]

    def values(self):
        return {"document_type": self.document_type.currentData(), "document_number": self.number.text().strip()}


class StudentApprovalDialog(FormDialog):
    """The pupil designates (or not) this parent; pupils have no account, so
    the administration records their answer."""

    def __init__(self, request, parent=None):
        super().__init__(
            "Désignation par l'élève",
            f"{request.student_name} confirme-t-il que {request.parent_name} est son "
            f"{request.relationship_label.lower()} ?",
            parent,
            width=520,
        )
        self.decision = QComboBox()
        for code in ("APPROVED", "REJECTED", "NOT_REQUIRED"):
            self.decision.addItem(STUDENT_APPROVALS[code], code)
        index = self.decision.findData(request.student_approval_status)
        self.decision.setCurrentIndex(max(index, 0))
        self.add_field(
            "decision",
            "Réponse",
            self.decision,
            required=True,
            help_text="« Non requise » : élève trop jeune, ou lien déjà établi par un document officiel.",
        )
        note = QPlainTextEdit(placeholderText="Contexte (facultatif)")
        note.setFixedHeight(72)
        note.setTabChangesFocus(True)
        self.note = self.add_field("note", "Note", note)
        self.finish()

    def values(self):
        return {"decision": self.decision.currentData(), "note": self.note.toPlainText().strip()}


class LinkApprovalDialog(FormDialog):
    """Final decision: creates the VERIFIED link with the rights chosen here
    (financial rights off by default)."""

    def __init__(self, request, parent=None):
        super().__init__(
            "Valider le rattachement",
            f"{request.parent_name} deviendra parent vérifié de {request.student_name}. Choisissez ses droits ; "
            "ils restent modifiables par l'administration.",
            parent,
            save_text="Valider",
            width=560,
        )
        self.add_section("Droits du parent")
        self.can_view_financial_data = self.add_field(
            "can_view_financial_data", "Finance", QCheckBox("Voir la situation financière (factures, paiements)")
        )
        self.can_pay = self.add_field("can_pay", "Paiement", QCheckBox("Payer pour cet élève"))
        self.can_receive_notifications = self.add_field(
            "can_receive_notifications", "Notifications", QCheckBox("Recevoir les notifications de l'élève")
        )
        self.can_submit_complaints = self.add_field(
            "can_submit_complaints", "Réclamations", QCheckBox("Déposer des réclamations")
        )
        self.can_receive_notifications.setChecked(True)
        self.can_submit_complaints.setChecked(True)
        if request.sponsored:
            hint = QLabel(
                f"Parent parrainé par {request.sponsor_name or 'un parent vérifié'} : le serveur refuse des droits "
                "financiers supérieurs à ceux du parrain.",
                objectName="help",
            )
            hint.setWordWrap(True)
            self.body.addWidget(hint)
        self.finish(required_note=False)

    def values(self):
        return {
            "can_pay": self.can_pay.isChecked(),
            "can_view_financial_data": self.can_view_financial_data.isChecked(),
            "can_receive_notifications": self.can_receive_notifications.isChecked(),
            "can_submit_complaints": self.can_submit_complaints.isChecked(),
        }
