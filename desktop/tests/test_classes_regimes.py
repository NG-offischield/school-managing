"""Classes → default room and timetable regimes (desktop side).

The server decides (exclusive default room, day / evening exception, slots
inside the regime); the desktop offers the regime field only when the year
has regimes, explains that changing the default room moves nothing, shows the
server's refusals in French, and creates / edits regimes."""

import pytest
from PySide6.QtCore import QTime

from school_admin.models import SchoolClass
from school_admin.services.classes import ReferenceService, RegimeService
from school_admin.ui.dialogs.class_dialog import NO_REGIME, ROOM_HELP, ClassDialog
from school_admin.ui.dialogs.regime_dialog import NEW_REGIME, RegimeDialog

from .test_classes import controller, names, open_classes  # noqa: F401 (fixture)


@pytest.fixture
def refs(logged_in, api):
    return ReferenceService(api)


@pytest.fixture
def evening(logged_in, api):
    return RegimeService(api).create(academic_year_id="y1", name="Cours du soir", start="17:00", end="21:00")


def class_values(**extra):
    return {
        "name": "4e Soir",
        "academic_year_id": "y1",
        "level_id": "l5",
        "main_room_id": None,
        "regime_id": None,
        "capacity": None,
        "public_visible": False,
        **extra,
    }


def test_regime_field_hidden_when_the_year_has_none(qapp, refs):
    dialog = ClassDialog(refs.years(open_only=True), refs.levels(), refs.rooms(), regimes=refs.regimes())
    assert not dialog.regime.parentWidget().isVisibleTo(dialog)
    assert dialog.values()["regime_id"] is None
    assert "ne déplace aucun créneau" in ROOM_HELP  # the default room only pre-fills NEW slots
    dialog.close()


def test_regime_field_lists_the_chosen_years_regimes(qapp, refs, evening):
    dialog = ClassDialog(refs.years(open_only=True), refs.levels(), refs.rooms(), regimes=refs.regimes())
    assert dialog.regime.parentWidget().isVisibleTo(dialog)
    assert [dialog.regime.itemText(i) for i in range(dialog.regime.count())] == [
        NO_REGIME,
        "Cours du soir (17:00–21:00)",
    ]
    dialog.regime.setCurrentIndex(1)
    assert dialog.values()["regime_id"] == evening.id
    dialog.academic_year.setCurrentIndex(dialog.academic_year.findData("y2"))  # 2026-2027: no regime
    assert dialog.academic_year.currentData() == "y2"
    assert not dialog.regime.parentWidget().isVisibleTo(dialog) and dialog.values()["regime_id"] is None
    dialog.close()


def test_edit_keeps_the_class_regime(qapp, refs, evening):
    klass = SchoolClass(
        "c9",
        "4e Soir",
        "l5",
        "Cinquième",
        "y1",
        "2025-2026",
        None,
        "r1",
        "R12 — Salle 12",
        False,
        True,
        evening.id,
        evening.label,
    )
    dialog = ClassDialog(refs.years(open_only=True), refs.levels(), refs.rooms(), school_class=klass, regimes=[evening])
    assert dialog.regime.currentData() == evening.id
    assert dialog.values()["regime_id"] == evening.id and dialog.values()["main_room_id"] == "r1"
    dialog.close()


def test_a_taken_default_room_is_explained(controller, backend):  # noqa: F811
    _, page = open_classes(controller)
    six_a = next(c for c in backend.classes.values() if c["name"] == "6e A")
    six_a["main_room"] = "r1"
    page.open_dialog = lambda references, school_class=None: class_values(main_room_id="r1")
    page.add()
    assert page.banner.kind == "warning"
    assert "déjà la salle principale d'une autre classe" in page.banner.plain_text()
    assert "régime horaire distinct" in page.banner.plain_text()
    assert "4e Soir" not in names(page)


def test_day_and_evening_classes_share_the_room(controller, backend):  # noqa: F811
    _, page = open_classes(controller)
    regimes = RegimeService(page.service.api)
    day = regimes.create(academic_year_id="y1", name="Cours du jour", start="07:00", end="14:00")
    night = regimes.create(academic_year_id="y1", name="Cours du soir", start="17:00", end="21:00")
    six_a = next(c for c in backend.classes.values() if c["name"] == "6e A")
    six_a.update(main_room="r1", regime=day.id)
    page.open_dialog = lambda references, school_class=None: class_values(main_room_id="r1", regime_id=night.id)
    page.add()
    assert page.banner.plain_text() == "Classe « 4e Soir » créée avec succès."
    row = names(page).index("4e Soir")
    assert page.table.item(row, 3).text() == "R12 — Salle 12 · Cours du soir (17:00–21:00)"


def test_regimes_are_created_and_edited_from_the_classes_page(controller, backend):  # noqa: F811
    _, page = open_classes(controller)
    assert page.regimes_button.text() == "Régimes horaires…"
    offered = {}

    def create(years, regimes):
        offered["years"], offered["regimes"] = [y.name for y in years], list(regimes)
        return {
            "regime_id": None,
            "academic_year_id": "y1",
            "name": "Cours du soir",
            "start": "17:00",
            "end": "21:00",
            "active": True,
        }

    page.open_regimes = create
    page.manage_regimes()
    assert offered["years"] == ["2025-2026", "2026-2027"] and offered["regimes"] == []
    assert page.banner.plain_text() == "Régime horaire « Cours du soir » créé avec succès."
    created = next(iter(backend.regimes.values()))
    assert (created["start_time"], created["end_time"]) == ("17:00", "21:00")
    page.open_regimes = lambda years, regimes: {
        "regime_id": regimes[0].id,
        "academic_year_id": "y1",
        "name": "Cours du soir",
        "start": "16:30",
        "end": "21:00",
        "active": True,
    }
    page.manage_regimes()
    assert page.banner.plain_text() == "Régime horaire « Cours du soir » modifié avec succès."
    assert created["start_time"] == "16:30"


def test_regime_dialog_new_or_existing(qapp, refs, evening):
    dialog = RegimeDialog(refs.years(open_only=True), [evening])
    assert dialog.regime.itemText(0) == NEW_REGIME and dialog.save_button.text() == "Créer le régime"
    assert not dialog.save_enabled  # name missing
    dialog.name.setText("Samedi")
    dialog.start.setTime(QTime(8, 0))
    dialog.end.setTime(QTime(12, 0))
    assert dialog.values() == {
        "regime_id": None,
        "academic_year_id": "y1",
        "name": "Samedi",
        "start": "08:00",
        "end": "12:00",
        "active": True,
    }
    dialog.regime.setCurrentIndex(1)  # existing: pre-filled
    assert (dialog.name.text(), dialog.start.time().toString("HH:mm"), dialog.end.time().toString("HH:mm")) == (
        "Cours du soir",
        "17:00",
        "21:00",
    )
    assert dialog.values()["regime_id"] == evening.id and dialog.save_button.text() == "Enregistrer"
    dialog.close()
