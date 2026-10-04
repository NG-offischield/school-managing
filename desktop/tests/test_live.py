"""End-to-end against a REAL running backend (opt-in: `pytest -m live`).

Required environment (never committed):
    SCHOOL_ADMIN_E2E_URL        e.g. http://127.0.0.1:8000/api/v1/
    SCHOOL_ADMIN_E2E_USER       the SUPER_ADMIN created by `manage.py bootstrap_school`
    SCHOOL_ADMIN_E2E_PASSWORD   its password (environment only)

Runs the vertical through the real screens (headless): login -> dashboard ->
categories -> add category -> subjects -> add subject with that category ->
years -> add a year, make it current -> levels -> add a level ->
classes -> add a class in that year and level, edit / deactivate / reactivate
-> dashboard charts -> level still used (409) -> previous current year
restored, test year closed -> logout.
Codes and dates are random so the test can be replayed; it creates a few
rows. Run it against a TEST backend (it switches the current year, then
restores it).
"""

import os
import secrets
import uuid
from datetime import date

import pytest
from PySide6.QtWidgets import QApplication

from school_admin.api import ApiClient
from school_admin.auth.session import AuthService
from school_admin.auth.token_store import MemoryTokenStore
from school_admin.config import AppConfig
from school_admin.ui.app import AppController
from school_admin.ui.dialogs.class_dialog import ClassDialog
from school_admin.ui.dialogs.subject_dialog import SubjectDialog
from school_admin.ui.tasks import ImmediateRunner

from .conftest import DEVICE

pytestmark = pytest.mark.live
URL = os.environ.get("SCHOOL_ADMIN_E2E_URL", "")
USER = os.environ.get("SCHOOL_ADMIN_E2E_USER", "")
PASSWORD = os.environ.get("SCHOOL_ADMIN_E2E_PASSWORD", "")


@pytest.fixture
def live():
    if not (URL and USER and PASSWORD):
        pytest.fail("Set SCHOOL_ADMIN_E2E_URL, SCHOOL_ADMIN_E2E_USER and SCHOOL_ADMIN_E2E_PASSWORD.")
    app = QApplication.instance() or QApplication([])
    api = ApiClient(URL)
    auth = AuthService(api, DEVICE, persistent_store=MemoryTokenStore())
    controller = AppController(api, auth, ImmediateRunner(), AppConfig(api_url=URL))
    yield controller
    controller.login_window.close()
    api.close()
    assert app is not None


