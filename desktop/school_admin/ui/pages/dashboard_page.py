"""Dashboard: real indicators from the API (services/dashboard.py)."""

from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout

from ..widgets import Page, button


class MetricCard(QFrame):
    def __init__(self, metric):
        super().__init__(objectName="card")
        self.setMinimumHeight(118)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(4)
        self.label = QLabel(metric.label, objectName="cardLabel")
        layout.addWidget(self.label)
        if metric.error:
            self.value = QLabel("Indisponible", objectName="cardError")
            detail = QLabel(metric.error, objectName="help")
        else:
            self.value = QLabel(metric.value or "—", objectName="cardValue")
            detail = QLabel(metric.hint, objectName="help")
        self.value.setWordWrap(True)
        detail.setWordWrap(True)
        layout.addWidget(self.value)
        layout.addWidget(detail)
        layout.addStretch()
        self.setAccessibleName(f"{metric.label} : {self.value.text()}")


class DashboardPage(Page):
    title = "Tableau de bord"

    def __init__(self, service, runner, parent=None, **kwargs):
        super().__init__(runner, parent, **kwargs)
        self.service = service
        top = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(2)
        self.heading = QLabel("Tableau de bord", objectName="pageTitle")
        self.subheading = QLabel("Vue d'ensemble de l'école, à partir des données du serveur.", objectName="subtitle")
        heading.addWidget(self.heading)
        heading.addWidget(self.subheading)
        top.addLayout(heading, 1)
        self.refresh_button = button("Actualiser", tooltip="Recharger les indicateurs (F5)")
        self.refresh_button.clicked.connect(self.reload)
        top.addWidget(self.refresh_button)
        self.layout_.addLayout(top)
        self.layout_.addWidget(self.banner)
        self.grid = QGridLayout()
        self.grid.setSpacing(16)
        self.layout_.addLayout(self.grid)
        self.layout_.addStretch()
        self.cards = []
        self.data = None

    def reload(self):
        self.call(self.service.load, self.show_data, action="Impossible de charger le tableau de bord")

    def set_busy(self, busy):
        super().set_busy(busy)
        self.refresh_button.setEnabled(not busy)

    def show_data(self, data):
        self.data = data
        parts = [v for v in (data.school_name, data.school_city) if v]
        if data.year_name:
            parts.append(f"année scolaire {data.year_name}")
        self.subheading.setText(" · ".join(parts))
        for card in self.cards:
            self.grid.removeWidget(card)
            card.deleteLater()
        self.cards = [MetricCard(metric) for metric in data.metrics]
        for index, card in enumerate(self.cards):
            self.grid.addWidget(card, index // 3, index % 3)
