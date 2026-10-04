"""Dashboard: real indicators and charts from the API (services/dashboard.py).

    Tableau de bord                                          [Actualiser]
    École · ville · année scolaire
    ┌ KPI ┐ ┌ KPI ┐ ┌ KPI ┐ ┌ KPI ┐        4 per row (3, then 2 when narrow)
    ┌ Présences (14 jours) ──┐ ┌ Élèves par niveau | classe ┐   2 per row
    ┌ Évolution des effectifs ┐ ┌ Activité récente ─────────┐   (1 when narrow)

The page scrolls vertically (1366×768, 1280×720); each chart has its own
state (loading, data, no data, error) and redraws to its size.
"""

from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from ...models import ChartData
from ...services.dashboard import activity_text
from ..charts import ActivityCard, BarChart, ChartCard, LineChart
from ..widgets import Page, button

NO_ANSWER = "le serveur n'a pas répondu."


class MetricCard(QFrame):
    def __init__(self, metric):
        super().__init__(objectName="card")
        self.setMinimumHeight(112)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
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
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea(objectName="pageScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget(objectName="dashboardContent")
        self.scroll.setWidget(content)
        self.layout_.addWidget(self.scroll)
        column = QVBoxLayout(content)
        column.setContentsMargins(28, 22, 28, 22)
        column.setSpacing(16)

        top = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(2)
        self.heading = QLabel("Tableau de bord", objectName="pageTitle")
        self.subheading = QLabel("Vue d'ensemble de l'école, à partir des données du serveur.", objectName="subtitle")
        self.subheading.setWordWrap(True)
        heading.addWidget(self.heading)
        heading.addWidget(self.subheading)
        top.addLayout(heading, 1)
        self.refresh_button = button("Actualiser", tooltip="Recharger les indicateurs (F5)")
        self.refresh_button.clicked.connect(self.reload)
        top.addWidget(self.refresh_button)
        column.addLayout(top)
        column.addWidget(self.banner)

        self.grid = QGridLayout()
        self.grid.setSpacing(16)
        column.addLayout(self.grid)

        self.attendance_card = ChartCard("Présences", [("Présences", LineChart())])
        self.enrollment_card = ChartCard(
            "Répartition des élèves", [("Par niveau", BarChart()), ("Par classe", BarChart())]
        )
        self.trend_card = ChartCard("Évolution des effectifs", [("Effectifs", LineChart())])
        self.activity_card = ActivityCard()
        self.chart_cards = [self.attendance_card, self.enrollment_card, self.trend_card]
        self.chart_grid = QGridLayout()
        self.chart_grid.setSpacing(16)
        column.addLayout(self.chart_grid)
        column.addStretch()
        self.cards = []
        self.data = None
        self.charts = None
        self.kpi_columns = self.chart_columns = 0
        self.arrange(self.width())

    # --- responsive layout -------------------------------------------------------------
    @staticmethod
    def columns_for(width):
        """(indicators per row, charts per row) for a page `width` wide."""
        kpi = 4 if width >= 1000 else (3 if width >= 760 else 2)
        return kpi, 2 if width >= 900 else 1

    def arrange(self, width):
        kpi, charts = self.columns_for(width)
        if kpi != self.kpi_columns:
            self.kpi_columns = kpi
            self._place(self.grid, self.cards, kpi)
        if charts != self.chart_columns:
            self.chart_columns = charts
            self._place(self.chart_grid, [*self.chart_cards, self.activity_card], charts)

    @staticmethod
    def _place(grid, widgets, columns):
        for widget in widgets:
            grid.removeWidget(widget)
        for index, widget in enumerate(widgets):
            grid.addWidget(widget, index // columns, index % columns)
        for col in range(4):
            grid.setColumnStretch(col, 1 if col < columns else 0)

    def resizeEvent(self, event):
        self.arrange(event.size().width())
        super().resizeEvent(event)

    # --- data -------------------------------------------------------------------------------
    def reload(self):
        for card in (*self.chart_cards, self.activity_card):
            card.set_loading()
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
        self.kpi_columns = 0
        self.arrange(self.width())
        self.call(self.service.load_charts, self.show_charts, action="Impossible de charger les graphiques")

    def show_charts(self, charts):
        self.charts = charts
        self.attendance_card.set_data(charts.attendance)
        self.enrollment_card.set_data(charts.by_level, charts.by_class)
        self.trend_card.set_data(charts.enrollment_trend)
        if charts.activity_error:
            self.activity_card.set_error(charts.activity_error)
        else:
            self.activity_card.set_items([activity_text(a) for a in charts.activity])

    def handle_error(self, exc, action=None):
        super().handle_error(exc, action)
        # Never leave « Chargement… » on screen after a failure.
        for card in self.chart_cards:
            if card.status == "loading":
                card.set_data(*[ChartData(error=NO_ANSWER)] * len(card.views))
        if self.activity_card.status == "loading":
            self.activity_card.set_error(NO_ANSWER)
