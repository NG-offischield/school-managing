"""Admin shell: sidebar navigation, header (school, user, logout), pages."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .navigation import NAVIGATION
from .pages.placeholder_page import PlaceholderPage


class MainWindow(QMainWindow):
    logout_requested = Signal()
    session_expired = Signal()

    def __init__(self, identity, page_factories, runner, parent=None):
        super().__init__(parent)
        self.identity = identity
        self.setWindowTitle(f"Administration — {identity.school_name}")
        self.resize(1200, 760)

        sidebar = QFrame(objectName="sidebar")
        sidebar.setFixedWidth(240)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 0, 0, 12)
        side.addWidget(QLabel("Administration", objectName="brand"))
        self.nav = QListWidget()
        side.addWidget(self.nav)

        header = QFrame(objectName="header")
        top = QHBoxLayout(header)
        top.setContentsMargins(20, 10, 20, 10)
        self.school_label = QLabel(f"<b>{identity.school_name}</b>  ·  {identity.school_code}")
        self.user_label = QLabel(f"{identity.full_name} — {identity.role_label}", objectName="muted")
        self.logout_button = QPushButton("Se déconnecter")
        self.logout_button.clicked.connect(self.logout_requested.emit)
        top.addWidget(self.school_label)
        top.addStretch()
        top.addWidget(self.user_label)
        top.addWidget(self.logout_button)

        self.stack = QStackedWidget()
        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(header)
        column.addWidget(self.stack)

        root = QWidget()
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(sidebar)
        row.addWidget(content)
        self.setCentralWidget(root)

        self.pages = {}
        section = None
        for entry in NAVIGATION:
            if entry.section and entry.section != section:
                section = entry.section
                title = QListWidgetItem(section.upper())
                title.setFlags(Qt.NoItemFlags)
                self.nav.addItem(title)
            label = entry.label if entry.available else f"{entry.label}  (bientôt)"
            item = QListWidgetItem(("    " if entry.section else "") + label)
            item.setData(Qt.UserRole, entry.key)
            if entry.available and entry.key in page_factories:
                page = page_factories[entry.key]()
                page.session_expired.connect(self.session_expired.emit)
            else:
                page = PlaceholderPage(entry.label, entry.description, runner)
                item.setForeground(Qt.gray)
            self.pages[entry.key] = page
            self.stack.addWidget(page)
            self.nav.addItem(item)
        self.nav.currentItemChanged.connect(self._navigate)
        self.open("dashboard")

    def _navigate(self, item, _previous=None):
        key = item.data(Qt.UserRole) if item else None
        if key in self.pages:
            page = self.pages[key]
            self.stack.setCurrentWidget(page)
            page.activate()

    def open(self, key):
        for index in range(self.nav.count()):
            item = self.nav.item(index)
            if item.data(Qt.UserRole) == key:
                self.nav.setCurrentItem(item)
                return self.pages[key]
        return None

    @property
    def current_page(self):
        return self.stack.currentWidget()
