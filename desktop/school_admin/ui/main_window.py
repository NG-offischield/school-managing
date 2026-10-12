"""Admin shell: sidebar navigation, header (school, user, logout), pages.

Sidebar: sections in small capitals, the active entry highlighted (filled
background + white bar), modules not yet available kept readable but
secondary with a "Bientôt" mention. Header: school name + code chip on the
left, the connected user (initials, name, role) and "Se déconnecter" on the
right. Ctrl+1 … Ctrl+9 open Tableau de bord / Années scolaires / Niveaux /
Catégories / Matières / Classes / Élèves / Enseignants / Cours.
"""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QKeySequence, QShortcut
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

from ..i18n import tr
from .branding import SOFTWARE_NAME, SOFTWARE_TAGLINE, brand_mark, software_icon
from .navigation import NAVIGATION
from .pages.placeholder_page import PlaceholderPage
from .theme import TOKENS, TYPE, theme_events
from .widgets import button


def initials(full_name):
    parts = [p for p in full_name.split() if p]
    return "".join(p[0] for p in parts[:2]).upper() or "?"


class MainWindow(QMainWindow):
    logout_requested = Signal()
    account_requested = Signal()
    session_expired = Signal()

    def __init__(self, identity, page_factories, runner, parent=None):
        super().__init__(parent)
        self.identity = identity
        self.setWindowTitle(f"{tr(SOFTWARE_NAME)} — {identity.school_name}")
        self.setWindowIcon(software_icon())
        self.setMinimumSize(1100, 640)
        self.resize(1280, 800)

        # --- sidebar ---
        sidebar = QFrame(objectName="sidebar")
        sidebar.setFixedWidth(256)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 0, 0, 12)
        side.setSpacing(0)
        # The SOFTWARE's identity (School Managing); the school's name is in the header.
        self.brand = brand_mark("compact", 32, object_name="brand")
        side.addWidget(self.brand)
        side.addWidget(QLabel(tr(SOFTWARE_TAGLINE), objectName="brandSub"))
        self.nav = QListWidget()
        self.nav.setAccessibleName(tr("Navigation"))
        self.nav.setSpacing(1)
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        side.addWidget(self.nav)
        self.about_button = QPushButton(tr("À propos de {0}", SOFTWARE_NAME), objectName="aboutLink")
        self.about_button.setCursor(Qt.PointingHandCursor)
        self.about_button.clicked.connect(self.show_about)
        side.addWidget(self.about_button)

        # --- header ---
        header = QFrame(objectName="header")
        header.setFixedHeight(68)
        top = QHBoxLayout(header)
        top.setContentsMargins(28, 10, 20, 10)
        top.setSpacing(12)
        self.school_label = QLabel(identity.school_name, objectName="schoolName")
        self.school_code = QLabel(identity.school_code, objectName="schoolCode")
        self.school_code.setToolTip(tr("Code de l'école"))
        self.school_code.setFixedHeight(24)
        top.addWidget(self.school_label)
        top.addWidget(self.school_code, 0, Qt.AlignVCenter)
        top.addStretch()
        avatar = QLabel(initials(identity.full_name), objectName="avatar", alignment=Qt.AlignCenter)
        avatar.setFixedSize(36, 36)
        who = QVBoxLayout()
        who.setSpacing(0)
        self.user_label = QLabel(identity.full_name, objectName="userName")
        self.role_label = QLabel(f"{identity.role_label} · {identity.username}", objectName="userRole")
        who.addWidget(self.user_label)
        who.addWidget(self.role_label)
        self.account_button = button(
            tr("Mon compte"), "secondary", tooltip=tr("Coordonnées, photo, mot de passe, appareils connectés")
        )
        self.account_button.clicked.connect(self.account_requested.emit)
        self.logout_button = button(tr("Se déconnecter"), tooltip=tr("Fermer la session sur ce poste"))
        top.addWidget(avatar)
        top.addLayout(who)
        top.addSpacing(8)
        top.addWidget(self.account_button)
        top.addWidget(self.logout_button)
        self.logout_button.clicked.connect(self.logout_requested.emit)

        self.stack = QStackedWidget()
        content = QWidget()
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(header)
        column.addWidget(self.stack, 1)

        root = QWidget()
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(sidebar)
        row.addWidget(content, 1)
        self.setCentralWidget(root)

        self.pages = {}
        theme_events().changed.connect(self.refresh_theme)
        self._theme_connected = True
        self._build_navigation(page_factories, runner)
        self.nav.currentItemChanged.connect(self._navigate)
        shortcuts = (
            "dashboard",
            "years",
            "levels",
            "categories",
            "subjects",
            "classes",
            "students",
            "teachers",
            "courses",
        )
        for index, key in enumerate(shortcuts, start=1):
            QShortcut(QKeySequence(f"Ctrl+{index}"), self, activated=lambda k=key: self.open(k))
        self.open("dashboard")

    def refresh_theme(self, _name=None):
        """A theme switch: the style sheet already re-themed the widgets; pages
        reload so the colours they put in table cells follow too."""
        if not self.isVisible():
            return
        for page in self.pages.values():
            page.reload()

    def closeEvent(self, event):
        # A closed shell (logout, session expiry) never reacts to a theme switch again.
        if self._theme_connected:  # closed twice (logout then quit): disconnect once only
            self._theme_connected = False
            theme_events().changed.disconnect(self.refresh_theme)
        super().closeEvent(event)

    def show_about(self):
        from .dialogs.about_dialog import AboutDialog

        AboutDialog(self).exec()

    def _build_navigation(self, page_factories, runner):
        section = None
        section_font = QFont()
        section_font.setPointSizeF(TYPE.section)
        section_font.setWeight(QFont.DemiBold)
        section_font.setLetterSpacing(QFont.PercentageSpacing, 112)
        soon_brush = QBrush(QColor(TOKENS.sidebar_muted))
        for entry in NAVIGATION:
            if entry.section and entry.section != section:
                section = entry.section
                title = QListWidgetItem(tr(section).upper())
                title.setFlags(Qt.NoItemFlags)  # not selectable, not focusable
                title.setFont(section_font)
                title.setForeground(soon_brush)
                title.setSizeHint(QSize(0, 34))
                self.nav.addItem(title)
            available = entry.available and entry.key in page_factories
            label = tr(entry.label)  # NAVIGATION holds the French sources
            item = QListWidgetItem(label if available else tr("{0}   ·  Bientôt", label))
            item.setData(Qt.UserRole, entry.key)
            item.setSizeHint(QSize(0, 38))
            if available:
                page = page_factories[entry.key]()
                page.session_expired.connect(self.session_expired.emit)
                item.setToolTip(label)
            else:
                page = PlaceholderPage(label, tr(entry.description), runner)
                item.setForeground(soon_brush)
                item.setToolTip(tr("{0} : module prévu dans une prochaine version", label))
            self.pages[entry.key] = page
            self.stack.addWidget(page)
            self.nav.addItem(item)

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
    def current_key(self):
        item = self.nav.currentItem()
        return item.data(Qt.UserRole) if item else None

    @property
    def current_page(self):
        return self.stack.currentWidget()
