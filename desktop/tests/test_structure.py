"""Gestion académique → Années scolaires / Niveaux: client services, pages,
dialogs, server rules (409 / 404 / 403), navigation, and the path
Année → Niveau → Classe → Tableau de bord with data created on screen."""

from datetime import date

import pytest
from PySide6.QtCore import QDate, QSize, Qt
from PySide6.QtTest import QTest

from school_admin.api.errors import Conflict, Forbidden, NotFound, ValidationFailed
from school_admin.config import AppConfig
from school_admin.models import AcademicYear, Level
from school_admin.services.structure import LevelService, YearService
from school_admin.ui.app import AppController
from school_admin.ui.dialogs.level_dialog import LevelDialog
from school_admin.ui.dialogs.year_dialog import YearDialog, suggested_dates
from school_admin.ui.tasks import ImmediateRunner

from .fake_backend import PASSWORD


@pytest.fixture
def years(logged_in, api):
    return YearService(api)


@pytest.fixture
def levels(logged_in, api):
    return LevelService(api)


# =============================================================================
# Client services
# =============================================================================


def test_years_list_create_update(years, backend):
    assert [y.name for y in years.list()] == ["2026-2027", "2025-2026", "2024-2025"]  # newest first
    assert [y.name for y in years.list(state="open")] == ["2026-2027", "2025-2026"]
    assert [y.name for y in years.list(state="closed")] == ["2024-2025"]
    current = next(y for y in years.list() if y.is_current)
    assert (current.start_date, current.end_date, current.class_count) == (date(2025, 9, 1), date(2026, 7, 31), 4)
    created = years.create(name="2027-2028", start_date=date(2027, 9, 1), end_date=date(2028, 7, 31))
    assert (created.status, created.is_current, created.class_count) == ("PLANNED", False, 0)
    edited = years.update(created.id, name="2027/2028", start_date=date(2027, 9, 1), end_date=date(2028, 7, 15))
    assert (edited.name, edited.end_date) == ("2027/2028", date(2028, 7, 15))
    assert ("PATCH", f"academic-years/{created.id}/") in backend.calls


def test_set_current_and_close(years, backend):
    planned = years.set_current("y2")
    assert (planned.is_current, planned.status) == (True, "ACTIVE")
    assert [y.name for y in years.list() if y.is_current] == ["2026-2027"]  # a single current year
    backend.years_with_pupils.clear()
    closed = years.close("y1")
    assert closed.status == "CLOSED" and not closed.open


def test_year_rules_are_the_servers(years, backend):
    with pytest.raises(ValidationFailed) as exc:  # incomplete: refused before any call
        years.create(name="", start_date=None, end_date=None)
    assert set(exc.value.field_errors()) == {"name", "start_date", "end_date"}
    calls = len(backend.calls)
    with pytest.raises(Conflict) as exc:
        years.create(name="2025-2026", start_date=date(2030, 9, 1), end_date=date(2031, 7, 31))
    assert exc.value.rule == "duplicate_year_name"
    with pytest.raises(Conflict) as exc:
        years.create(name="Chevauche", start_date=date(2026, 6, 1), end_date=date(2027, 6, 1))
    assert exc.value.rule == "year_overlap"
    with pytest.raises(Conflict) as exc:
        years.close("y1")
    assert exc.value.rule == "year_is_current"
    years.set_current("y2")
    with pytest.raises(Conflict) as exc:
        years.close("y1")
    assert exc.value.rule == "year_has_active_enrollments"
    with pytest.raises(ValidationFailed) as exc:
        years.set_current("y0")
    assert exc.value.rule == "year_closed"
    with pytest.raises(NotFound):  # another school's year: 404, like a missing one
        years.close("other-school-year")
    assert len(backend.calls) > calls


