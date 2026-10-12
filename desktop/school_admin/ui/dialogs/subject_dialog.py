"""Add / edit a subject. Order: Code, Nom, Catégorie, Type, options.
The category is picked from the EXISTING active categories (a list, never
free text); without a category the form cannot be saved and the dialog
says why."""

from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit

from ...i18n import tr
from ...models import SUBJECT_TYPES
from ..widgets import FormDialog

CHOOSE_CATEGORY = "Choisir une catégorie…"


class SubjectDialog(FormDialog):
    def __init__(self, categories, parent=None, subject=None):
        editing = subject is not None
        super().__init__(
            tr("Modifier la matière") if editing else tr("Nouvelle matière"),
            tr("Une matière appartient toujours à une catégorie pédagogique existante."),
            parent,
        )
        self.code = self.add_field(
            "code",
            tr("Code"),
            QLineEdit(placeholderText=tr("Ex. MATH"), maxLength=30),
            required=True,
            width="short",
            help_text=tr("Le code ne peut plus être modifié après la création.")
            if editing
            else tr("Court et unique (ex. MATH, SVT)."),
        )
        self.name = self.add_field(
            "name",
            tr("Nom"),
            QLineEdit(placeholderText=tr("Ex. Mathématiques"), maxLength=120),
            required=True,
            width="medium",
            beside=True,
        )
        category = QComboBox()
        category.setEditable(False)  # no free text
        category.addItem(tr(CHOOSE_CATEGORY), None)
        for item in categories:
            category.addItem(f"{item.code} — {item.name}", item.id)
        self.category = self.add_field(
            "category",
            tr("Catégorie"),
            category,
            required=True,
            width="medium",
            help_text=tr("Seules les catégories actives sont proposées.")
            if categories
            else tr("Aucune catégorie active : créez d'abord une catégorie pédagogique."),
        )
        subject_type = QComboBox()
        for value, label in SUBJECT_TYPES.items():
            subject_type.addItem(label, value)
        self.subject_type = self.add_field(
            "subject_type",
            tr("Type"),
            subject_type,
            width="short",
            beside=True,
            help_text=tr("Pratique : lieu ou équipement requis."),
        )
        self.public_visible = self.add_field(
            "options", tr("Options"), QCheckBox(tr("Visible sur le site public de l'école"))
        )
        if editing:
            self.code.setText(subject.code)
            self.code.setReadOnly(True)
            self.name.setText(subject.name)
            index = self.category.findData(subject.category_id)
            if index < 0:  # current category now inactive: still shown, so the subject stays coherent
                self.category.addItem(tr("{0} (inactive)", subject.category_label), subject.category_id)
                index = self.category.count() - 1
            self.category.setCurrentIndex(index)
            self.subject_type.setCurrentIndex(max(0, self.subject_type.findData(subject.subject_type)))
            self.public_visible.setChecked(subject.public_visible)
        for signal in (self.code.textChanged, self.name.textChanged, self.category.currentIndexChanged):
            signal.connect(self.refresh_state)
        self.finish()
        (self.name if editing else self.code).setFocus()

    def missing_fields(self):
        missing = []
        if not self.code.text().strip():
            missing.append(tr("Code"))
        if not self.name.text().strip():
            missing.append(tr("Nom"))
        if not self.category.currentData():
            missing.append(tr("Catégorie"))
        return missing

    def values(self):
        return {
            "code": self.code.text().strip(),
            "name": self.name.text().strip(),
            "category_id": self.category.currentData(),
            "subject_type": self.subject_type.currentData(),
            "public_visible": self.public_visible.isChecked(),
        }
