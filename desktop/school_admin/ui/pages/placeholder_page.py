"""Reserved place of a future module (nothing fake: just announced)."""

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from ..widgets import Page


class PlaceholderPage(Page):
    def __init__(self, title, description, runner, parent=None):
        super().__init__(runner, parent)
        self.title = title
        self.layout_.addWidget(QLabel(title, objectName="pageTitle"))
        card = QFrame(objectName="card")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(22, 20, 22, 20)
        heading = QLabel("Module prévu dans une prochaine version", objectName="cardLabel")
        text = QLabel(f"{description} Ces écrans ne sont pas encore disponibles sur le poste d'administration.")
        text.setWordWrap(True)
        inner.addWidget(heading)
        inner.addWidget(text)
        self.layout_.addWidget(card)
        self.layout_.addStretch()