def test_levels_list_create_update_toggle(levels, backend):
    assert [lv.code for lv in levels.list()] == ["6E", "5E", "OLD"]  # in progression order
    assert [lv.code for lv in levels.list(active=True)] == ["6E", "5E"]
    assert levels.list(search="sixi")[0].class_count == 2
    created = levels.create(code="4e", name="Quatrième", cycle="COLLÈGE", order_index=3, first_character="4")
    assert (created.code, created.cycle, created.order_index, created.first_character) == ("4E", "COLLÈGE", 3, "4")
    edited = levels.update(created.id, name="4e (Quatrième)", cycle="COLLÈGE", order_index=3)
    assert edited.name == "4e (Quatrième)"
    assert [path for method, path in backend.calls if method == "PATCH"] == [f"levels/{created.id}/"]
    assert levels.deactivate(created.id).active is False
    assert levels.reactivate(created.id).active is True


def test_level_rules_are_the_servers(levels):
    with pytest.raises(ValidationFailed) as exc:
        levels.create(code="", name="")
    assert set(exc.value.field_errors()) == {"code", "name"}
    with pytest.raises(Conflict) as exc:
        levels.create(code="6e", name="Doublon")
    assert exc.value.rule == "duplicate_code"
    with pytest.raises(Conflict) as exc:
        levels.deactivate("l6")  # used by 6e A / 6e B of the current year
    assert exc.value.rule == "level_in_use"
    with pytest.raises(NotFound):
        levels.update("other-school-level", name="x")


def test_non_admin_cannot_write(years, levels, backend):
    backend.roles = ["TEACHER"]  # the role changed on the server after login
    assert [y.name for y in years.list()]  # reading is allowed
    with pytest.raises(Forbidden):
        years.set_current("y2")
    with pytest.raises(Forbidden):
        years.create(name="2030-2031", start_date=date(2030, 9, 1), end_date=date(2031, 7, 31))
    with pytest.raises(Forbidden):
        levels.create(code="CM1", name="Cours moyen 1")
    with pytest.raises(Forbidden):
        levels.deactivate("l5")


# =============================================================================
# Dialogs
# =============================================================================


def test_year_dialog_suggests_dates_and_name(qapp):
    existing = [AcademicYear("y1", "2025-2026", "ACTIVE", True, date(2025, 9, 1), date(2026, 7, 31))]
    start, end = suggested_dates(existing)
    assert (start, end) == (date(2026, 9, 1), date(2027, 7, 31))
    assert suggested_dates([], today=date(2026, 3, 10)) == (date(2025, 9, 1), date(2026, 7, 31))
    dialog = YearDialog(suggested=(start, end))
    assert (dialog.name.text(), dialog.save_enabled) == ("2026-2027", True)
    dialog.end.setDate(QDate(2028, 7, 31))
    assert dialog.name.text() == "2026-2028"  # follows the dates until the name is typed
    QTest.keyClicks(dialog.name, "x")
    dialog.end.setDate(QDate(2027, 7, 31))
    assert dialog.name.text() == "2026-2028x"
    dialog.end.setDate(QDate(2026, 8, 1))
    assert not dialog.save_enabled
    assert dialog.status.text() == "Pour enregistrer, complétez : une date de fin après la date de début."
    dialog.end.setDate(QDate(2027, 7, 31))
    dialog.name.clear()
    assert dialog.status.text() == "Pour enregistrer, complétez : Nom."
    dialog.name.setText("2026-2027")
    assert dialog.values() == {"name": "2026-2027", "start_date": date(2026, 9, 1), "end_date": date(2027, 7, 31)}


def test_year_dialog_edit_shows_state(qapp):
    year = AcademicYear("y2", "2026-2027", "PLANNED", False, date(2026, 9, 1), date(2027, 7, 31))
    dialog = YearDialog(year=year)
    assert dialog.windowTitle() == "Modifier l'année scolaire"
    assert dialog.start.date() == QDate(2026, 9, 1) and dialog.name.text() == "2026-2027"
    dialog.start.setDate(QDate(2026, 8, 25))
    assert dialog.name.text() == "2026-2027"  # an existing name is never rewritten


