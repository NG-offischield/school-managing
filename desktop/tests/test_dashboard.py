"""Tableau de bord: indicators and charts fed by the API only — data present,
no data, API errors, chart contents and tooltips, responsive layout."""

from datetime import UTC, datetime, timedelta

import pytest
from PySide6.QtCore import QSize
from PySide6.QtTest import QTest

from school_admin.config import AppConfig
from school_admin.models import Activity, ChartData, Point
from school_admin.services.dashboard import DashboardService, activity_text, money, relative_time
from school_admin.ui.app import AppController
from school_admin.ui.charts import BarChart, ChartCard, LineChart, nice_ceiling
from school_admin.ui.tasks import ImmediateRunner

from .fake_backend import PASSWORD, fail


@pytest.fixture
def service(logged_in, api):
    return DashboardService(api)


@pytest.fixture
def controller(qapp, api, auth):
    ctrl = AppController(api, auth, ImmediateRunner(), AppConfig(api_url="http://testserver/api/v1/"))
    yield ctrl
    if ctrl.main_window is not None:
        ctrl.main_window.close()
    ctrl.login_window.close()


def open_dashboard(ctrl):
    window = ctrl.login_window
    window.identifier.setText("admin")
    window.password.setText(PASSWORD)
    window.attempt()
    return ctrl.main_window, ctrl.main_window.pages["dashboard"]


# =============================================================================
# Service: only API values
# =============================================================================


def test_charts_from_the_api(service):
    charts = service.load_charts()
    attendance = charts.attendance
    assert attendance.series == ("Présents", "Absents") and attendance.unit == "%" and attendance.maximum == 100
    assert [p.label for p in attendance.points] == ["02/03", "03/03"]  # the day still PENDING is not a point
    assert attendance.points[0].values == (90.0, 10.0)  # (100 + 8) / 120, (10 + 2) / 120
    assert attendance.points[0].tooltip == (
        "Lundi 02/03 : 90 % présents (108 sur 120 élèves pointés) · 8 retards · 12 absents dont 2 justifiés"
    )
    assert [(p.label, p.values) for p in charts.by_level.points] == [("6E", (70,)), ("5E", (50,))]
    assert charts.by_level.points[0].tooltip == "Sixième (6E) : 70 élèves inscrits"
    assert charts.by_class.points[0].tooltip == "6e A : 38 élèves pour 40 places"
    assert [(p.label, p.values) for p in charts.enrollment_trend.points] == [
        ("sept. 25", (112,)),
        ("oct. 25", (118,)),
        ("nov. 25", (120,)),
    ]
    assert charts.enrollment_trend.points[0].tooltip == "Fin septembre 2025 : 112 élèves inscrits"
    assert charts.activity == [] and charts.activity_error is None


def test_finance_indicator(service, backend):
    values = {m.label: m for m in service.load().metrics}
    finance = values["Encaissements"]
    assert finance.value == "1 250 000 XAF"
    assert finance.hint == "reste à encaisser : 300 000 XAF · 2 factures en retard"
    backend.forced[("GET", "admin/finance/dashboard/")] = fail(403, "PERMISSION_DENIED", "Permission refusée.")
    assert {m.label: m for m in service.load().metrics}["Encaissements"].error == "Permission refusée."


def test_no_data_is_said_not_invented(service, backend):
    backend.attendance_days = []
    backend.enrollments = {"academic_year": None, "academic_year_name": "", "total": 0, "by_level": [], "by_class": []}
    charts = service.load_charts()
    assert charts.attendance.points == [] and charts.attendance.error is None
    assert charts.attendance.empty_text == "Aucune présence pointée sur les 14 derniers jours."
    for chart in (charts.by_level, charts.by_class, charts.enrollment_trend):
        assert chart.points == [] and chart.empty_text == "Aucune année scolaire courante n'est définie."
    backend.enrollments = {
        "academic_year": "y1",
        "academic_year_name": "2025-2026",
        "total": 0,
        "by_level": [],
        "by_class": [{"class": "c1", "name": "6e A", "level_code": "6E", "count": 0, "capacity": None}],
        "by_month": [{"month": "2025-09", "enrolled": 0}],
    }
    charts = service.load_charts()
    assert charts.by_class.points == [] and charts.by_class.empty_text == "Aucun élève inscrit en 2025-2026."
    assert charts.enrollment_trend.points == []  # a flat line of zeros is not shown as data


