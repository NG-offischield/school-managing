"""Global UI rule: no dialog, form or input panel leaves the screen.

Every dialog is checked at 1366×768, 1280×720, 1024×768 and on a very
small screen: it fits, the buttons stay visible and reachable (mouse and
keyboard), the form scrolls instead of growing, fields have a width that
matches their data, side-by-side fields stack when the dialog is narrow."""

from datetime import date

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel

from school_admin.models import AcademicYear, Category, Level, Room
from school_admin.ui.dialogs.category_dialog import CategoryDialog
from school_admin.ui.dialogs.class_dialog import ClassDialog
from school_admin.ui.dialogs.level_dialog import LevelDialog
from school_admin.ui.dialogs.subject_dialog import SubjectDialog
from school_admin.ui.dialogs.year_dialog import YearDialog
from school_admin.ui.widgets import FIELD_WIDTHS, SCREEN_MARGIN, ConfirmDialog

YEARS = [AcademicYear("y1", "2025-2026", "ACTIVE", True, date(2025, 9, 1), date(2026, 7, 31))]
LEVELS = [Level("l6", "6E", "Sixième", 1, True)]
ROOMS = [Room("r1", "R12", "Salle 12 du bâtiment principal (rez-de-chaussée)", 40, True)]
CATEGORIES = [Category("c1", "SCI", "Scientifique", "", True)]

DIALOGS = {
    "catégorie": lambda: CategoryDialog(),
    "matière": lambda: SubjectDialog(CATEGORIES),
    "classe": lambda: ClassDialog(YEARS, LEVELS, ROOMS),
    "année": lambda: YearDialog(suggested=(date(2026, 9, 1), date(2027, 7, 31))),
    "niveau": lambda: LevelDialog(),
    "confirmation": lambda: ConfirmDialog("Désactiver ?", "Texte explicatif " * 20, danger=True),
}
SCREENS = [QSize(1366, 768), QSize(1280, 720), QSize(1024, 768), QSize(800, 480)]


def on_screen(dialog, screen):
    """Show the dialog as it would open on a screen of size `screen`."""
    dialog.show()
    QTest.qWaitForWindowExposed(dialog)
    dialog.fit_to(screen)
    dialog.layout().activate()
    QApplication.processEvents()
    return dialog


def inside(widget, dialog):
    top_left = widget.mapTo(dialog, widget.rect().topLeft())
    bottom_right = widget.mapTo(dialog, widget.rect().bottomRight())
    return dialog.rect().contains(top_left) and dialog.rect().contains(bottom_right)


@pytest.mark.parametrize("screen", SCREENS, ids=lambda s: f"{s.width()}x{s.height()}")
@pytest.mark.parametrize("name", DIALOGS)
def test_dialog_fits_and_keeps_its_buttons(qapp, name, screen):
    dialog = on_screen(DIALOGS[name](), screen)
    assert dialog.width() <= screen.width() - SCREEN_MARGIN and dialog.height() <= screen.height() - SCREEN_MARGIN
    for action in (dialog.cancel_button, dialog.save_button):
        assert action.isVisible() and inside(action, dialog), f"{action.text()} hors de la fenêtre"
        assert action.width() >= action.minimumSizeHint().width()
    assert inside(dialog.footer, dialog)
    # Nothing is cut sideways: the form never needs a horizontal scroll bar.
    assert dialog.content.width() <= dialog.scroll.viewport().width()
    for label in dialog.content.findChildren(QLabel):
        if label.isVisible():
            assert label.mapTo(dialog.content, label.rect().bottomRight()).x() <= dialog.content.width()
    dialog.close()


@pytest.mark.parametrize("name", ["catégorie", "matière", "classe", "année", "niveau"])
def test_no_scroll_needed_on_usual_screens(qapp, name):
    for screen in (QSize(1366, 768), QSize(1280, 720)):
        dialog = on_screen(DIALOGS[name](), screen)
        assert not dialog.scroll.verticalScrollBar().isVisible(), f"{name} défile à {screen}"
        dialog.close()


