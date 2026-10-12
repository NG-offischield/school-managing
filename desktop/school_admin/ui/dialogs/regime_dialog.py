"""Timetable regimes of a school year (Classes → « Régimes horaires… »).

One form: pick the year, then « Nouveau régime… » or an existing regime
(its values are pre-filled), name, start, end, active. A regime is an
explicit time window (e.g. cours du soir 17:00–21:00) that lets a day class
and an evening class share one default room; the server checks the hours
(same day, end after start), unique names, shared rooms and slots."""

from PySide6.QtCore import QTime
from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit

from ..widgets import FormDialog, time_field

NEW_REGIME = "Nouveau régime…"


class RegimeDialog(FormDialog):
    def __init__(self, years, regimes, parent=None):
        super().__init__(
            "Régimes horaires",
            "Facultatif : utile seulement si des classes de cours du jour et du soir partagent une salle principale. "
            "Une fenêtre horaire tient dans une même journée (pas après minuit).",
            parent,
        )
        self.regimes = list(regimes)
        self.year = QComboBox()
        for year in years:
            self.year.addItem(year.short_label, year.id)
        self.add_field("academic_year", "Année scolaire", self.year, required=True, width="medium")
        self.regime = self.add_field("regime", "Régime", QComboBox(), width="medium", beside=True)
        self.name = self.add_field(
            "name", "Nom", QLineEdit(placeholderText="Ex. Cours du soir", maxLength=80), required=True, width="medium"
        )
        self.start = self.add_field("start_time", "Début", time_field(QTime(17, 0)), required=True, width="short")
        self.end = self.add_field(
            "end_time", "Fin", time_field(QTime(21, 0)), required=True, width="short", beside=True
        )
        self.active = self.add_field("options", "Options", QCheckBox("Régime actif"))
        self.active.setChecked(True)
        self.year.currentIndexChanged.connect(lambda _: self._fill_regimes())
        self.regime.currentIndexChanged.connect(lambda _: self._load())
        self.name.textChanged.connect(self.refresh_state)
        self._fill_regimes()
        self.finish()

    def _fill_regimes(self):
        self.regime.blockSignals(True)
        self.regime.clear()
        self.regime.addItem(NEW_REGIME, None)
        for regime in self.regimes:
            if regime.year_id == self.year.currentData():
                self.regime.addItem(regime.label if regime.active else f"{regime.label} (inactif)", regime.id)
        self.regime.blockSignals(False)
        self._load()

    def _load(self):
        regime = next((r for r in self.regimes if r.id == self.regime.currentData()), None)
        self.name.setText(regime.name if regime else "")
        self.start.setTime(QTime.fromString(regime.start, "HH:mm") if regime else QTime(17, 0))
        self.end.setTime(QTime.fromString(regime.end, "HH:mm") if regime else QTime(21, 0))
        self.active.setChecked(regime.active if regime else True)
        self.active.setEnabled(regime is not None)  # a new regime starts active
        self.save_button.setText("Enregistrer" if regime else "Créer le régime")
        self.refresh_state()

    def missing_fields(self):
        missing = []
        if not self.year.currentData():
            missing.append("Année scolaire")
        if not self.name.text().strip():
            missing.append("Nom")
        return missing

    def values(self):
        return {
            "regime_id": self.regime.currentData(),
            "academic_year_id": self.year.currentData(),
            "name": self.name.text().strip(),
            "start": self.start.time().toString("HH:mm"),
            "end": self.end.time().toString("HH:mm"),
            "active": self.active.isChecked(),
        }