def test_api_errors_stay_inside_each_chart(service, backend):
    backend.forced[("GET", "admin/dashboard/attendance-trend/")] = fail(500, "SERVER_ERROR", "Erreur interne.")
    backend.forced[("GET", "admin/dashboard/enrollments/")] = fail(403, "PERMISSION_DENIED", "Permission refusée.")
    backend.forced[("GET", "admin/dashboard/activity/")] = fail(404, "NOT_FOUND", "Introuvable.")
    charts = service.load_charts()
    assert charts.attendance.error and charts.by_level.error == "Permission refusée."
    assert charts.by_class.error == charts.enrollment_trend.error == "Permission refusée."
    assert charts.activity_error == "Introuvable."


def test_formatting_helpers():
    assert money("1250000.00", "XAF") == "1 250 000 XAF"
    assert money("1250.50", "EUR") == "1 250,50 EUR"
    now = datetime(2026, 3, 4, 12, 0, tzinfo=UTC)
    assert relative_time(now - timedelta(seconds=20), now) == "à l'instant"
    assert relative_time(now - timedelta(minutes=5), now) == "il y a 5 min"
    assert relative_time(now - timedelta(hours=2), now) == "il y a 2 h"
    three_days_ago = now - timedelta(days=3)
    assert relative_time(three_days_ago, now) == three_days_ago.astimezone().strftime("%d/%m à %H:%M")
    title, detail, when = activity_text(Activity(now, "LEVEL_CREATED", "Level", "Sixième", "Ada Admin"), now)
    assert (title, detail, when) == ("Niveau créé", "Sixième", "à l'instant · Ada Admin")
    assert activity_text(Activity(None, "SOMETHING_NEW", "", "", ""))[0] == "SOMETHING_NEW"  # never hidden
    assert [nice_ceiling(v) for v in (0, 3, 7, 38, 72, 120, 999)] == [4, 4, 8, 40, 80, 120, 1000]


# =============================================================================
# Page
# =============================================================================


def test_dashboard_page_shows_indicators_and_charts(controller, backend):
    backend.log("LEVEL_CREATED", "Sixième")
    _, page = open_dashboard(controller)
    values = {card.label.text(): card.value.text() for card in page.cards}
    assert values["Encaissements"] == "1 250 000 XAF" and values["Classes"] == "4"
    assert [c.status for c in (page.attendance_card, page.enrollment_card, page.trend_card)] == ["data"] * 3
    assert page.attendance_card.chart.data.points[1].values == (round(110 / 120 * 100, 1), round(10 / 120 * 100, 1))
    assert "Présents" in page.attendance_card.legend.text() and "Absents" in page.attendance_card.legend.text()
    assert [p.label for p in page.enrollment_card.chart.data.points] == ["6E", "5E"]
    page.enrollment_card.switch[1].click()  # « Par classe »
    assert page.enrollment_card.current == 1
    assert [p.label for p in page.enrollment_card.chart.data.points] == ["6e A", "6e B", "5e A"]
    assert page.activity_card.status == "data" and len(page.activity_card.rows) == 1


def test_dashboard_page_empty_and_errors(controller, backend):
    backend.attendance_days = []
    backend.forced[("GET", "admin/dashboard/enrollments/")] = fail(500, "SERVER_ERROR", "Erreur interne du serveur.")
    _, page = open_dashboard(controller)
    assert page.attendance_card.status == "empty"
    assert page.attendance_card.state.text() == "Aucune présence pointée sur les 14 derniers jours."
    assert page.enrollment_card.status == "error" and page.enrollment_card.state.text().startswith("Indisponible — ")
    assert page.trend_card.status == "error"
    assert page.activity_card.status == "empty"
    assert page.activity_card.state.text() == "Aucune opération enregistrée pour le moment."


