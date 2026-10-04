"""Shared list screen of the catalogue: search, status filter, table,
add / edit / deactivate / reactivate actions."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
)

from ..widgets import Page

STATUS_FILTERS = [("Actives", True), ("Inactives", False), ("Toutes", None)]


class CatalogPage(Page):
    title = ""
    columns = []
    noun = ""  # "catégorie", "matière"

    def __init__(self, runner, parent=None, **kwargs):
        super().__init__(runner, parent, **kwargs)
        self.rows = []
        header = QHBoxLayout()
        header.addWidget(QLabel(self.title, objectName="pageTitle"))
        header.addStretch()
        self.count_label = QLabel("", objectName="muted")
        header.addWidget(self.count_label)
        self.layout_.addLayout(header)

        tools = QHBoxLayout()
        self.search = QLineEdit(placeholderText="Rechercher (code ou nom)…", clearButtonEnabled=True)
        self.status = QComboBox()
        for label, value in STATUS_FILTERS:
            self.status.addItem(label, value)
        tools.addWidget(self.search, 2)
        tools.addWidget(self.status)
        self.add_filters(tools)
        tools.addStretch()
        self.add_button = QPushButton("Ajouter", objectName="primary")
        self.edit_button = QPushButton("Modifier")
        self.toggle_button = QPushButton("Désactiver")
        self.refresh_button = QPushButton("Actualiser")
        for button in (self.add_button, self.edit_button, self.toggle_button, self.refresh_button):
            tools.addWidget(button)
        self.layout_.addLayout(tools)
        self.layout_.addWidget(self.banner)

        self.table = QTableWidget(0, len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.layout_.addWidget(self.table)

        self._debounce = QTimer(self, singleShot=True, interval=300, timeout=self.reload)
        self.search.textChanged.connect(lambda _: self._debounce.start())
        self.status.currentIndexChanged.connect(lambda _: self.reload())
        self.add_button.clicked.connect(self.add)
        self.edit_button.clicked.connect(self.edit)
        self.toggle_button.clicked.connect(self.toggle)
        self.refresh_button.clicked.connect(self.reload)
        self.table.itemSelectionChanged.connect(self._update_actions)
        self.table.doubleClicked.connect(lambda _: self.edit())
        self._update_actions()

    # --- to implement ---------------------------------------------------------
    def add_filters(self, layout):
        pass

    def fetch(self):
        raise NotImplementedError

    def cells(self, row):
        raise NotImplementedError

    # --- list -------------------------------------------------------------------
    def reload(self):
        self.call(self.fetch, self.show_rows)

    def show_rows(self, rows):
        self.rows = rows
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(self.cells(row)):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, row.id)
                self.table.setItem(r, c, item)
        self.table.setSortingEnabled(True)
        self.count_label.setText(f"{len(rows)} {self.noun}{'s' if len(rows) > 1 else ''}")
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
        self.edit_button.setEnabled(row is not None and not self.busy)
        self.toggle_button.setEnabled(row is not None and not self.busy)
        self.toggle_button.setText("Réactiver" if row is not None and not row.active else "Désactiver")
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
                f"Désactiver « {row.code} — {row.name} » ?\n\nElle ne sera plus proposée dans les "
                f"nouvelles saisies ; l'historique est conservé. Le serveur refusera si elle est encore utilisée."
            )
            if not self.confirm(self, f"Désactiver la {self.noun}", text):
                return
            self.call(lambda: self.deactivate(row.id), lambda saved: self._saved(saved, "désactivée"))
        else:
            self.call(lambda: self.reactivate(row.id), lambda saved: self._saved(saved, "réactivée"))

    def _saved(self, saved, verb):
        self.success(f"{self.noun.capitalize()} « {saved.code} » {verb}.")
        self.call(self.fetch, lambda rows: (self.show_rows(rows), self.select_id(saved.id)))
