"""Add / edit a pedagogical category (fields supported by the API: code at
creation only — immutable afterwards —, name, description)."""

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout


class CategoryDialog(QDialog):
    def __init__(self, parent=None, category=None):
        super().__init__(parent)
        self.setWindowTitle("Modifier la catégorie" if category else "Nouvelle catégorie")
        self.setMinimumWidth(420)
        self.code = QLineEdit(placeholderText="Ex. SCI", maxLength=40)
        self.name = QLineEdit(placeholderText="Ex. Scientifique", maxLength=120)
        self.description = QPlainTextEdit()
        self.description.setFixedHeight(80)
        form = QFormLayout()
        form.addRow("Code *", self.code)
        form.addRow("Nom *", self.name)
        form.addRow("Description", self.description)
        if category:
            self.code.setText(category.code)
            self.code.setReadOnly(True)
            self.code.setToolTip("Le code d'une catégorie ne change pas (traçabilité).")
            self.name.setText(category.name)
            self.description.setPlainText(category.description)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText("Enregistrer")
        self.buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("* champs obligatoires", objectName="muted"))
        layout.addWidget(self.buttons)
        self.code.textChanged.connect(self._update)
        self.name.textChanged.connect(self._update)
        self._update()

    def _update(self):
        ok = bool(self.code.text().strip() and self.name.text().strip())
        self.buttons.button(QDialogButtonBox.Save).setEnabled(ok)

    @property
    def save_enabled(self):
        return self.buttons.button(QDialogButtonBox.Save).isEnabled()

    def values(self):
        return {
            "code": self.code.text().strip(),
            "name": self.name.text().strip(),
            "description": self.description.toPlainText().strip(),
        }
