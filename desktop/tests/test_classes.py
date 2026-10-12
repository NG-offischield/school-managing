"""Gestion académique → Classes: client service, page, dialog, errors,
filters, navigation, readability with the current theme."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QComboBox, QLabel, QLineEdit, QPushButton

from school_admin.api.errors import Conflict, ValidationFailed
from school_admin.config import AppConfig
from school_admin.services.classes import ClassService, ReferenceService
from school_admin.ui.app import AppController
from school_admin.ui.dialogs.class_dialog import CHOOSE_LEVEL, NO_ROOM, ClassDialog
from school_admin.ui.tasks import ImmediateRunner
from school_admin.ui.theme import contrast_ratio

from .fake_backend import PASSWORD, fail


@pytest.fixture
def classes(logged_in, api):
    return ClassService(api)


@pytest.fixture
def refs(logged_in, api):
    return ReferenceService(api)


# =============================================================================
# Client service
# =============================================================================


def test_list_and_filters(classes):
    assert [c.name for c in classes.list()] == ["5e A", "5e B", "6e A", "6e B"]
    assert [c.name for c in classes.list(level_id="l5")] == ["5e A", "5e B"]
    assert [c.name for c in classes.list(search="sixi")] == ["6e A", "6e B"]  # level name
    six_a = classes.list(search="6e A")[0]
    assert (six_a.level_label, six_a.year_name, six_a.main_room_label) == ("Sixième", "2025-2026", "")
    assert classes.list(academic_year_id="y2") == []


def test_references_come_from_the_api(refs):
    assert [y.name for y in refs.years(open_only=True)] == ["2025-2026", "2026-2027"]  # current first, no closed
    assert [lv.code for lv in refs.levels()] == ["6E", "5E"]  # active only, in order
    assert [r.code for r in refs.rooms()] == ["R12", "LAB"]


def test_create_update_deactivate_reactivate(classes, backend):
    created = classes.create(name="4e A", level_id="l5", academic_year_id="y1", main_room_id="r1", capacity=35)
    assert (created.name, created.main_room_label, created.capacity) == ("4e A", "R12 — Salle 12", 35)
    edited = classes.update(created.id, name="4e Bilingue", level_id="l6", main_room_id=None, capacity=None)
    assert (edited.name, edited.level_label, edited.main_room_id) == ("4e Bilingue", "Sixième", None)
    assert ("PATCH", f"classes/{created.id}/") in backend.calls
    assert classes.deactivate(created.id).active is False
    assert classes.reactivate(created.id).active is True


def test_rules_are_the_servers(classes):
    with pytest.raises(ValidationFailed) as exc:  # incomplete: refused before any call
        classes.create(name="", level_id=None, academic_year_id=None)
    assert set(exc.value.field_errors()) == {"name", "level", "academic_year"}
    with pytest.raises(Conflict) as exc:
        classes.create(name="6E A", level_id="l6", academic_year_id="y1")
    assert exc.value.rule == "duplicate_class_name"
    with pytest.raises(ValidationFailed) as exc:
        classes.create(name="Tle C", level_id="l6", academic_year_id="y0")
    assert exc.value.rule == "year_closed"
    in_use = classes.list(search="6e A")[0]
    with pytest.raises(Conflict) as exc:
        classes.deactivate(in_use.id)
    assert exc.value.rule == "class_in_use"


# =============================================================================
# Dialog
# =============================================================================


def dialog_for(refs, school_class=None):
    return ClassDialog(refs.years(open_only=True), refs.levels(), refs.rooms(), school_class=school_class)


def test_dialog_lists_validation_and_values(qapp, refs):
    dialog = dialog_for(refs)
    dialog.show()
    QTest.qWaitForWindowExposed(dialog)
    for combo in (dialog.academic_year, dialog.level, dialog.main_room):
        assert not combo.isEditable()  # lists from the API, never free text
    assert [dialog.level.itemText(i) for i in range(dialog.level.count())] == [
        CHOOSE_LEVEL,
        "Sixième (6E)",
        "Cinquième (5E)",
    ]
    assert dialog.academic_year.currentText() == "2025-2026 (courante)"  # current year preselected, compact label
    assert dialog.main_room.currentText() == NO_ROOM and dialog.main_room.count() == 3  # active rooms only
    assert not dialog.save_enabled and dialog.status.text() == "Pour enregistrer, complétez : Nom, Niveau."
    QTest.keyClicks(dialog.name, "4e A")
    assert dialog.status.text() == "Pour enregistrer, complétez : Niveau."
    dialog.level.setCurrentIndex(2)
    dialog.main_room.setCurrentIndex(2)
    QTest.keyClicks(dialog.capacity, "35x")  # digits only
    assert dialog.save_enabled and dialog.status.text() == ""
    assert dialog.values() == {
        "name": "4e A",
        "academic_year_id": "y1",
        "level_id": "l5",
        "main_room_id": "r2",
        "regime_id": None,  # no regime in this year: field hidden
        "capacity": 35,
        "public_visible": False,
    }
    dialog.close()


def test_edit_dialog_keeps_the_year_and_shows_inactive_values(qapp, refs, backend):
    from school_admin.models import SchoolClass

    old = SchoolClass(
        "c1", "3e A", "lx", "Ancien niveau", "y1", "2025-2026", 30, "rx", "OLD — Salle fermée", True, True
    )
    dialog = dialog_for(refs, old)
    assert dialog.windowTitle() == "Modifier la classe" and not dialog.academic_year.isEnabled()
    assert dialog.level.currentText() == "Ancien niveau (inactif)"
    assert dialog.main_room.currentText() == "OLD — Salle fermée (inactive)"
    assert dialog.capacity.text() == "30" and dialog.public_visible.isChecked() and dialog.save_enabled


def test_dialog_is_readable_with_the_current_theme(qapp, refs):
    dialog = dialog_for(refs)
    dialog.resize(dialog.sizeHint())
    dialog.show()
    QTest.qWaitForWindowExposed(dialog)
    background = dialog.palette().color(QPalette.Window).name()
    assert contrast_ratio(background, "#FFFFFF") < 1.1
    texts = [label.text() for label in dialog.findChildren(QLabel)]
    for caption in (
        "Nouvelle classe",
        "Nom *",
        "Année scolaire *",
        "Niveau *",
        "Salle principale",
        "Capacité (élèves)",
        "Options",
    ):
        assert caption in texts
    for label in (lb for lb in dialog.findChildren(QLabel) if lb.isVisible()):
        assert label.text().strip()
        assert contrast_ratio(label.palette().color(QPalette.WindowText).name(), background) >= 4.5, label.text()
    for field in dialog.findChildren(QLineEdit) + dialog.findChildren(QComboBox):
        assert (
            contrast_ratio(field.palette().color(QPalette.Text).name(), field.palette().color(QPalette.Base).name())
            >= 4.5
        )
    buttons = {b.text(): b.property("variant") for b in dialog.findChildren(QPushButton)}
    assert buttons == {"Annuler": "secondary", "Enregistrer": "primary"}
    for widget in dialog.findChildren(QLabel) + dialog.findChildren(QPushButton):
        if widget.isVisible():
            assert dialog.rect().contains(widget.geometry()), widget.text()
    QTest.keyClick(dialog, Qt.Key_Escape)
    assert not dialog.isVisible()


# =============================================================================
# Page
# =============================================================================


@pytest.fixture
def controller(qapp, api, auth):
    ctrl = AppController(api, auth, ImmediateRunner(), AppConfig(api_url="http://testserver/api/v1/"))
    ctrl.confirmations = []
    ctrl.confirm_answer = True

    def confirm(_parent, title, text, **options):
        ctrl.confirmations.append((title, text, options))
        return ctrl.confirm_answer

    ctrl.page_options = {"classes": {"confirm": confirm}}
    yield ctrl
    if ctrl.main_window is not None:
        ctrl.main_window.close()
    ctrl.login_window.close()


def open_classes(ctrl):
    window = ctrl.login_window
    window.identifier.setText("admin")
    window.password.setText(PASSWORD)
    window.attempt()
    return ctrl.main_window, ctrl.main_window.open("classes")


def names(page):
    return [page.table.item(r, 0).text() for r in range(page.table.rowCount())]


def test_navigation_and_list(controller):
    shell, page = open_classes(controller)
    labels = [shell.nav.item(i).text() for i in range(shell.nav.count())]
    assert "Classes" in labels and "Classes   ·  Bientôt" not in labels
    assert shell.current_key == "classes" and type(page).__name__ == "ClassesPage"
    assert page.year_filter.currentText() == "2025-2026 — année courante"  # default: the current year
    assert names(page) == ["5e A", "5e B", "6e A", "6e B"] and page.count_label.text() == "4 classes"
    assert [page.table.horizontalHeaderItem(c).text() for c in range(page.table.columnCount())] == [
        "Nom",
        "Niveau",
        "Année scolaire",
        "Salle principale",
        "Capacité",
        "Statut",
    ]
    assert page.table.item(0, 3).text() == "—" and page.table.item(0, 5).text() == "●  Active"


def test_filters(controller):
    _, page = open_classes(controller)
    page.level_filter.setCurrentIndex(page.level_filter.findData("l6"))
    assert names(page) == ["6e A", "6e B"]
    page.search.setText("b")
    page.reload()
    assert names(page) == ["6e B"]
    page.year_filter.setCurrentIndex(page.year_filter.findData("y2"))
    assert names(page) == [] and page.empty.text() == "Aucune classe ne correspond à ces critères."
    assert page.level_filter.itemText(page.level_filter.findData("lx")) == "Ancien niveau (OLD) (inactif)"


def test_create_edit_deactivate_reactivate(controller, backend):
    _, page = open_classes(controller)
    offered = {}

    def create(references, school_class=None):
        years, levels, rooms, _regimes = references
        offered["years"] = [y.name for y in years]
        return {
            "name": "4e A",
            "academic_year_id": "y1",
            "level_id": "l5",
            "main_room_id": "r1",
            "capacity": 35,
            "public_visible": False,
        }

    page.open_dialog = create
    page.add()
    assert offered["years"] == ["2025-2026", "2026-2027"]  # only open years can receive a class
    assert page.banner.plain_text() == "Classe « 4e A » créée avec succès."
    row = names(page).index("4e A")
    assert page.table.item(row, 3).text() == "R12 — Salle 12" and page.table.item(row, 4).text() == "35 élèves"
    page.table.selectRow(row)
    page.open_dialog = lambda references, school_class=None: {
        "name": "4e Bilingue",
        "academic_year_id": school_class.year_id,
        "level_id": "l5",
        "main_room_id": None,
        "capacity": None,
        "public_visible": True,
    }
    page.edit()
    assert "4e Bilingue" in names(page) and page.banner.kind == "success"
    patch = [c for c in backend.calls if c[0] == "PATCH"]
    assert patch  # the year was not sent (fixed at creation)
    page.table.selectRow(names(page).index("4e Bilingue"))
    page.toggle()
    title, text, options = controller.confirmations[-1]
    assert title == "Désactiver la classe ?" and "« 4e Bilingue — 2025-2026 »" in text
    assert options == {"confirm_text": "Désactiver", "danger": True}
    page.status.setCurrentIndex(1)  # Inactives
    assert names(page) == ["4e Bilingue"]
    page.table.selectRow(0)
    assert page.toggle_button.text() == "Réactiver"
    page.toggle()
    assert page.banner.plain_text() == "Classe « 4e Bilingue » réactivée avec succès."


def test_cancelled_confirmation_sends_nothing(controller, backend):
    _, page = open_classes(controller)
    controller.confirm_answer = False
    page.table.selectRow(names(page).index("6e B"))
    page.toggle()
    assert not [c for c in backend.calls if c[1].endswith("/deactivate/")]


@pytest.mark.parametrize(
    ("method", "path_suffix", "status", "details", "kind", "text"),
    [
        ("POST", "", 403, None, "error", "Permission refusée : Message du serveur."),
        (
            "POST",
            "",
            409,
            {"rule": "duplicate_class_name"},
            "warning",
            "Une classe porte déjà ce nom pour cette année scolaire : choisissez-en un autre.",
        ),
        ("POST", "", 404, None, "warning", "Message du serveur. La liste va être actualisée."),
    ],
)
def test_errors_on_create(controller, backend, method, path_suffix, status, details, kind, text):
    _, page = open_classes(controller)
    backend.forced[(method, "classes/" + path_suffix)] = fail(status, "X", "Message du serveur.", details)
    page.open_dialog = lambda references, school_class=None: {
        "name": "4e A",
        "academic_year_id": "y1",
        "level_id": "l5",
        "main_room_id": None,
        "capacity": None,
        "public_visible": False,
    }
    page.add()
    assert page.banner.kind == kind
    assert page.banner.plain_text() == f"Impossible de créer la classe — {text}"


def test_class_in_use_cannot_be_deactivated(controller):
    _, page = open_classes(controller)
    page.table.selectRow(names(page).index("6e A"))
    page.toggle()
    assert page.banner.kind == "warning"
    assert page.banner.plain_text() == (
        "Impossible de désactiver la classe — Cette classe a encore des élèves inscrits ou des cours actifs : "
        "elle ne peut pas être désactivée."
    )


def test_dashboard_counts_real_classes(controller, backend):
    shell, _ = open_classes(controller)
    backend.add_class("CM2", "l6")
    dashboard = shell.open("dashboard")
    values = {card.label.text(): card.value.text() for card in dashboard.cards}
    assert values["Classes"] == "5"  # the real count of the current year


@pytest.mark.parametrize("width", [1366, 1920])
def test_toolbar_fits_without_overlap(controller, width):
    from PySide6.QtCore import QSize

    shell, page = open_classes(controller)
    shell.resize(QSize(width, 768))
    shell.show()
    QTest.qWaitForWindowExposed(shell)
    widgets = [page.search, page.status, page.year_filter, page.level_filter, page.count_label]
    for left, right in zip(widgets, widgets[1:], strict=False):
        assert left.geometry().right() < right.geometry().left(), (left.accessibleName(), right.accessibleName())
    assert page.search.width() >= 200 and page.year_filter.width() >= page.year_filter.minimumWidth()
    for button in (page.refresh_button, page.edit_button, page.toggle_button, page.add_button):
        assert button.isVisible() and button.width() >= button.minimumSizeHint().width()
    shell.close()