def test_full_vertical_against_the_real_backend(live):
    suffix = uuid.uuid4().hex[:5].upper()
    window = live.login_window
    window.identifier.setText(USER)
    window.password.setText(PASSWORD)
    window.attempt()
    shell = live.main_window
    assert shell is not None, window.banner.text()

    dashboard = shell.pages["dashboard"]
    assert dashboard.data is not None and dashboard.data.school_name
    labels = [card.findChild(type(card.value)).text() for card in dashboard.cards]
    assert "Élèves" in labels and "Enseignants" in labels

    categories = shell.open("categories")
    categories.open_dialog = lambda category=None: {
        "code": f"E2E{suffix}",
        "name": f"Catégorie E2E {suffix}",
        "description": "Créée par le test de bout en bout du poste d'administration.",
    }
    categories.add()
    assert categories.banner.kind == "success", categories.banner.text()
    assert f"E2E{suffix}" in [categories.table.item(r, 0).text() for r in range(categories.table.rowCount())]

    subjects = shell.open("subjects")

    def fill(available, subject=None):
        dialog = SubjectDialog(available)
        dialog.code.setText(f"S{suffix}")
        dialog.name.setText(f"Matière E2E {suffix}")
        assert not dialog.save_enabled  # no category yet
        dialog.category.setCurrentIndex(dialog.category.findText(f"E2E{suffix} — Catégorie E2E {suffix}"))
        assert dialog.save_enabled
        return dialog.values()

    subjects.open_dialog = fill
    subjects.add()
    assert subjects.banner.kind == "success", subjects.banner.text()
    rows = {
        subjects.table.item(r, 0).text(): subjects.table.item(r, 2).text() for r in range(subjects.table.rowCount())
    }
    assert rows[f"S{suffix}"] == f"E2E{suffix} — Catégorie E2E {suffix}"

    # --- Années scolaires: a far-future year (no overlap), made current ---
    years = shell.open("years")
    previous_current = next((y for y in years.rows if y.is_current), None)
    first = 2200 + secrets.randbelow(700)
    years.open_dialog = lambda year=None: {
        "name": f"{first}-{first + 1}" if year is None else f"{first}/{first + 1}",
        "start_date": date(first, 9, 1),
        "end_date": date(first + 1, 7, 31),
    }
    years.add()
    assert years.banner.kind == "success", years.banner.plain_text()
    assert years.selected().name == f"{first}-{first + 1}" and years.selected().status == "PLANNED"
    years.edit()
    assert years.banner.kind == "success", years.banner.plain_text()
    years.confirm = lambda *args, **kwargs: True
    years.set_current()
    assert years.selected().is_current and years.selected().status == "ACTIVE", years.banner.plain_text()
    new_year = years.selected()

    # --- Niveaux ---
    levels = shell.open("levels")
    levels.open_dialog = lambda level=None: {
        "code": f"N{suffix}",
        "name": f"Niveau E2E {suffix}",
        "cycle": "E2E",
        "order_index": 90,
        "first_character": "",
        "public_visible": False,
    }
    levels.add()
    assert levels.banner.plain_text() == f"Niveau « N{suffix} » créé avec succès."

    # --- Classes: in the new year and level, both created on screen ---
    classes = shell.open("classes")
    assert classes.year_filter.currentData() == new_year.id  # the new current year by default

    def fill_class(references, school_class=None):
        years, levels, rooms = references
        dialog = ClassDialog(years, levels, rooms, school_class=school_class)
        if school_class is None:
            assert dialog.academic_year.currentData() == new_year.id  # current year preselected
            dialog.name.setText(f"C{suffix}")
            assert not dialog.save_enabled  # no level yet
            dialog.level.setCurrentIndex(dialog.level.findText(f"Niveau E2E {suffix} (N{suffix})"))
            dialog.main_room.setCurrentIndex(1 if rooms else 0)
            dialog.capacity.setText("30")
        else:
            dialog.name.setText(f"C{suffix} bis")
        assert dialog.save_enabled
        return dialog.values()

    classes.open_dialog = fill_class
    classes.add()
    assert classes.banner.kind == "success", classes.banner.plain_text()
    names = [classes.table.item(r, 0).text() for r in range(classes.table.rowCount())]
    assert f"C{suffix}" in names
    classes.table.selectRow(names.index(f"C{suffix}"))
    classes.edit()
    assert classes.banner.kind == "success", classes.banner.plain_text()
    classes.confirm = lambda *args, **kwargs: True
    names = [classes.table.item(r, 0).text() for r in range(classes.table.rowCount())]
    classes.table.selectRow(names.index(f"C{suffix} bis"))
    classes.toggle()
    assert classes.banner.plain_text() == f"Classe « C{suffix} bis » désactivée avec succès."
    classes.status.setCurrentIndex(1)  # Inactives
    names = [classes.table.item(r, 0).text() for r in range(classes.table.rowCount())]
    classes.table.selectRow(names.index(f"C{suffix} bis"))
    classes.toggle()
    assert classes.banner.plain_text() == f"Classe « C{suffix} bis » réactivée avec succès."

    # --- Tableau de bord: the new data, charts in a real state (never an error) ---
    dashboard = shell.open("dashboard")
    values = {card.label.text(): card.value.text() for card in dashboard.cards}
    assert values["Année scolaire active"] == new_year.name and values["Classes"] == "1"
    for card in (dashboard.attendance_card, dashboard.enrollment_card, dashboard.trend_card):
        assert card.status in ("data", "empty"), card.state.text()
    assert dashboard.activity_card.status == "data"
    titles = " ".join(row.findChildren(type(dashboard.subheading))[0].text() for row in dashboard.activity_card.rows)
    assert f"C{suffix}" in titles and f"Niveau E2E {suffix}" in titles

    # --- The level is used by an active class of an open year: refused (409) ---
    levels = shell.open("levels")
    levels.confirm = lambda *args, **kwargs: True
    codes = [levels.table.item(r, 1).text() for r in range(levels.table.rowCount())]
    levels.table.selectRow(codes.index(f"N{suffix}"))
    levels.toggle()
    assert levels.banner.kind == "warning" and "ne peut pas être désactivé" in levels.banner.plain_text()

    # --- Restore the previous current year, then close the test year ---
    years = shell.open("years")
    years.confirm = lambda *args, **kwargs: True
    if previous_current is not None:
        years.select_id(previous_current.id)
        years.set_current()
        assert years.selected().is_current, years.banner.plain_text()
    years.select_id(new_year.id)
    years.close_year()
    assert years.banner.plain_text() == f"Année « {new_year.name} » clôturée.", years.banner.plain_text()

    shell.logout_button.click()
    assert live.main_window is None and live.api.access_token is None
