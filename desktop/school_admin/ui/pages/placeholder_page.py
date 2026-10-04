"""Reserved place of a future module (nothing fake: just announced)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from ..widgets import Page


class PlaceholderPage(Page):
    def __init__(self, title, description, runner, parent=None):
        super().__init__(runner, parent)
        self.title = title
        heading = QLabel(title, objectName="pageTitle")
        text = QLabel(
            f"{description}\n\nCe module arrivera dans une prochaine version du poste d'administration.",
            objectName="muted",
        )
        text.setWordWrap(True)
        text.setAlignment(Qt.AlignTop)
        self.layout_.addWidget(heading)
        self.layout_.addWidget(text)
        self.layout_.addStretch()
