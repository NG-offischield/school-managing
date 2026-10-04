"""Add / edit a pedagogical category (fields supported by the API: code at
creation only — immutable afterwards —, name, description)."""

from PySide6.QtWidgets import QLineEdit, QPlainTextEdit

from ..widgets import FormDialog


class CategoryDialog(FormDialog):
    def __init__(self, parent=None, category=None):
        editing = category is not None
        super().__init__(
            "Modifier la catégorie" if editing else "Nouvelle catégorie",
            "Une catégorie regroupe des matières (ex. Scientifique : mathématiques, physique…).",
            parent,
        )
        self.code = self.add_field(
            "code",
            "Code",
            QLineEdit(placeholderText="Ex. SCI", maxLength=40),
            required=True,
            help_text="Le code ne peut plus être modifié après la création."
            if editing
            else "Court et unique, en majuscules (ex. SCI, LIT).",
        )
        self.name = self.add_field(
            "name", "Nom", QLineEdit(placeholderText="Ex. Scientifique", maxLength=120), required=True
        )
        description = QPlainTextEdit(placeholderText="Facultatif")
        description.setFixedHeight(84)
        description.setTabChangesFocus(True)  # Tab leaves the text area, as in the other fields
        self.description = self.add_field("description", "Description", description)
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
            missing.append("Code")
        if not self.name.text().strip():
            missing.append("Nom")
        return missing

    def values(self):
        return {
            "code": self.code.text().strip(),
            "name": self.name.text().strip(),
            "description": self.description.toPlainText().strip(),
        }
