"""Système / Clair / Sombre: the dark palette keeps the readability rules of the
light one (WCAG 2.1), a switch re-themes what is already open (palette, style
sheet, calendars, status colours, charts), the choice survives a restart
(desktop.json) and never destroys the rest of that file."""

import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QCalendarWidget, QLabel, QLineEdit

from school_admin.config import load_config, save_preference
from school_admin.ui.charts import series_colours
from school_admin.ui.dialogs.subject_dialog import SubjectDialog
from school_admin.ui.theme import (
    DARK,
    LIGHT,
    TOKENS,
    TokenColours,
    _asset,
    apply_theme,
    build_stylesheet,
    contrast_ratio,
    resolve_mode,
    theme_events,
)

from .test_communication_documents import controller  # noqa: F401 (fixture)
from .test_theme_dialogs import CATEGORIES, color, shown

PAIRS = [
    ("text", "panel", 4.5),
    ("text", "background", 4.5),
    ("text", "card", 4.5),
    ("text_secondary", "panel", 4.5),
    ("text_secondary", "background", 4.5),
    ("placeholder", "field", 4.5),
    ("text_disabled", "disabled_fill", 4.5),
    ("text_disabled", "field_disabled", 4.5),
    ("on_primary", "primary", 4.5),
    ("on_primary", "primary_hover", 4.5),
    ("on_primary", "primary_pressed", 4.5),
    ("on_primary", "danger", 4.5),
    ("danger", "panel", 4.5),
    ("primary", "panel", 4.5),  # selected tab, links
    ("error", "error_bg", 4.5),
    ("success", "success_bg", 4.5),
    ("warning", "warning_bg", 4.5),
    ("info", "info_bg", 4.5),
    ("success", "card", 4.5),  # status cells
    ("warning", "card", 4.5),
    ("text", "primary_soft", 4.5),
    ("text", "row_alt", 4.5),
    ("text", "header_section", 4.5),
    ("tooltip_text", "text", 4.5),  # tooltip: inverted
    ("sidebar_text", "sidebar", 4.5),
    ("sidebar_muted", "sidebar", 4.5),
    ("sidebar_text", "sidebar_hover", 4.5),
    ("calendar_weekend", "field", 4.5),
    ("calendar_today_text", "field", 4.5),
    ("field_border", "field", 3.0),
    ("field_border", "background", 3.0),
    ("focus", "field", 3.0),
    ("chart_1", "card", 3.0),
    ("chart_2", "card", 3.0),
    ("chart_3", "card", 3.0),
]


@pytest.fixture(autouse=True)
def without_leftover_windows(qapp):
    """A theme switch re-polishes EVERY widget of the application: windows left
    open by earlier test files (thousands of widgets) would make it crawl.
    The application itself only ever has a handful."""
    from PySide6.QtCore import QCoreApplication, QEvent

    for widget in qapp.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    yield


@pytest.fixture
def light_again(qapp):
    yield qapp
    apply_theme(qapp, "light")  # every other test expects the default light theme


@pytest.mark.parametrize("palette", [LIGHT, DARK], ids=["light", "dark"])
@pytest.mark.parametrize(("foreground", "background", "minimum"), PAIRS)
def test_both_palettes_meet_wcag(palette, foreground, background, minimum):
    ratio = contrast_ratio(getattr(palette, foreground), getattr(palette, background))
    assert ratio >= minimum, f"{palette.name}: {foreground} on {background}: {ratio:.2f}"


def test_dark_style_sheet_has_no_light_literal_left():
    sheet = build_stylesheet(DARK)
    # The former light literals are now tokens: the dark sheet uses the dark values.
    assert f"border-color: {DARK.error_border}" in sheet and "border-color: #FECACA" not in sheet
    assert f"border-bottom: 1px solid {DARK.row_line}" in sheet and "#EDF1F6" not in sheet
    assert f"QHeaderView::section {{ background: {DARK.header_section};" in sheet
    assert f"color: {DARK.tooltip_text}" in sheet and "#C3CCD7" not in sheet
    assert "chevron-down-dark.svg" in sheet and "check-dark.svg" in sheet
    assert "chevron-down-dark.svg" not in build_stylesheet(LIGHT)
    assert _asset("chevron-left.svg", LIGHT).endswith("/chevron-left.svg")


def test_switching_rethemes_open_windows_calendars_and_colours(light_again):
    app = light_again
    status = TokenColours(PUBLISHED="success")
    dialog = shown(SubjectDialog(CATEGORIES))
    calendar = QCalendarWidget()
    events = []
    theme_events().changed.connect(events.append)
    assert status.get("PUBLISHED") == LIGHT.success and series_colours()[0] == LIGHT.chart_1

    apply_theme(app, "dark")
    QTest.qWait(10)
    assert app.property("theme_mode") == "dark" and app.property("theme_name") == "dark"
    assert app.palette().color(QPalette.Window).name() == DARK.background.lower()
    assert TOKENS.text == DARK.text and status.get("PUBLISHED") == DARK.success
    assert series_colours() == (DARK.chart_1, DARK.chart_2, DARK.chart_3)
    background = color(dialog, QPalette.Window)
    assert contrast_ratio(background, "#FFFFFF") > 10  # the OPEN dialog turned dark
    for label in [lbl for lbl in dialog.findChildren(QLabel) if lbl.isVisible() and lbl.text().strip()]:
        assert contrast_ratio(color(label, QPalette.WindowText), background) >= 4.5, label.text()
    for field in dialog.findChildren(QLineEdit):
        assert contrast_ratio(color(field, QPalette.Text), color(field, QPalette.Base)) >= 4.5
    weekend = calendar.weekdayTextFormat(Qt.Saturday).foreground().color().name()
    assert weekend == DARK.calendar_weekend.lower()  # existing calendars restyled

    apply_theme(app, "light")
    assert events == ["dark", "light"]
    assert color(dialog, QPalette.Window) == LIGHT.panel.lower()
    assert calendar.weekdayTextFormat(Qt.Saturday).foreground().color().name() == LIGHT.calendar_weekend.lower()
    theme_events().changed.disconnect(events.append)
    dialog.close()
    calendar.deleteLater()