def test_dialogs_stay_reasonably_narrow(qapp):
    for name, factory in DIALOGS.items():
        dialog = on_screen(factory(), QSize(1920, 1080))
        assert dialog.width() <= 640, name  # never stretched across the screen
        dialog.close()


def test_long_form_scrolls_with_fixed_buttons_and_follows_the_focus(qapp):
    dialog = ClassDialog(YEARS, LEVELS, ROOMS)
    on_screen(dialog, QSize(1024, 420))  # very short screen: the form must scroll
    bar = dialog.scroll.verticalScrollBar()
    assert bar.isVisible() and bar.maximum() > 0
    assert dialog.save_button.isVisible() and inside(dialog.save_button, dialog)
    dialog.name.setText("6e A")
    dialog.level.setCurrentIndex(1)
    dialog.activateWindow()
    dialog.name.setFocus()
    for _ in range(12):  # Tab down to the last field
        if dialog.focusWidget() is dialog.public_visible:
            break
        QTest.keyClick(dialog.focusWidget(), Qt.Key_Tab)
    assert dialog.focusWidget() is dialog.public_visible
    assert bar.value() > 0  # the form scrolled to the focused field
    viewport = dialog.scroll.viewport()
    field = dialog.public_visible
    assert viewport.rect().contains(field.mapTo(viewport, field.rect().center()))
    QTest.keyClick(dialog.public_visible, Qt.Key_Return)  # Enter saves, even scrolled down
    assert dialog.result() == QDialog.Accepted


def test_escape_closes_a_scrolled_dialog(qapp):
    dialog = on_screen(LevelDialog(), QSize(1024, 400))
    QTest.keyClick(dialog, Qt.Key_Escape)
    assert not dialog.isVisible() and dialog.result() == QDialog.Rejected


def test_field_widths_match_their_data(qapp):
    level = on_screen(LevelDialog(), QSize(1366, 768))
    assert level.code.width() <= FIELD_WIDTHS["short"] and level.order.width() <= FIELD_WIDTHS["short"]
    assert level.name.width() <= FIELD_WIDTHS["medium"] and level.prefix.width() <= FIELD_WIDTHS["short"]
    year = on_screen(YearDialog(), QSize(1366, 768))
    assert year.start.width() <= FIELD_WIDTHS["short"] and year.end.width() <= FIELD_WIDTHS["short"]
    category = on_screen(CategoryDialog(), QSize(1366, 768))
    assert category.description.width() > category.code.width() * 2  # free text keeps the width
    for dialog in (level, year, category):
        dialog.close()


def test_side_by_side_fields_stack_on_a_narrow_dialog(qapp):
    dialog = on_screen(ClassDialog(YEARS, LEVELS, ROOMS), QSize(1366, 768))
    assert not dialog.rows[0].stacked  # Nom | Capacité
    assert (
        dialog.name.mapTo(dialog, dialog.name.rect().topLeft()).y()
        == dialog.capacity.mapTo(dialog, dialog.capacity.rect().topLeft()).y()
    )
    on_screen(dialog, QSize(470, 700))  # narrow screen: one column
    assert dialog.rows[0].stacked and dialog.rows[1].stacked
    assert (
        dialog.capacity.mapTo(dialog, dialog.capacity.rect().topLeft()).y()
        > dialog.name.mapTo(dialog, dialog.name.rect().bottomLeft()).y()
    )
    assert inside(dialog.save_button, dialog)
    dialog.close()


def test_long_list_items_do_not_widen_the_form(qapp):
    rooms = [Room("r1", "R12", "Salle polyvalente du bâtiment des sciences, aile nord, premier étage", 40, True)]
    dialog = on_screen(ClassDialog(YEARS, LEVELS, rooms), QSize(1280, 720))
    assert dialog.main_room.width() <= FIELD_WIDTHS["medium"]
    dialog.main_room.setCurrentIndex(1)
    assert dialog.main_room.toolTip().startswith("R12 — Salle polyvalente")  # full text on hover
    assert dialog.main_room.view().minimumWidth() > dialog.main_room.width()  # open list shows it whole
    dialog.close()
