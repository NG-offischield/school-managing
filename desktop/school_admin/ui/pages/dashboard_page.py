"""Dashboard: real indicators from the API (services/dashboard.py)."""

from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ..widgets import Page


class MetricCard(QFrame):
    def __init__(self, metric):
        super().__init__(objectName="card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.addWidget(QLabel(metric.label, objectName="muted"))
        if metric.error:
            self.value = QLabel("Indisponible", objectName="cardError")
            self.value.setToolTip(metric.error)
            layout.addWidget(self.value)
            detail = QLabel(metric.error, objectName="muted")
        else:
            self.value = QLabel(metric.value or "—", objectName="cardValue")
            self.value.setWordWrap(True)
            layout.addWidget(self.value)
            detail = QLabel(metric.hint, objectName="muted")
        detail.setWordWrap(True)
        layout.addWidget(detail)


class DashboardPage(Page):
    title = "Tableau de bord"

    def __init__(self, service, runner, parent=None, **kwargs):
        super().__init__(runner, parent, **kwargs)
        self.service = service
        top = QHBoxLayout()
        heading = QVBoxLayout()
        self.heading = QLabel("Tableau de bord", objectName="pageTitle")
        self.subheading = QLabel("", objectName="muted")
        heading.addWidget(self.heading)
        heading.addWidget(self.subheading)
        top.addLayout(heading)
        top.addStretch()
        self.refresh_button = QPushButton("Actualiser")
        self.refresh_button.clicked.connect(self.reload)
        top.addWidget(self.refresh_button)
        self.layout_.addLayout(top)
        self.layout_.addWidget(self.banner)
        self.grid = QGridLayout()
        self.grid.setSpacing(12)
        self.layout_.addLayout(self.grid)
        self.layout_.addStretch()
        self.cards = []
        self.data = None

    def reload(self):
        self.call(self.service.load, self.show_data)

    def set_busy(self, busy):
        super().set_busy(busy)
        self.refresh_button.setEnabled(not busy)

    def show_data(self, data):
        self.data = data
        self.subheading.setText(" — ".join(v for v in (data.school_name, data.school_city, data.year_name) if v))
        for card in self.cards:
            self.grid.removeWidget(card)
            card.deleteLater()
        self.cards = [MetricCard(metric) for metric in data.metrics]
        for index, card in enumerate(self.cards):
            self.grid.addWidget(card, index // 3, index % 3)
