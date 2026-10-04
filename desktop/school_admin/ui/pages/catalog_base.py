"""Shared list screen of the catalogue.

    Title                                              N éléments
    Short description of the screen
    [Rechercher…] [Statut ▼] (filters)    Actualiser Modifier Désactiver [Ajouter]
    (message banner)
    ┌ table ─────────────────────────────────────────────────────────┐
    └────────────────────────────────────────────────────────────────┘

Button roles: Ajouter = primary, Désactiver = danger, the rest secondary.
A page may replace Désactiver/Réactiver by its own actions (`has_toggle`,
`extra_actions`, e.g. Années scolaires: Définir comme courante, Clôturer).
`cells()` may return (text, sort_key) pairs: dates and numbers then sort
by value, not alphabetically.
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
MASCULINE_STATUS_FILTERS = [("Actifs", True), ("Inactifs", False), ("Tous", None)]
STATUS_COLUMN_TITLE = "Statut"


class SortableItem(QTableWidgetItem):
    """Table cell sorted by a key (date, number) instead of its text."""

    def __init__(self, text, key):
        super().__init__(text)
        self.key = key

    def __lt__(self, other):
        other_key = getattr(other, "key", None)
        if other_key is None or type(other_key) is not type(self.key):
            return super().__lt__(other)
        return self.key < other_key


def status_item(active, feminine=True):
    e = "e" if feminine else ""
    word = ("Active" if active else "Inactive") if feminine else ("Actif" if active else "Inactif")
    item = QTableWidgetItem(f"●  {word}" if active else f"○  {word}")
    item.setForeground(QBrush(QColor(TOKENS.success if active else TOKENS.text_secondary)))
    font = QFont()
    font.setWeight(QFont.DemiBold if active else QFont.Normal)
    item.setFont(font)
    item.setToolTip(
        f"Proposé{e} dans les nouvelles saisies" if active else f"Désactivé{e} : conservé{e} pour l'historique"
    )
    return item


class CatalogPage(Page):
    title = ""
    description = ""
    columns = []
    noun = ""  # "catégorie", "matière", "niveau"
    feminine = True
    plural_noun = ""  # irregular plural ("niveaux"); default noun + "s"
    search_placeholder = "Rechercher par code ou nom…"
    status_filters = STATUS_FILTERS
    has_toggle = True  # Désactiver / Réactiver
    default_sort = (0, Qt.AscendingOrder)  # (column, order) when the list opens
    sortable = True  # False when the server orders the rows (paginated lists)

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
        # Actions sit on the title row (right): the filter row below keeps the
        # whole width, so several filters fit at 1366x768 without overlapping.
        self.refresh_button = button("Actualiser", tooltip="Recharger la liste (F5)")
        self.edit_button = button("Modifier")
        self.toggle_button = button("Désactiver", "danger")
        self.add_button = button("Ajouter", "primary", tooltip=f"Ajouter {self.a} {self.noun} (Ctrl+N)")
        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.toggle_button.setVisible(self.has_toggle)
        buttons = (
            self.refresh_button,
            *self.leading_actions(),
            self.edit_button,
            self.toggle_button,
            *self.extra_actions(),
            self.add_button,
        )
        for widget in buttons:
            actions.addWidget(widget)
        head.addLayout(actions)
        head.setAlignment(actions, Qt.AlignTop)
        self.layout_.addLayout(head)

        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.search = QLineEdit(placeholderText=self.search_placeholder, clearButtonEnabled=True)
        self.search.setAccessibleName("Rechercher")
        self.search.setMinimumWidth(220)
        self.status = QComboBox()
        self.status.setAccessibleName("Filtrer par statut")
        self.status.setToolTip("Filtrer par statut")
        filters = self.status_filters
        if filters is STATUS_FILTERS and not self.feminine:
            filters = MASCULINE_STATUS_FILTERS
        for label, value in filters:
            self.status.addItem(label, value)
        self.status.setMinimumWidth(130)
        tools.addWidget(self.search, 1)
        tools.addWidget(self.status)
        self.add_filters(tools)
        self.count_label = QLabel("", objectName="countLabel")
        tools.addSpacing(8)
        tools.addWidget(self.count_label)
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
        # Ascending by the first column (Qt defaults to DESCENDING once sorting is on).
        self.table.horizontalHeader().setSortIndicator(*self.default_sort)
        self.table.setSortingEnabled(self.sortable)
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
        self.table.doubleClicked.connect(lambda _: self.open_row())
        QShortcut(QKeySequence.New, self, activated=lambda: self.add_button.isEnabled() and self.add())
        QShortcut(QKeySequence.Refresh, self, activated=self.reload)
        QShortcut(QKeySequence.Find, self, activated=self.search.setFocus)
        QShortcut(QKeySequence(Qt.Key_Return), self.table, activated=lambda: self.open_row())
        self._update_actions()

    # --- to implement ---------------------------------------------------------
    def stretch_columns(self):
        return {1}  # the name

    def add_filters(self, layout):
        pass

    def open_row(self):
        """Double-click / Entrée on a row (default: edit it)."""
        self.edit()

    def leading_actions(self):
        """Buttons placed right after « Actualiser » (e.g. « Fiche »)."""
        return []

    def extra_actions(self):
        """Buttons placed before « Ajouter » (created here, wired by the page)."""
        return []

    def update_extra_actions(self, row):
        """Enable / explain the extra actions for the selected row (or None)."""

    def status_cell(self, row):
        return status_item(row.active, self.feminine)

    def fetch(self):
        raise NotImplementedError

    def cells(self, row):
        raise NotImplementedError

    def is_filtered(self):
        """Does a filter hide rows? (wording of the empty state)"""
        return bool(self.search.text().strip()) or self.status.currentData() != self.status_filters[0][1]

    def describe_row(self, row):
        """How a row is named in confirmations."""
        return f"{row.code} — {row.name}"

    # --- French agreement (une catégorie / un niveau) -------------------------
    @property
    def plural(self):
        return self.plural_noun or f"{self.noun}s"

    @property
    def a(self):
        return "une" if self.feminine else "un"

    @property
    def the(self):
        return "l'" if self.noun[:1] in "aeiouyéèh" else ("la " if self.feminine else "le ")

    @property
    def none(self):
        return "Aucune" if self.feminine else "Aucun"

    def agree(self, participle):
        """« créé » -> « créée » for a feminine noun."""
        return f"{participle}e" if self.feminine else participle

    # --- list -------------------------------------------------------------------
    def reload(self):
        self.call(self.fetch, self.show_rows, action=f"Impossible de charger les {self.plural}")

    def show_rows(self, rows):
        self.rows = rows
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(self.cells(row)):
                if self.columns[c] == STATUS_COLUMN_TITLE:
                    item = self.status_cell(row)
                elif isinstance(value, tuple):
                    value, key = value
                    item = SortableItem(value, key)
                else:
                    item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, row.id)
                if value and self.columns[c] != STATUS_COLUMN_TITLE:
                    item.setToolTip(value)
                self.table.setItem(r, c, item)
        self.table.setSortingEnabled(self.sortable)
        count = len(rows)
        self.count_label.setText(f"{count} {self.noun if count < 2 else self.plural}")
        filtered = self.is_filtered()
        self.empty.setText(
            f"{self.none} {self.noun} ne correspond à ces critères."
            if filtered
            else f"{self.none} {self.noun} pour le moment. Cliquez sur « Ajouter » pour en créer {self.a}."
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
        why = "" if row is not None else f"Sélectionnez d'abord {self.a} {self.noun} dans la liste."
        self.edit_button.setToolTip(why or "Modifier la ligne sélectionnée (Entrée)")
        self.toggle_button.setToolTip(why or ("Réactiver" if reactivate else "Désactiver (l'historique est conservé)"))
        self.add_button.setEnabled(not self.busy)
        self.update_extra_actions(row if not self.busy else None)

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
                f"« {self.describe_row(row)} » ne sera plus {self.agree('proposé')} dans les nouvelles "
                f"saisies. Son historique est conservé et vous pourrez {'la' if self.feminine else 'le'} "
                f"réactiver.\n\nLe serveur refusera la désactivation si {'elle' if self.feminine else 'il'} "
                f"est encore {self.agree('utilisé')}."
            )
            title = f"Désactiver {self.the}{self.noun} ?"
            if not self.confirm(self, title, text, confirm_text="Désactiver", danger=True):
                return
            self.call(
                lambda: self.deactivate(row.id),
                lambda saved: self._saved(saved, self.agree("désactivé")),
                action=f"Impossible de désactiver {self.the}{self.noun}",
            )
        else:
            self.call(
                lambda: self.reactivate(row.id),
                lambda saved: self._saved(saved, self.agree("réactivé")),
                action=f"Impossible de réactiver {self.the}{self.noun}",
            )

    def _saved(self, saved, verb):
        self.success(f"{self.noun.capitalize()} « {saved.code} » {verb} avec succès.")
        self.call(
            self.fetch,
            lambda rows: (self.show_rows(rows), self.select_id(saved.id)),
            action=f"Impossible de charger les {self.plural}",
        )