def test_level_dialog_fields_and_values(qapp):
    dialog = LevelDialog(cycles=["COLLÈGE", "LYCÉE"], next_order=3)
    assert dialog.order.text() == "3" and not dialog.save_enabled
    assert dialog.status.text() == "Pour enregistrer, complétez : Code, Nom."
    dialog.code.setText("4e")
    dialog.name.setText("Quatrième")
    dialog.cycle.setText("COLLÈGE")
    assert dialog.save_enabled
    assert dialog.values() == {
        "code": "4E",
        "name": "Quatrième",
        "cycle": "COLLÈGE",
        "order_index": 3,
        "first_character": "",
        "public_visible": False,
    }
    level = Level("l6", "6E", "Sixième", 1, True, "COLLÈGE", "6", True)
    edit = LevelDialog(level=level)
    assert edit.code.isReadOnly() and edit.prefix.text() == "6" and edit.public_visible.isChecked()


# =============================================================================
# Pages
# =============================================================================


@pytest.fixture
def controller(qapp, api, auth):
    ctrl = AppController(api, auth, ImmediateRunner(), AppConfig(api_url="http://testserver/api/v1/"))
    ctrl.confirmations = []
    ctrl.confirm_answer = True

    def confirm(_parent, title, text, **options):
        ctrl.confirmations.append((title, text, options))
        return ctrl.confirm_answer

    ctrl.page_options = {key: {"confirm": confirm} for key in ("years", "levels", "classes")}
    yield ctrl
    if ctrl.main_window is not None:
        ctrl.main_window.close()
    ctrl.login_window.close()


def open_page(ctrl, key):
    window = ctrl.login_window
    window.identifier.setText("admin")
    window.password.setText(PASSWORD)
    window.attempt()
    return ctrl.main_window, ctrl.main_window.open(key)


def column(page, index=0):
    return [page.table.item(r, index).text() for r in range(page.table.rowCount())]


def row_of(page, text, index=0):
    return column(page, index).index(text)


def test_navigation_order_and_shortcuts(controller):
    shell, _ = open_page(controller, "years")
    labels = [shell.nav.item(i).text() for i in range(shell.nav.count())]
    start = labels.index("GESTION ACADÉMIQUE")
    assert labels[start + 1 : start + 6] == [
        "Années scolaires",
        "Niveaux",
        "Catégories pédagogiques",
        "Matières",
        "Classes",
    ]
    shell.show()
    QTest.qWaitForWindowExposed(shell)
    shell.activateWindow()
    keys = ("dashboard", "years", "levels", "categories", "subjects", "classes")
    for index, key in enumerate(keys):
        QTest.keyClick(shell, Qt.Key(Qt.Key_1 + index), Qt.ControlModifier)  # Ctrl+1 … Ctrl+6
        assert shell.current_key == key and type(shell.current_page).__name__ != "PlaceholderPage"


def test_years_page_list_and_actions(controller):
    _, page = open_page(controller, "years")
    assert column(page) == ["2026-2027", "2025-2026", "2024-2025"]
    assert [page.table.horizontalHeaderItem(c).text() for c in range(5)] == [
        "Nom",
        "Début",
        "Fin",
        "Classes",
        "Statut",
    ]
    current = row_of(page, "2025-2026")
    assert page.table.item(current, 1).text() == "01/09/2025" and page.table.item(current, 3).text() == "4"
    assert page.table.item(current, 4).text() == "★  En cours · courante"
    assert not page.toggle_button.isVisible() or page.toggle_button.isHidden()
    page.table.selectRow(current)
    assert not page.current_button.isEnabled() and page.current_button.toolTip() == "C'est déjà l'année courante."
    assert not page.close_button.isEnabled()
    assert page.close_button.toolTip() == "Définissez d'abord une autre année comme courante."
    page.table.selectRow(row_of(page, "2024-2025"))  # closed
    assert not page.edit_button.isEnabled() and page.edit_button.toolTip() == "Cette année est clôturée."
    page.table.selectRow(row_of(page, "2026-2027"))
    assert page.current_button.isEnabled() and page.close_button.isEnabled() and page.edit_button.isEnabled()
    page.status.setCurrentIndex(2)  # Clôturées
    assert column(page) == ["2024-2025"]


