"""Add / edit a pedagogical category (fields supported by the API: code at
creation only — immutable afterwards —, name, description)."""

from PySide6.QtWidgets import QLineEdit, QPlainTextEdit

from ...i18n import tr
from ..widgets import FormDialog


class CategoryDialog(FormDialog):
    def __init__(self, parent=None, category=None):
        editing = category is not None
        super().__init__(
            tr("Modifier la catégorie") if editing else tr("Nouvelle catégorie"),
            tr("Une catégorie regroupe des matières (ex. Scientifique : mathématiques, physique…)."),
            parent,
        )
        self.code = self.add_field(
            "code",
            tr("Code"),
            QLineEdit(placeholderText=tr("Ex. SCI"), maxLength=40),
            required=True,
            width="short",
            help_text=tr("Le code ne peut plus être modifié après la création.")
            if editing
            else tr("Court et unique (ex. SCI, LIT)."),
        )
        self.name = self.add_field(
            "name",
            tr("Nom"),
            QLineEdit(placeholderText=tr("Ex. Scientifique"), maxLength=120),
            required=True,
            width="medium",
            beside=True,
        )
        description = QPlainTextEdit(placeholderText=tr("Facultatif"))
        description.setFixedHeight(84)
        description.setTabChangesFocus(True)  # Tab leaves the text area, as in the other fields
        self.description = self.add_field("description", tr("Description"), description)
        if editing:
            self.code.setText(category.code)
            self.code.setReadOnly(True)
            self.name.setText(category.name)
            self.description.setPlainText(category.description)
        for field in (self.code, self.name):
            field.textChanged.connect(self.refresh_state)
        self.finish()
        (self.name if editing else self.code).setFocus()

    def missing_fields(self):
        missing = []
        if not self.code.text().strip():
            missing.append(tr("Code"))
        if not self.name.text().strip():
            missing.append(tr("Nom"))
        return missing

    def values(self):
        return {
            "code": self.code.text().strip(),
            "name": self.name.text().strip(),
            "description": self.description.toPlainText().strip(),
        }
