"""Add / edit a subject. The category is picked from the EXISTING active
categories (a list, never free text); without a category the form cannot
be saved."""

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from ...models import SUBJECT_TYPES


class SubjectDialog(QDialog):
    def __init__(self, categories, parent=None, subject=None):
        super().__init__(parent)
        self.setWindowTitle("Modifier la matière" if subject else "Nouvelle matière")
        self.setMinimumWidth(440)
        self.code = QLineEdit(placeholderText="Ex. MATH", maxLength=30)
        self.name = QLineEdit(placeholderText="Ex. Mathématiques", maxLength=120)
        self.category = QComboBox()
        self.category.setEditable(False)  # no free text
        self.category.addItem("— Choisir une catégorie —", None)
        for category in categories:
            self.category.addItem(f"{category.code} — {category.name}", category.id)
        self.subject_type = QComboBox()
        for value, label in SUBJECT_TYPES.items():
            self.subject_type.addItem(label, value)
        self.public_visible = QCheckBox("Visible sur le site public")
        form = QFormLayout()
        form.addRow("Code *", self.code)
        form.addRow("Nom *", self.name)
        form.addRow("Catégorie *", self.category)
        form.addRow("Type", self.subject_type)
        form.addRow("", self.public_visible)
        self.hint = QLabel("", objectName="muted")
        self.hint.setWordWrap(True)
        if not categories:
            self.hint.setText("Aucune catégorie active : créez d'abord une catégorie pédagogique.")
        if subject:
            self.code.setText(subject.code)
            self.code.setReadOnly(True)
            self.name.setText(subject.name)
            index = self.category.findData(subject.category_id)
            if index < 0:  # current category now inactive: still shown, so the subject stays coherent
                self.category.addItem(f"{subject.category_label} (inactive)", subject.category_id)
                index = self.category.count() - 1
            self.category.setCurrentIndex(index)
            self.subject_type.setCurrentIndex(max(0, self.subject_type.findData(subject.subject_type)))
            self.public_visible.setChecked(subject.public_visible)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Save).setText("Enregistrer")
        self.buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.hint)
        layout.addWidget(QLabel("* champs obligatoires", objectName="muted"))
        layout.addWidget(self.buttons)
        for signal in (self.code.textChanged, self.name.textChanged, self.category.currentIndexChanged):
            signal.connect(self._update)
        self._update()

    def _update(self):
        ok = bool(self.code.text().strip() and self.name.text().strip() and self.category.currentData())
        self.buttons.button(QDialogButtonBox.Save).setEnabled(ok)

    @property
    def save_enabled(self):
        return self.buttons.button(QDialogButtonBox.Save).isEnabled()

    def values(self):
        return {
            "code": self.code.text().strip(),
            "name": self.name.text().strip(),
            "category_id": self.category.currentData(),
            "subject_type": self.subject_type.currentData(),
            "public_visible": self.public_visible.isChecked(),
        }
