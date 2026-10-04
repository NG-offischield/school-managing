"""Shared list screen of the catalogue.

    Title                                              N éléments
    Short description of the screen
    [Rechercher…] [Statut ▼] (filters)    Actualiser Modifier Désactiver [Ajouter]
    (message banner)
    ┌ table ─────────────────────────────────────────────────────────┐
    └────────────────────────────────────────────────────────────────┘

Button roles: Ajouter = primary, Désactiver = danger, the rest secondary.
Keyboard: Ctrl+N add, Entrée / double-clic edit, F5 reload, Ctrl+F search.
A disabled action says why in its tooltip.
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QStackedLayout,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..theme import TOKENS
from ..widgets import Page, button, set_variant

STATUS_FILTERS = [("Actives", True), ("Inactives", False), ("Toutes", None)]
STATUS_COLUMN_TITLE = "Statut"


def status_item(active):
    item = QTableWidgetItem("●  Active" if active else "○  Inactive")
    item.setForeground(QBrush(QColor(TOKENS.success if active else TOKENS.text_secondary)))
    font = QFont()
    font.setWeight(QFont.DemiBold if active else QFont.Normal)
    item.setFont(font)
    item.setToolTip("Proposée dans les nouvelles saisies" if active else "Désactivée : conservée pour l'historique")
    return item


class CatalogPage(Page):
    title = ""
    description = ""
    columns = []
    noun = ""  # "catégorie", "matière"
    feminine = True

    def __init__(self, runner, parent=None, **kwargs):
        super().__init__(runner, parent, **kwargs)
        self.rows = []
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(QLabel(self.title, objectName="pageTitle"))
        subtitle = QLabel(self.description, objectName="subtitle")
        subtitle.setWordWrap(True)
        titles.addWidget(subtitle)
        head.addLayout(titles, 1)
        self.count_label = QLabel("", objectName="countLabel")
        head.addWidget(self.count_label, 0, Qt.AlignBottom)
        self.layout_.addLayout(head)

        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.search = QLineEdit(placeholderText="Rechercher par code ou nom…", clearButtonEnabled=True)
        self.search.setAccessibleName("Rechercher")
        self.search.setMinimumWidth(240)
        self.status = QComboBox()
        self.status.setAccessibleName("Filtrer par statut")
        self.status.setToolTip("Filtrer par statut")
        for label, value in STATUS_FILTERS:
            self.status.addItem(label, value)
        self.status.setMinimumWidth(130)
        tools.addWidget(self.search, 2)
        tools.addWidget(self.status)
        self.add_filters(tools)
        tools.addStretch(1)
        self.refresh_button = button("Actualiser", tooltip="Recharger la liste (F5)")
        self.edit_button = button("Modifier")
        self.toggle_button = button("Désactiver", "danger")
        self.add_button = button("Ajouter", "primary", tooltip=f"Ajouter une {self.noun} (Ctrl+N)")
        for widget in (self.refresh_button, self.edit_button, self.toggle_button, self.add_button):
            tools.addWidget(widget)
        self.layout_.addLayout(tools)
        self.layout_.addWidget(self.banner)

        self.table = QTableWidget(0, len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)
        self.table.setAccessibleName(self.title)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setHighlightSections(False)
        header.setMinimumSectionSize(90)
        for index in range(len(self.columns)):
            mode = QHeaderView.Stretch if index in self.stretch_columns() else QHeaderView.ResizeToContents
            header.setSectionResizeMode(index, mode)
        self.empty = QLabel("", objectName="emptyState", alignment=Qt.AlignCenter)
        self.empty.setWordWrap(True)
        holder = QWidget()
        self.table_stack = QStackedLayout(holder)
        self.table_stack.addWidget(self.table)
        self.table_stack.addWidget(self.empty)
        self.layout_.addWidget(holder, 1)

        self._debounce = QTimer(self, singleShot=True, interval=300, timeout=self.reload)
        self.search.textChanged.connect(lambda _: self._debounce.start())
        self.status.currentIndexChanged.connect(lambda _: self.reload())
        self.add_button.clicked.connect(self.add)
        self.edit_button.clicked.connect(self.edit)
        self.toggle_button.clicked.connect(self.toggle)
        self.refresh_button.clicked.connect(self.reload)
        self.table.itemSelectionChanged.connect(self._update_actions)
        self.table.doubleClicked.connect(lambda _: self.edit())
        QShortcut(QKeySequence.New, self, activated=lambda: self.add_button.isEnabled() and self.add())
        QShortcut(QKeySequence.Refresh, self, activated=self.reload)
        QShortcut(QKeySequence.Find, self, activated=self.search.setFocus)
        QShortcut(QKeySequence(Qt.Key_Return), self.table, activated=self.edit)
        self._update_actions()

    # --- to implement ---------------------------------------------------------
    def stretch_columns(self):
        return {1}  # the name

    def add_filters(self, layout):
        pass

    def fetch(self):
        raise NotImplementedError

    def cells(self, row):
        raise NotImplementedError

    @property
    def plural(self):
        return f"{self.noun}s"

    # --- list -------------------------------------------------------------------
    def reload(self):
        self.call(self.fetch, self.show_rows, action=f"Impossible de charger les {self.plural}")

    def show_rows(self, rows):
        self.rows = rows
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(self.cells(row)):
                item = status_item(row.active) if self.columns[c] == STATUS_COLUMN_TITLE else QTableWidgetItem(value)
                item.setData(Qt.UserRole, row.id)
                if value and self.columns[c] != STATUS_COLUMN_TITLE:
                    item.setToolTip(value)
                self.table.setItem(r, c, item)
        self.table.setSortingEnabled(True)
        count = len(rows)
        self.count_label.setText(f"{count} {self.noun if count < 2 else self.plural}")
        filtered = bool(self.search.text().strip()) or self.status.currentData() is not True
        self.empty.setText(
            f"Aucune {self.noun} ne correspond à ces critères."
            if filtered
            else f"Aucune {self.noun} pour le moment. Cliquez sur « Ajouter » pour en créer une."
        )
        self.table_stack.setCurrentWidget(self.table if rows else self.empty)
        self._update_actions()

    def selected(self):
        items = self.table.selectedItems()
        if not items:
            return None
        row_id = items[0].data(Qt.UserRole)
        return next((row for row in self.rows if row.id == row_id), None)

    def select_id(self, row_id):
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(Qt.UserRole) == row_id:
                self.table.selectRow(r)
                return

    def _update_actions(self):
        row = self.selected()
        available = row is not None and not self.busy
        self.edit_button.setEnabled(available)
        self.toggle_button.setEnabled(available)
        reactivate = row is not None and not row.active
        self.toggle_button.setText("Réactiver" if reactivate else "Désactiver")
        set_variant(self.toggle_button, "secondary" if reactivate else "danger")
        why = "" if row is not None else f"Sélectionnez d'abord une {self.noun} dans la liste."
        self.edit_button.setToolTip(why or "Modifier la ligne sélectionnée (Entrée)")
        self.toggle_button.setToolTip(why or ("Réactiver" if reactivate else "Désactiver (l'historique est conservé)"))
        self.add_button.setEnabled(not self.busy)

    def set_busy(self, busy):
        super().set_busy(busy)
        self.refresh_button.setEnabled(not busy)
        self._update_actions()

    # --- actions (dialog-driven, implemented by subclasses) ---------------------
    def add(self):
        raise NotImplementedError

    def edit(self):
        raise NotImplementedError

    def toggle(self):
        row = self.selected()
        if row is None:
            return
        if row.active:
            text = (
                f"« {row.code} — {row.name} » ne sera plus proposée dans les nouvelles saisies. "
                f"Son historique est conservé et vous pourrez la réactiver.\n\n"
                f"Le serveur refusera la désactivation si elle est encore utilisée."
            )
            if not self.confirm(self, f"Désactiver la {self.noun} ?", text, confirm_text="Désactiver", danger=True):
                return
            self.call(
                lambda: self.deactivate(row.id),
                lambda saved: self._saved(saved, "désactivée"),
                action=f"Impossible de désactiver la {self.noun}",
            )
        else:
            self.call(
                lambda: self.reactivate(row.id),
                lambda saved: self._saved(saved, "réactivée"),
                action=f"Impossible de réactiver la {self.noun}",
            )

    def _saved(self, saved, verb):
        self.success(f"{self.noun.capitalize()} « {saved.code} » {verb} avec succès.")
        self.call(
            self.fetch,
            lambda rows: (self.show_rows(rows), self.select_id(saved.id)),
            action=f"Impossible de charger les {self.plural}",
        )
