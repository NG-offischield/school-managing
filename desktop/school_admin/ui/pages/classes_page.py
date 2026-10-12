"""Gestion académique → Classes.

Filters: academic year (the current year by default), level, status and a
search on the name. Add / edit open ClassDialog fed with lists fresh from the
API (open years, active levels, active rooms, regimes). « Régimes horaires… »
creates or edits the optional time windows (day / evening classes sharing a
default room); the server enforces every rule."""

from PySide6.QtWidgets import QComboBox, QDialog

from ...i18n import Tr, tr
from ...services.classes import RegimeService
from ..dialogs.class_dialog import ClassDialog
from ..dialogs.regime_dialog import RegimeDialog
from ..widgets import button
from .catalog_base import STATUS_COLUMN_TITLE, CatalogPage

ALL_YEARS = "Toutes les années"
ALL_LEVELS = "Tous les niveaux"


class ClassesPage(CatalogPage):
    title = Tr("Classes")
    description = Tr("Classes de chaque année scolaire, avec leur niveau et leur salle principale.")
    columns = Tr(["Nom", "Niveau", "Année scolaire", "Salle principale", "Capacité", STATUS_COLUMN_TITLE])
    noun = "classe"
    search_placeholder = Tr("Rechercher par nom ou niveau…")

    def __init__(self, service, references, runner, parent=None, *, dialog=ClassDialog, regimes=None, **kwargs):
        self.service = service
        self.references = references
        self.dialog = dialog
        self.regime_service = regimes or RegimeService(service.api)
        self._filters_ready = False
        super().__init__(runner, parent, **kwargs)

    def stretch_columns(self):
        return {0, 3}  # name and room

    def is_filtered(self):
        return super().is_filtered() or bool(self.level_filter.currentData())

    def extra_actions(self):
        self.regimes_button = button(
            tr("Régimes horaires…"), tooltip=tr("Cours du jour / du soir : fenêtres horaires facultatives des classes")
        )
        self.regimes_button.clicked.connect(self.manage_regimes)
        return [self.regimes_button]

    def describe_row(self, row):
        return f"{row.name} — {row.year_name}"

    def add_filters(self, layout):
        self.year_filter = QComboBox()
        self.year_filter.setAccessibleName(tr("Filtrer par année scolaire"))
        self.year_filter.setToolTip(tr("Filtrer par année scolaire"))
        self.year_filter.setMinimumWidth(220)
        self.year_filter.addItem(tr(ALL_YEARS), None)
        self.level_filter = QComboBox()
        self.level_filter.setAccessibleName(tr("Filtrer par niveau"))
        self.level_filter.setToolTip(tr("Filtrer par niveau"))
        self.level_filter.setMinimumWidth(170)
        self.level_filter.addItem(tr(ALL_LEVELS), None)
        for combo in (self.year_filter, self.level_filter):
            combo.currentIndexChanged.connect(lambda _: self._filters_ready and self.reload())
            layout.addWidget(combo)

    def activate(self):
        """Refresh the filter lists (years, levels may have changed), then the list."""
        self.call(
            lambda: (self.references.years(), self.references.levels(active_only=False)),
            self._fill_filters,
            action=tr("Impossible de charger les années et les niveaux"),
        )

    def _fill_filters(self, references):
        years, levels = references
        current_year, current_level = self.year_filter.currentData(), self.level_filter.currentData()
        first_time = not self._filters_ready
        self._filters_ready = False
        self.year_filter.clear()
        self.year_filter.addItem(tr(ALL_YEARS), None)
        for year in years:
            self.year_filter.addItem(year.label, year.id)
        if first_time:  # default: the current year, which is what the administrator works on
            current = next((y for y in years if y.is_current), None)
            current_year = current.id if current else None
        self.year_filter.setCurrentIndex(max(0, self.year_filter.findData(current_year)))
        self.level_filter.clear()
        self.level_filter.addItem(tr(ALL_LEVELS), None)
        for level in levels:
            self.level_filter.addItem(level.label if level.active else tr("{0} (inactif)", level.label), level.id)
        self.level_filter.setCurrentIndex(max(0, self.level_filter.findData(current_level)))
        self._filters_ready = True
        self.reload()

    def fetch(self):
        return self.service.list(
            search=self.search.text(),
            active=self.status.currentData(),
            academic_year_id=self.year_filter.currentData(),
            level_id=self.level_filter.currentData(),
        )

    def cells(self, row):
        capacity = tr("{0} élèves", row.capacity) if row.capacity else "—"
        room = row.main_room_label or "—"
        if row.regime_label:
            room = f"{room} · {row.regime_label}"
        return [row.name, row.level_label, row.year_name, room, capacity, ""]

    # --- dialogs -------------------------------------------------------------------
    def open_dialog(self, references, school_class=None):
        """Returns the dialog values, or None if cancelled (overridable in tests)."""
        years, levels, rooms, regimes = references
        dialog = self.dialog(years, levels, rooms, self, school_class, regimes=regimes)
        return dialog.values() if dialog.exec() == QDialog.Accepted else None

    def _with_references(self, then):
        """Lists offered by the form, fresh from the API: open years, active levels, active rooms, regimes."""
        self.call(
            lambda: (
                self.references.years(open_only=True),
                self.references.levels(),
                self.references.rooms(),
                self.references.regimes(),
            ),
            then,
            action=tr("Impossible de charger les années, niveaux, salles et régimes"),
        )

    # --- timetable regimes ------------------------------------------------------------
    def open_regimes(self, years, regimes):
        """Returns the regime form values, or None if cancelled (overridable in tests)."""
        dialog = RegimeDialog(years, regimes, self)
        return dialog.values() if dialog.exec() == QDialog.Accepted else None

    def manage_regimes(self):
        def open_form(references):
            values = self.open_regimes(*references)
            if not values:
                return
            regime_id = values.pop("regime_id")
            if regime_id:
                values.pop("academic_year_id")
                call = lambda: self.regime_service.update(regime_id, **values)  # noqa: E731
                done, failed = tr("modifié"), tr("Impossible de modifier le régime horaire")
            else:
                values.pop("active")
                call = lambda: self.regime_service.create(**values)  # noqa: E731
                done, failed = tr("créé"), tr("Impossible de créer le régime horaire")
            self.call(
                call,
                lambda saved: self.success(tr("Régime horaire « {0} » {1} avec succès.", saved.name, done)),
                action=failed,
            )

        self.call(
            lambda: (self.references.years(open_only=True), self.regime_service.list()),
            open_form,
            action=tr("Impossible de charger les régimes horaires"),
        )

    def add(self):
        def open_form(references):
            values = self.open_dialog(references)
            if values:
                self.call(
                    lambda: self.service.create(**values),
                    lambda saved: self._saved(saved, tr("créée")),
                    action=tr("Impossible de créer la classe"),
                )

        self._with_references(open_form)

    def edit(self):
        row = self.selected()
        if row is None:
            return

        def open_form(references):
            values = self.open_dialog(references, row)
            if values:
                values.pop("academic_year_id")  # fixed at creation
                self.call(
                    lambda: self.service.update(row.id, **values),
                    lambda saved: self._saved(saved, tr("modifiée")),
                    action=tr("Impossible de modifier la classe"),
                )

        self._with_references(open_form)

    def deactivate(self, row_id):
        return self.service.deactivate(row_id)

    def reactivate(self, row_id):
        return self.service.reactivate(row_id)