def test_years_sort_by_date_not_text(controller):
    _, page = open_page(controller, "years")
    page.table.sortItems(1)
    assert column(page) == ["2024-2025", "2025-2026", "2026-2027"]


def test_year_create_set_current_close(controller, backend):
    _, page = open_page(controller, "years")
    page.open_dialog = lambda year=None: {
        "name": "2027-2028",
        "start_date": date(2027, 9, 1),
        "end_date": date(2028, 7, 31),
    }
    page.add()
    assert page.banner.plain_text() == "Année « 2027-2028 » créée avec succès."
    assert page.selected().name == "2027-2028" and page.selected().status == "PLANNED"
    page.set_current()
    title, text, options = controller.confirmations[-1]
    assert title == "Définir comme année courante ?" and "« 2027-2028 »" in text
    assert page.banner.plain_text() == "« 2027-2028 » est maintenant l'année courante."
    assert page.table.item(row_of(page, "2027-2028"), 4).text() == "★  En cours · courante"
    backend.years_with_pupils.clear()
    page.table.selectRow(row_of(page, "2025-2026"))
    page.close_year()
    title, text, options = controller.confirmations[-1]
    assert title == "Clôturer l'année scolaire ?" and options == {"confirm_text": "Clôturer", "danger": True}
    assert page.banner.plain_text() == "Année « 2025-2026 » clôturée."
    assert page.table.item(row_of(page, "2025-2026"), 4).text() == "○  Clôturée"


def test_year_conflicts_are_explained(controller, backend):
    _, page = open_page(controller, "years")
    page.open_dialog = lambda year=None: {
        "name": "Nouvelle",
        "start_date": date(2026, 6, 1),
        "end_date": date(2027, 6, 30),
    }
    page.add()
    assert page.banner.kind == "warning"
    assert page.banner.plain_text() == (
        "Impossible de créer l'année scolaire — Ces dates chevauchent une autre année scolaire de l'école : "
        "ajustez le début ou la fin."
    )
    page.table.selectRow(row_of(page, "2026-2027"))
    page.close_year()
    assert page.banner.plain_text() == "Année « 2026-2027 » clôturée."  # no pupils, not current
    page.table.selectRow(row_of(page, "2025-2026"))
    assert not page.close_button.isEnabled()  # the current year: explained, not sent
    page.table.selectRow(row_of(page, "2025-2026"))
    controller.confirm_answer = False
    calls = len(backend.calls)
    page.close_year()
    assert len(backend.calls) == calls  # cancelled: nothing sent


def test_levels_page_crud_and_in_use(controller, backend):
    _, page = open_page(controller, "levels")
    assert column(page, 1) == ["6E", "5E"]  # active ones, in progression order
    assert page.table.item(0, 4).text() == "2" and page.table.item(0, 5).text() == "●  Actif"
    assert page.count_label.text() == "2 niveaux"
    page.open_dialog = lambda level=None: {
        "code": "4E",
        "name": "Quatrième",
        "cycle": "COLLÈGE",
        "order_index": 3,
        "first_character": "4",
        "public_visible": False,
    }
    page.add()
    assert page.banner.plain_text() == "Niveau « 4E » créé avec succès."
    page.table.selectRow(row_of(page, "4E", 1))
    page.open_dialog = lambda level=None: {
        "code": level.code,
        "name": "4e — Quatrième",
        "cycle": "COLLÈGE",
        "order_index": 3,
        "first_character": "4",
        "public_visible": True,
    }
    page.edit()
    assert page.banner.plain_text() == "Niveau « 4E » modifié avec succès."
    page.table.selectRow(row_of(page, "4E", 1))
    page.toggle()
    title, text, options = controller.confirmations[-1]
    assert title == "Désactiver le niveau ?" and "ne sera plus proposé dans" in text
    assert page.banner.plain_text() == "Niveau « 4E » désactivé avec succès."
    page.table.selectRow(row_of(page, "6E", 1))
    page.toggle()
    assert page.banner.kind == "warning" and page.banner.plain_text() == (
        "Impossible de désactiver le niveau — Des classes actives d'une année ouverte utilisent ce niveau : "
        "il ne peut pas être désactivé."
    )
    page.status.setCurrentIndex(1)
    assert set(column(page, 1)) == {"OLD", "4E"}
    assert page.empty.text() == "Aucun niveau ne correspond à ces critères."


