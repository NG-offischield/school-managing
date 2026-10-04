"""Add / edit a level: Code, Nom, Cycle, Ordre, Préfixe des classes,
Options (fields supported by the API). The code is fixed once created."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import QCheckBox, QCompleter, QLineEdit

from ..widgets import FormDialog


class LevelDialog(FormDialog):
    def __init__(self, parent=None, level=None, *, cycles=(), next_order=1):
        editing = level is not None
        super().__init__(
            "Modifier le niveau" if editing else "Nouveau niveau",
            "Un niveau regroupe les classes d'une même année d'études (ex. 6e : 6e A, 6e B…).",
            parent,
        )
        self.code = self.add_field(
            "code",
            "Code",
            QLineEdit(placeholderText="Ex. 6E", maxLength=30),
            required=True,
            width="short",
            help_text="Le code ne peut plus être modifié après la création."
            if editing
            else "Court et unique (ex. 6E, TLE, L1).",
        )
        self.name = self.add_field(
            "name",
            "Nom",
            QLineEdit(placeholderText="Ex. Sixième", maxLength=100),
            required=True,
            width="medium",
            beside=True,
        )
        cycle = QLineEdit(placeholderText="Ex. COLLÈGE", maxLength=40)
        if cycles:
            completer = QCompleter(sorted(set(cycles)), cycle)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            cycle.setCompleter(completer)  # suggestions, the cycle stays free (ADR 0008)
        self.cycle = self.add_field(
            "cycle", "Cycle", cycle, width="medium", help_text="Facultatif : collège, lycée, université…"
        )
        order = QLineEdit(placeholderText="Ex. 1", maxLength=3)
        order.setValidator(QIntValidator(0, 999, order))
        self.order = self.add_field(
            "order_index", "Ordre", order, width="short", beside=True, help_text="Rang dans la progression."
        )
        self.prefix = self.add_field(
            "first_character",
            "Préfixe des classes",
            QLineEdit(placeholderText="Ex. 6", maxLength=5),
            width="short",
            help_text="Facultatif : début du nom des classes (« 6 » pour 6e A).",
        )
        self.public_visible = self.add_field("options", "Options", QCheckBox("Visible sur le site public de l'école"))
        if editing:
            self.code.setText(level.code)
            self.code.setReadOnly(True)
            self.name.setText(level.name)
            self.cycle.setText(level.cycle)
            self.order.setText(str(level.order_index))
            self.prefix.setText(level.first_character)
            self.public_visible.setChecked(level.public_visible)
        else:
            self.order.setText(str(next_order))
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
            "code": self.code.text().strip().upper(),
            "name": self.name.text().strip(),
            "cycle": self.cycle.text().strip(),
            "order_index": int(self.order.text()) if self.order.text().strip() else 0,
            "first_character": self.prefix.text().strip(),
            "public_visible": self.public_visible.isChecked(),
        }