def test_dashboard_refresh_shows_new_data(controller, backend):
    _, page = open_dashboard(controller)
    backend.enrollments["by_level"].append({"level": "l4", "code": "4E", "name": "Quatrième", "count": 12})
    backend.log("CLASS_CREATED", "4e A")
    page.refresh_button.click()
    assert [p.label for p in page.enrollment_card.chart.data.points] == ["6E", "5E", "4E"]
    assert page.activity_card.status == "data"


@pytest.mark.parametrize(
    ("width", "kpi", "charts"),
    [(1366 - 256, 4, 2), (1280 - 256, 4, 2), (1024 - 256, 3, 1), (700, 2, 1)],
)
def test_dashboard_reflows_with_the_width(controller, width, kpi, charts):
    shell, page = open_dashboard(controller)
    shell.resize(QSize(width + 256, 720))
    shell.show()
    QTest.qWaitForWindowExposed(shell)
    page.arrange(width)
    assert (page.kpi_columns, page.chart_columns) == (kpi, charts)
    assert page.scroll.horizontalScrollBar().maximum() == 0 or width < 760  # no sideways scroll on real screens
    shell.close()


@pytest.mark.parametrize("size", [QSize(320, 200), QSize(640, 260), QSize(960, 360)])
def test_charts_redraw_to_any_size(qapp, size):
    data = ChartData(
        series=("Élèves",),
        points=[Point(f"Classe {i}", (i * 3,), f"Classe {i} : {i * 3} élèves") for i in range(1, 25)],
    )
    for chart in (LineChart(), BarChart()):
        chart.resize(size)
        chart.set_data(data)
        image = chart.grab()
        assert image.size() == size
        rect = chart.plot_rect()
        assert rect.width() > 0 and rect.height() > 0 and rect.right() <= size.width()
        assert chart.tooltip(0) == "Classe 1 : 3 élèves"
        assert chart.top == 80  # 72 rounded up to a readable axis


def test_chart_card_states(qapp):
    card = ChartCard("Présences", [("Présences", LineChart())])
    assert card.status == "loading" and card.state.text() == "Chargement…"
    card.set_data(ChartData(error="Permission refusée."))
    assert card.status == "error" and card.state.text() == "Indisponible — Permission refusée."
    card.set_data(ChartData(empty_text="Rien à afficher."))
    assert card.status == "empty" and card.state.text() == "Rien à afficher."
    card.set_data(ChartData(series=("A", "B"), points=[Point("x", (1, 2))], unit="%", maximum=100))
    assert card.status == "data" and card.stack.currentWidget() is card.chart


@pytest.mark.parametrize("token", ["chart_1", "chart_2", "chart_3"])
def test_chart_colours_are_visible_on_a_card(token):
    from school_admin.ui.theme import TOKENS, contrast_ratio

    assert contrast_ratio(getattr(TOKENS, token), TOKENS.card) >= 3  # WCAG 1.4.11 graphical objects


def test_attendance_indicator_is_a_rate_with_its_detail(service, backend):
    from .fake_backend import ok

    backend.forced[("GET", "admin/attendance/dashboard/")] = ok(
        {"counts": {"PRESENT": 90, "LATE": 6, "ABSENT": 3, "EXCUSED": 1, "PENDING": 20}}
    )
    metric = {m.label: m for m in service.load().metrics}["Présence aujourd'hui"]
    assert (metric.value, metric.hint) == ("96 %", "90 présents · 6 retards · 3 absents · 1 excusés")
    backend.forced[("GET", "admin/attendance/dashboard/")] = ok({"counts": {"PENDING": 20}})
    metric = {m.label: m for m in service.load().metrics}["Présence aujourd'hui"]
    assert metric.value == "—" and metric.hint.startswith("aucun élève pointé le ")
