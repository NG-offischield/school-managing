"""Gestion académique → Années scolaires / Niveaux.

Années scolaires: list (newest first), Ajouter, Modifier (open years),
Définir comme courante, Clôturer. A year is never deleted nor deactivated:
its life cycle is planifiée → en cours (courante) → clôturée; the server
decides whether an action is allowed and the page explains its refusals.

Niveaux: same list screen as the catalogue (code, name, cycle, order,
classes using it, status) with Désactiver / Réactiver.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import QDialog, QTableWidgetItem

from ...i18n import Texts, Tr, tr
from ..dialogs.level_dialog import LevelDialog
from ..dialogs.year_dialog import YearDialog, suggested_dates
from ..theme import TOKENS
from ..widgets import button
from .catalog_base import STATUS_COLUMN_TITLE, CatalogPage

YEAR_STATE_FILTERS = Texts([("Toutes", None), ("Ouvertes", "open"), ("Clôturées", "closed")])


def _day(value):
    return (f"{value:%d/%m/%Y}", value.isoformat()) if value else ("—", "")


def _count(value):
    return ("—", -1) if value is None else (str(value), value)


class YearsPage(CatalogPage):
    title = Tr("Années scolaires")
    description = Tr("Années de l'école : l'année courante est celle proposée par défaut dans tous les écrans.")
    columns = Tr(["Nom", "Début", "Fin", "Classes", STATUS_COLUMN_TITLE])
    noun = "année"
    search_placeholder = Tr("Rechercher une année…")
    status_filters = YEAR_STATE_FILTERS
    has_toggle = False
    default_sort = (1, Qt.DescendingOrder)  # newest year first (by start date)

    def __init__(self, service, runner, parent=None, *, dialog=YearDialog, **kwargs):
        self.service = service
        self.dialog = dialog
        super().__init__(runner, parent, **kwargs)
        self.current_button.clicked.connect(self.set_current)
        self.close_button.clicked.connect(self.close_year)
        self.status.setToolTip(tr("Filtrer par état"))

    def stretch_columns(self):
        return {0}

    def extra_actions(self):
        self.current_button = button(tr("Définir comme courante"))
        self.close_button = button(tr("Clôturer"), "danger")
        return [self.current_button, self.close_button]

    def describe_row(self, row):
        return row.name

    def fetch(self):
        return self.service.list(search=self.search.text(), state=self.status.currentData())

    def cells(self, row):
        return [row.name, _day(row.start_date), _day(row.end_date), _count(row.class_count), ""]

    def status_cell(self, row):
        text = tr("★  En cours · courante") if row.is_current else f"{'●' if row.open else '○'}  {row.status_label}"
        item = QTableWidgetItem(text)
        colour = TOKENS.success if row.is_current else (TOKENS.text if row.open else TOKENS.text_secondary)
        item.setForeground(QBrush(QColor(colour)))
        font = QFont()
        font.setWeight(QFont.DemiBold if row.is_current else QFont.Normal)
        item.setFont(font)
        item.setToolTip(
            tr("Année proposée par défaut dans tous les écrans")
            if row.is_current
            else (tr("Modifiable") if row.open else tr("Clôturée : conservée pour l'historique, non modifiable"))
        )
        return item

    def update_extra_actions(self, row):
        if not hasattr(self, "current_button"):
            return
        if row is None:
            why = tr("Sélectionnez d'abord une année dans la liste.")
            for widget in (self.current_button, self.close_button):
                widget.setEnabled(False)
                widget.setToolTip(why)
            return
        closed = tr("Cette année est clôturée.")
        self.edit_button.setEnabled(row.open)
        self.edit_button.setToolTip(tr("Modifier le nom ou les dates (Entrée)") if row.open else closed)
        self.current_button.setEnabled(row.open and not row.is_current)
        self.current_button.setToolTip(
            closed
            if not row.open
            else (
                tr("C'est déjà l'année courante.")
                if row.is_current
                else tr("Proposer cette année par défaut dans tous les écrans (elle passe « en cours »).")
            )
        )
        self.close_button.setEnabled(row.open and not row.is_current)
        self.close_button.setToolTip(
            closed
            if not row.open
            else (
                tr("Définissez d'abord une autre année comme courante.")
                if row.is_current
                else tr("Figer l'année : plus aucune classe, inscription ou présence ne pourra y être saisie.")
            )
        )

    # --- actions --------------------------------------------------------------------
    def open_dialog(self, year=None):
        """Returns the dialog values, or None if cancelled (overridable in tests)."""
        dialog = self.dialog(self, year, suggested=None if year else suggested_dates(self.rows))
        return dialog.values() if dialog.exec() == QDialog.Accepted else None

    def add(self):
        values = self.open_dialog()
        if values:
            self.call(
                lambda: self.service.create(**values),
                lambda saved: self._saved(saved, tr("créée")),
                action=tr("Impossible de créer l'année scolaire"),
            )

    def edit(self):
        row = self.selected()
        if row is None or not row.open:
            return
        values = self.open_dialog(row)
        if values:
            self.call(
                lambda: self.service.update(row.id, **values),
                lambda saved: self._saved(saved, tr("modifiée")),
                action=tr("Impossible de modifier l'année scolaire"),
            )

    def set_current(self):
        row = self.selected()
        if row is None:
            return
        text = tr(
            "« {0} » deviendra l'année proposée par défaut dans tous les écrans (classes, inscriptions, présences…) "
            "et passera « en cours ».\n\nL'année courante actuelle reste ouverte mais n'est plus proposée par défaut.",
            row.name,
        )
        if not self.confirm(
            self, tr("Définir comme année courante ?"), text, confirm_text=tr("Définir comme courante")
        ):
            return
        self.call(
            lambda: self.service.set_current(row.id),
            lambda saved: self._done(saved, tr("« {0} » est maintenant l'année courante.", saved.name)),
            action=tr("Impossible de définir l'année courante"),
        )

    def close_year(self):
        row = self.selected()
        if row is None:
            return
        text = tr(
            "« {0} » sera figée : plus aucune classe, inscription, présence ou séance ne pourra y être créée ou "
            "modifiée. Ses données restent consultables.\n\nLe serveur refusera la clôture si des élèves y sont "
            "encore inscrits.",
            row.name,
        )
        if not self.confirm(self, tr("Clôturer l'année scolaire ?"), text, confirm_text=tr("Clôturer"), danger=True):
            return
        self.call(
            lambda: self.service.close(row.id),
            lambda saved: self._done(saved, tr("Année « {0} » clôturée.", saved.name)),
            action=tr("Impossible de clôturer l'année scolaire"),
        )

    def _done(self, saved, message):
        self.success(message)
        self.call(
            self.fetch,
            lambda rows: (self.show_rows(rows), self.select_id(saved.id)),
            action=tr("Impossible de charger les années"),
        )


class LevelsPage(CatalogPage):
    title = Tr("Niveaux")
    description = Tr("Niveaux d'études de l'école (6e, 5e… ou L1, L2…), dans l'ordre de la progression.")
    columns = Tr(["Ordre", "Code", "Nom", "Cycle", "Classes ouvertes", STATUS_COLUMN_TITLE])
    noun = "niveau"
    feminine = False
    plural_noun = "niveaux"
    search_placeholder = Tr("Rechercher par code, nom ou cycle…")

    def __init__(self, service, runner, parent=None, *, dialog=LevelDialog, **kwargs):
        self.service = service
        self.dialog = dialog
        super().__init__(runner, parent, **kwargs)

    def stretch_columns(self):
        return {2}

    def fetch(self):
        return self.service.list(search=self.search.text(), active=self.status.currentData())

    def cells(self, row):
        order = (str(row.order_index), row.order_index)
        return [order, row.code, row.name, row.cycle or "—", _count(row.class_count), ""]

    def open_dialog(self, level=None):
        """Returns the dialog values, or None if cancelled (overridable in tests)."""
        cycles = [r.cycle for r in self.rows if r.cycle]
        next_order = max((r.order_index for r in self.rows), default=0) + 1
        dialog = self.dialog(self, level, cycles=cycles, next_order=next_order)
        return dialog.values() if dialog.exec() == QDialog.Accepted else None

    def add(self):
        values = self.open_dialog()
        if values:
            self.call(
                lambda: self.service.create(**values),
                lambda saved: self._saved(saved, tr("créé")),
                action=tr("Impossible de créer le niveau"),
            )

    def edit(self):
        row = self.selected()
        if row is None:
            return
        values = self.open_dialog(row)
        if values:
            values.pop("code")  # fixed at creation
            self.call(
                lambda: self.service.update(row.id, **values),
                lambda saved: self._saved(saved, tr("modifié")),
                action=tr("Impossible de modifier le niveau"),
            )

    def deactivate(self, row_id):
        return self.service.deactivate(row_id)

    def reactivate(self, row_id):
        return self.service.reactivate(row_id)
