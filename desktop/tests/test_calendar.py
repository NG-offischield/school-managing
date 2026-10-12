"""Date picker of the admin desktop (widgets.date_field): readable calendar
popup from the theme tokens — navigation bar, month / year, weekends, today
vs selected day — French locale and dd/MM/yyyy kept, dates untouched.

Regression guards for two defects seen on Windows: dark month/year text on
the primary-blue navigation bar (2.65:1), and day numbers elided to "…" by
the data-table cell padding leaking into the calendar's own table."""

import pytest
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QTableView, QToolButton, QWidget

from school_admin.ui.theme import TOKENS, build_stylesheet, contrast_ratio, style_calendar
from school_admin.ui.widgets import date_field

TODAY = QDate(2026, 10, 12)


@pytest.fixture
def field(qapp):
    widget = date_field()
    style_calendar(widget.calendarWidget(), today=TODAY)  # fixed "today" for the assertions
    widget.setDate(QDate(2026, 10, 15))
    yield widget
    widget.deleteLater()


def shown_calendar(field):
    calendar = field.calendarWidget()
    calendar.setSelectedDate(field.date())
    calendar.resize(calendar.sizeHint())
    calendar.show()
    calendar.repaint()
    return calendar


@pytest.mark.parametrize(
    ("foreground", "background"),
    [
        ("text", "panel"),  # month / year buttons on the navigation bar
        ("on_primary", "primary"),  # selected day
        ("calendar_today_text", "field"),  # today
        ("calendar_weekend", "field"),  # Saturday / Sunday
        ("text_secondary", "field"),  # weekday headers
        ("text_disabled", "field"),  # days of the previous / next month
    ],
)
def test_calendar_tokens_are_readable(foreground, background):
    assert contrast_ratio(getattr(TOKENS, foreground), getattr(TOKENS, background)) >= 4.5


def test_navigation_bar_is_painted_light_behind_dark_text(field):
    calendar = shown_calendar(field)
    bar = calendar.findChild(QWidget, "qt_calendar_navigationbar")
    image = calendar.grab().toImage()
    painted = image.pixelColor(bar.geometry().right() - 3, bar.geometry().center().y()).name()
    assert painted.lower() == TOKENS.panel.lower()  # no longer QPalette::Highlight (primary blue)
    assert contrast_ratio(TOKENS.text, painted) >= 4.5


def test_previous_and_next_buttons_are_visible_and_work(field):
    calendar = shown_calendar(field)
    for name in ("qt_calendar_prevmonth", "qt_calendar_nextmonth"):
        button = calendar.findChild(QToolButton, name)
        assert button.isVisibleTo(calendar) and not button.icon().isNull()
    calendar.findChild(QToolButton, "qt_calendar_nextmonth").click()
    assert (calendar.yearShown(), calendar.monthShown()) == (2026, 11)
    calendar.findChild(QToolButton, "qt_calendar_prevmonth").click()
    calendar.findChild(QToolButton, "qt_calendar_prevmonth").click()
    assert (calendar.yearShown(), calendar.monthShown()) == (2026, 9)
    calendar.setCurrentPage(2027, 1)  # year navigation
    assert (calendar.yearShown(), calendar.monthShown()) == (2027, 1)
    assert field.date() == QDate(2026, 10, 15)  # browsing never changes the date


def test_selecting_a_day_sets_the_field_date(field):
    calendar = shown_calendar(field)
    calendar.setSelectedDate(QDate(2026, 10, 20))
    calendar.clicked.emit(QDate(2026, 10, 20))  # what a click on a cell sends to the QDateEdit
    assert field.date() == QDate(2026, 10, 20)
    assert field.text() == "20/10/2026"


def test_selected_day_tile_is_solid_primary(field):
    calendar = shown_calendar(field)
    view = calendar.findChild(QTableView, "qt_calendar_calendarview")
    rect = view.visualRect(view.currentIndex())
    pixel = view.viewport().grab().toImage().pixelColor(rect.center().x(), rect.top() + 2).name()
    assert pixel.lower() == TOKENS.primary.lower()


def test_today_is_marked_and_distinct_from_the_selected_day(field):
    calendar = field.calendarWidget()
    today = calendar.dateTextFormat(TODAY)
    assert today.foreground().color().name().lower() == TOKENS.calendar_today_text.lower()
    assert today.fontWeight() >= 700 and today.fontUnderline()
    other = calendar.dateTextFormat(QDate(2026, 10, 13))
    assert not other.fontUnderline()  # only today
    assert TOKENS.calendar_today_text.lower() != TOKENS.on_primary.lower()


def test_weekends_and_headers_use_the_tokens_not_qt_red(field):
    calendar = field.calendarWidget()
    for day in (Qt.Saturday, Qt.Sunday):
        assert calendar.weekdayTextFormat(day).foreground().color().name().lower() == TOKENS.calendar_weekend.lower()
    assert calendar.weekdayTextFormat(Qt.Monday).foreground().color().name().lower() == TOKENS.text.lower()
    assert calendar.headerTextFormat().foreground().color().name().lower() == TOKENS.text_secondary.lower()


def test_french_locale_monday_first_and_format_kept(field):
    calendar = field.calendarWidget()
    assert calendar.locale().name() == "fr_FR"
    assert calendar.firstDayOfWeek() == Qt.Monday
    assert calendar.locale().monthName(10) == "octobre"
    assert field.displayFormat() == "dd/MM/yyyy" and field.text() == "15/10/2026"
    assert field.calendarPopup()


def test_calendar_cells_are_not_padded_like_data_tables():
    sheet = build_stylesheet()
    assert "QCalendarWidget QTableView::item { padding: 0; border: none; }" in sheet
    assert "QCalendarWidget QWidget#qt_calendar_navigationbar" in sheet


def test_popup_fits_small_screens(field):
    hint = field.calendarWidget().sizeHint()
    assert hint.width() <= 400 and hint.height() <= 320  # well inside 800x480