def test_year_level_class_dashboard_path(controller, backend):
    """Année scolaire → créer 2026-2027 courante, Niveaux → créer 6e,
    Classes → créer 6e A, Tableau de bord: everything comes from the screens."""
    backend.years = [y for y in backend.years if y["id"] != "y2"]
    shell, years = open_page(controller, "years")
    years.open_dialog = lambda year=None: {
        "name": "2026-2027",
        "start_date": date(2026, 9, 1),
        "end_date": date(2027, 7, 31),
    }
    years.add()
    years.set_current()
    levels = shell.open("levels")
    levels.open_dialog = lambda level=None: {
        "code": "6EBIS",
        "name": "Sixième bilingue",
        "cycle": "",
        "order_index": 1,
        "first_character": "6",
        "public_visible": False,
    }
    levels.add()
    classes = shell.open("classes")
    assert classes.year_filter.currentText() == "2026-2027 — année courante"
    offered = {}

    def create(references, school_class=None):
        year_list, level_list, _rooms, _regimes = references
        offered["years"] = [y.name for y in year_list]
        offered["levels"] = [lv.code for lv in level_list]
        new_year = next(y for y in year_list if y.name == "2026-2027")
        new_level = next(lv for lv in level_list if lv.code == "6EBIS")
        return {
            "name": "6e A",
            "academic_year_id": new_year.id,
            "level_id": new_level.id,
            "main_room_id": None,
            "capacity": 40,
            "public_visible": False,
        }

    classes.open_dialog = create
    classes.add()
    assert offered["years"][0] == "2026-2027" and "6EBIS" in offered["levels"]
    assert classes.banner.plain_text() == "Classe « 6e A » créée avec succès."
    assert column(classes) == ["6e A"]  # the only class of the new current year
    dashboard = shell.open("dashboard")
    values = {card.label.text(): card.value.text() for card in dashboard.cards}
    assert values["Année scolaire active"] == "2026-2027" and values["Classes"] == "1"
    titles = [row.findChildren(type(dashboard.activity_card.title))[0].text() for row in dashboard.activity_card.rows]
    assert titles[:3] == [
        "<b>Classe créée</b> · 6e A",
        "<b>Niveau créé</b> · Sixième bilingue",
        ("<b>Année courante définie</b> · 2026-2027"),
    ]


@pytest.mark.parametrize("size", [QSize(1366, 768), QSize(1280, 720)])
def test_years_toolbar_fits(controller, size):
    shell, page = open_page(controller, "years")
    shell.resize(size)
    shell.show()
    QTest.qWaitForWindowExposed(shell)
    buttons = [page.refresh_button, page.edit_button, page.current_button, page.close_button, page.add_button]
    for left, right in zip(buttons, buttons[1:], strict=False):
        assert left.isVisible() and left.geometry().right() < right.geometry().left()
    for widget in buttons:
        assert widget.width() >= widget.minimumSizeHint().width()
        assert page.rect().contains(widget.mapTo(page, widget.rect().bottomRight()))
    shell.close()
