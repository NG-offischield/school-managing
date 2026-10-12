"""Add / edit a class. Rows: Nom | Capacité, Année scolaire | Niveau,
Salle principale | Régime horaire, Options (two columns, one on a narrow
screen). Year, level, room and regime are picked from lists provided by the
API (never free text); the year is fixed once the class exists.

The regime field only appears when the chosen year HAS regimes (schools
without day / evening classes never see it). The server decides whether a
default room may be shared; the dialog only explains it."""

from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit

from ..widgets import FormDialog

CHOOSE_YEAR = "Choisir une année scolaire…"
CHOOSE_LEVEL = "Choisir un niveau…"
NO_ROOM = "Aucune salle principale"
NO_REGIME = "Aucun régime horaire"
ROOM_HELP = (
    "Facultatif. Proposée pour les NOUVEAUX créneaux : la changer ou la retirer ne déplace aucun créneau ni "
    "séance déjà planifiés. Une salle principale n'appartient qu'à une classe de l'année, sauf classes de "
    "régimes horaires distincts (jour / soir)."
)


def _combo(placeholder, items, label=lambda item: item.label):
    combo = QComboBox()
    combo.setEditable(False)  # lists only, no free text
    if placeholder:
        combo.addItem(placeholder, None)
    for item in items:
        combo.addItem(label(item), item.id)
    return combo


class ClassDialog(FormDialog):
    def __init__(self, years, levels, rooms, parent=None, school_class=None, regimes=()):
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
            width="medium",
            help_text="Unique dans l'année scolaire (ex. 6e A, Tle C2).",
        )
        capacity = QLineEdit(placeholderText="Ex. 40", maxLength=3)
        capacity.setValidator(QIntValidator(1, 500, capacity))
        self.capacity = self.add_field(
            "capacity", "Capacité (élèves)", capacity, width="short", beside=True, help_text="Facultatif."
        )
        self.academic_year = self.add_field(
            "academic_year",
            "Année scolaire",
            _combo(CHOOSE_YEAR, years, lambda year: year.short_label),
            required=True,
            width="medium",
            help_text="L'année d'une classe ne change plus après sa création."
            if editing
            else ("Années planifiées ou en cours." if years else "Aucune année ouverte : créez d'abord l'année."),
        )
        self.level = self.add_field(
            "level",
            "Niveau",
            _combo(CHOOSE_LEVEL, levels),
            required=True,
            width="medium",
            beside=True,
            help_text="Seuls les niveaux actifs sont proposés." if levels else "Aucun niveau actif.",
        )
        self.main_room = self.add_field(
            "main_room",
            "Salle principale",
            _combo(NO_ROOM, rooms),
            width="medium",
            help_text=ROOM_HELP,
        )
        self.regimes = list(regimes)
        self.regime = self.add_field(
            "regime",
            "Régime horaire",
            _combo(NO_REGIME, []),
            width="medium",
            beside=True,
            help_text="Facultatif : fenêtre horaire de la classe (ex. cours du soir). Ses créneaux devront s'y tenir.",
        )
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
        self._fill_regimes(school_class.regime_id if editing else None, school_class.regime_label if editing else "")
        self.academic_year.currentIndexChanged.connect(lambda _: self._fill_regimes(None, ""))
        for signal in (self.name.textChanged, self.level.currentIndexChanged, self.academic_year.currentIndexChanged):
            signal.connect(self.refresh_state)
        self.finish()
        self.name.setFocus()

    def _fill_regimes(self, selected_id, selected_label):
        """Regimes of the chosen year only; the field is hidden when there are none."""
        year = self.academic_year.currentData()
        offered = [r for r in self.regimes if r.year_id == year]
        self.regime.clear()
        self.regime.addItem(NO_REGIME, None)
        for regime in offered:
            self.regime.addItem(regime.label, regime.id)
        if selected_id:
            self._select(self.regime, selected_id, f"{selected_label} (inactif)")
        self.regime.parentWidget().setVisible(bool(offered) or bool(selected_id))

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
            "regime_id": self.regime.currentData(),
            "capacity": int(self.capacity.text()) if self.capacity.text().strip() else None,
            "public_visible": self.public_visible.isChecked(),
        }
