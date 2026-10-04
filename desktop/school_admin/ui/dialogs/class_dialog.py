"""Add / edit a class. Order: Nom, Année scolaire, Niveau, Salle principale,
Capacité, Options. Year, level and room are picked from lists provided by the
API (never free text); the year is fixed once the class exists."""

from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit

from ..widgets import FormDialog

CHOOSE_YEAR = "Choisir une année scolaire…"
CHOOSE_LEVEL = "Choisir un niveau…"
NO_ROOM = "Aucune salle principale"


def _combo(placeholder, items, label=lambda item: item.label):
    combo = QComboBox()
    combo.setEditable(False)  # lists only, no free text
    if placeholder:
        combo.addItem(placeholder, None)
    for item in items:
        combo.addItem(label(item), item.id)
    return combo


class ClassDialog(FormDialog):
    def __init__(self, years, levels, rooms, parent=None, school_class=None):
        editing = school_class is not None
        super().__init__(
            "Modifier la classe" if editing else "Nouvelle classe",
            "Une classe appartient à une année scolaire et à un niveau de l'école.",
            parent,
        )
        self.name = self.add_field(
            "name",
            "Nom",
            QLineEdit(placeholderText="Ex. 6e A", maxLength=80),
            required=True,
            help_text="Unique dans l'année scolaire (ex. 6e A, Tle C2).",
        )
        self.academic_year = self.add_field(
            "academic_year",
            "Année scolaire",
            _combo(CHOOSE_YEAR, years),
            required=True,
            help_text="L'année d'une classe ne change plus après sa création."
            if editing
            else ("Années planifiées ou en cours." if years else "Aucune année ouverte : créez d'abord l'année."),
        )
        self.level = self.add_field(
            "level",
            "Niveau",
            _combo(CHOOSE_LEVEL, levels),
            required=True,
            help_text="Seuls les niveaux actifs sont proposés." if levels else "Aucun niveau actif.",
        )
        self.main_room = self.add_field(
            "main_room",
            "Salle principale",
            _combo(NO_ROOM, rooms),
            help_text="Facultatif : salle par défaut des cours théoriques de la classe.",
        )
        capacity = QLineEdit(placeholderText="Facultatif, ex. 40", maxLength=3)
        capacity.setValidator(QIntValidator(1, 500, capacity))
        self.capacity = self.add_field("capacity", "Capacité (élèves)", capacity, help_text="Nombre maximal d'élèves.")
        self.public_visible = self.add_field("options", "Options", QCheckBox("Visible sur le site public de l'école"))

        if editing:
            self._select(self.academic_year, school_class.year_id, f"{school_class.year_name}")
            self.academic_year.setEnabled(False)
            self.name.setText(school_class.name)
            self._select(self.level, school_class.level_id, f"{school_class.level_label} (inactif)")
            if school_class.main_room_id:
                self._select(self.main_room, school_class.main_room_id, f"{school_class.main_room_label} (inactive)")
            self.capacity.setText(str(school_class.capacity) if school_class.capacity else "")
            self.public_visible.setChecked(school_class.public_visible)
        elif years:
            self.academic_year.setCurrentIndex(1)  # the current year comes first
        for signal in (self.name.textChanged, self.level.currentIndexChanged, self.academic_year.currentIndexChanged):
            signal.connect(self.refresh_state)
        self.finish()
        self.name.setFocus()

    @staticmethod
    def _select(combo, value, missing_label):
        """Select `value`; if it is no longer offered (inactive), show it anyway."""
        index = combo.findData(value)
        if index < 0:
            combo.addItem(missing_label, value)
            index = combo.count() - 1
        combo.setCurrentIndex(index)

    def missing_fields(self):
        missing = []
        if not self.name.text().strip():
            missing.append("Nom")
        if not self.academic_year.currentData():
            missing.append("Année scolaire")
        if not self.level.currentData():
            missing.append("Niveau")
        return missing

    def values(self):
        return {
            "name": self.name.text().strip(),
            "academic_year_id": self.academic_year.currentData(),
            "level_id": self.level.currentData(),
            "main_room_id": self.main_room.currentData(),
            "capacity": int(self.capacity.text()) if self.capacity.text().strip() else None,
            "public_visible": self.public_visible.isChecked(),
        }