def test_system_mode_follows_windows(light_again, monkeypatch):
    # Offscreen Qt has no colour scheme: the Windows answer is substituted.
    from school_admin.ui import theme

    monkeypatch.setattr(theme, "system_prefers_dark", lambda app=None: True)
    assert resolve_mode("system", light_again) is DARK
    apply_theme(light_again, "system")
    assert light_again.property("theme_mode") == "system" and light_again.property("theme_name") == "dark"
    monkeypatch.setattr(theme, "system_prefers_dark", lambda app=None: False)
    assert resolve_mode("system", light_again) is LIGHT
    assert resolve_mode("light") is LIGHT and resolve_mode("dark") is DARK and resolve_mode("bogus") is LIGHT


def test_preference_survives_a_restart_and_keeps_the_other_settings(tmp_path):
    (tmp_path / "desktop.json").write_text(json.dumps({"api_url": "http://serveur.test:8000/api/v1/"}), "utf-8")
    assert load_config(env={}, directory=tmp_path).theme == "system"  # default
    assert save_preference("theme", "dark", directory=tmp_path)
    config = load_config(env={}, directory=tmp_path)
    assert config.theme == "dark" and config.api_url == "http://serveur.test:8000/api/v1/"
    (tmp_path / "desktop.json").write_text("{not json", "utf-8")
    assert not save_preference("theme", "light", directory=tmp_path)
    assert (tmp_path / "desktop.json").read_text("utf-8") == "{not json"  # never overwritten
    (tmp_path / "desktop.json").write_text(json.dumps({"theme": "purple"}), "utf-8")
    assert load_config(env={}, directory=tmp_path).theme == "system"


def test_account_dialog_applies_and_keeps_the_choice(controller, backend, tmp_path, light_again):  # noqa: F811
    from .test_communication_documents import open_module

    controller.config_directory = tmp_path
    shell, page = open_module(controller, "dashboard")
    reloads = []
    page.reload = lambda: reloads.append("dashboard")
    dialog = controller.account_dialog()
    assert dialog.theme.isEnabled() and dialog.theme.currentData() in ("system", "light", "dark")
    dialog.theme.setCurrentIndex(dialog.theme.findData("dark"))
    assert light_again.property("theme_mode") == "dark" and TOKENS.name == "dark"
    assert dialog.banner.plain_text() == "Thème : Sombre."
    assert reloads == ["dashboard"]  # open pages refresh their coloured cells
    assert load_config(env={}, directory=tmp_path).theme == "dark"  # survives a restart
    assert controller.account_dialog().theme.currentData() == "dark"
    dialog.close()


SPECIAL_SURFACES = {"avatar", "schoolCode", "banner", "legendChip", "brand", "brandSub"}


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_every_module_is_readable_in_both_themes(controller, backend, light_again, mode):  # noqa: F811
    """Real rendering: each module opened at 1280x720 in the theme; every
    visible text (outside the dark sidebar and the coloured chips, which have
    their own pairs) keeps 4.5:1 against the page and card surfaces."""
    from PySide6.QtCore import QSize

    from school_admin.ui.navigation import NAVIGATION

    from .test_communication_documents import open_module

    apply_theme(light_again, mode)
    shell, _ = open_module(controller, "dashboard")
    shell.resize(QSize(1280, 720))
    shell.show()
    QTest.qWaitForWindowExposed(shell)
    sidebar = shell.findChild(QLabel.__base__, "sidebar")
    checked = set()
    for entry in [e for e in NAVIGATION if e.available]:
        page = shell.open(entry.key)
        QTest.qWait(5)
        for label in page.findChildren(QLabel):
            if not label.isVisible() or not label.text().strip() or label.objectName() in SPECIAL_SURFACES:
                continue
            if sidebar is not None and sidebar.isAncestorOf(label):
                continue
            foreground = color(label, QPalette.WindowText)
            checked.add(entry.key)
            for surface in (TOKENS.background, TOKENS.panel):
                ratio = contrast_ratio(foreground, surface)
                assert ratio >= 4.5, f"{mode} {entry.key}: {label.objectName() or label.text()[:30]!r} {ratio:.2f}"
        assert page.isVisible(), entry.key
    assert len(checked) >= 12, sorted(checked)  # not vacuous: texts were checked in (nearly) every module
    assert shell.palette().color(QPalette.Window).name() == TOKENS.background.lower()
    shell.close()
