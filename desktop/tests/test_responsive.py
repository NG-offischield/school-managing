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

from school_admin.models import (
    AcademicYear,
    Category,
    Enrollment,
    Level,
    Qualification,
    Room,
    SchoolClass,
    Student,
    Subject,
    Teacher,
)
from school_admin.ui.dialogs.category_dialog import CategoryDialog
from school_admin.ui.dialogs.class_dialog import ClassDialog
from school_admin.ui.dialogs.level_dialog import LevelDialog
from school_admin.ui.dialogs.student_dialogs import (
    ChangeClassDialog,
    EnrollDialog,
    StudentDialog,
    StudentRecordDialog,
)
from school_admin.ui.dialogs.subject_dialog import SubjectDialog
from school_admin.ui.dialogs.teacher_dialogs import (
    QualificationsDialog,
    ReasonDialog,
    TeacherDialog,
    TeacherRecordDialog,
)
from school_admin.ui.dialogs.year_dialog import YearDialog
from school_admin.ui.tasks import ImmediateRunner
from school_admin.ui.widgets import FIELD_WIDTHS, SCREEN_MARGIN, ConfirmDialog

YEARS = [AcademicYear("y1", "2025-2026", "ACTIVE", True, date(2025, 9, 1), date(2026, 7, 31))]
LEVELS = [Level("l6", "6E", "Sixième", 1, True)]
ROOMS = [Room("r1", "R12", "Salle 12 du bâtiment principal (rez-de-chaussée)", 40, True)]
CATEGORIES = [Category("c1", "SCI", "Scientifique", "", True)]

CLASSES = [SchoolClass("c1", "6e A", "l6", "", "y1", "", 40, None, "", False, True)]
STUDENT = Student("s1", "MAT-1", "INS-1", "Awa", "Ndiaye", date(2013, 2, 1), "F", "ACTIVE", "Douala", "Akwa", 140)
ENROLLMENT = Enrollment("e1", "y1", "2025-2026", "c1", "6e A", "l6", "6E", "Sixième", "ACTIVE", date(2025, 9, 2))

SUBJECTS = [Subject("s1", "MATH", "Mathématiques", "c1", "SCI — Scientifique", "THEORETICAL", False, True)]
TEACHER = Teacher(
    "t1",
    "ENS-1",
    "Jean",
    "Mbarga",
    "j@ecole.test",
    "",
    "c1",
    "SCI — Scientifique",
    "s1",
    "MATH — Mathématiques",
    ("MATH",),
    "ACTIVE",
    "ACTIVE",
    True,
    None,
    "Akwa",
    "",
    "",
    False,
    2,
    5,
)
QUALS = [Qualification("q1", "s1", "MATH", "Mathématiques", "VERIFIED", "ADMIN", "COMPATIBLE", "COMPATIBLE")]


class StubTeachers:
    """Answers of the API for the qualifications dialog (layout tests only)."""

    def qualifications(self, _teacher_id):
        return QUALS

    def rules(self, _teacher_id):
        return []

    def overrides(self, _teacher_id):
        return []


DIALOGS = {
    "catégorie": lambda: CategoryDialog(),
    "matière": lambda: SubjectDialog(CATEGORIES),
    "classe": lambda: ClassDialog(YEARS, LEVELS, ROOMS),
    "année": lambda: YearDialog(suggested=(date(2026, 9, 1), date(2027, 7, 31))),
    "niveau": lambda: LevelDialog(),
    "élève (ajout)": lambda: StudentDialog((YEARS, LEVELS, CLASSES)),
    "élève (modification)": lambda: StudentDialog(None, student=STUDENT),
    "inscription": lambda: EnrollDialog((YEARS, LEVELS, CLASSES), student=STUDENT),
    "changement de classe": lambda: ChangeClassDialog(([], LEVELS, CLASSES), enrollment=ENROLLMENT),
    "fiche élève": lambda: StudentRecordDialog(STUDENT, [ENROLLMENT], []),
    "enseignant (ajout)": lambda: TeacherDialog(CATEGORIES, SUBJECTS),
    "enseignant (modification)": lambda: TeacherDialog(CATEGORIES, SUBJECTS, teacher=TEACHER),
    "qualifications": lambda: QualificationsDialog(TEACHER, StubTeachers(), ImmediateRunner(), SUBJECTS, LEVELS),
    "dérogation": lambda: ReasonDialog("Accorder une dérogation ?", "Texte " * 30, with_expiry=True),
    "fiche enseignant": lambda: TeacherRecordDialog(TEACHER, QUALS, []),
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
        if action.isHidden():  # the record has only « Fermer »
            continue
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


@pytest.mark.parametrize("screen", [QSize(1366, 768), QSize(1280, 720)], ids=["1366x768", "1280x720"])
def test_long_student_form_scrolls_with_buttons_always_visible(qapp, screen):
    dialog = on_screen(StudentDialog((YEARS, LEVELS, CLASSES)), screen)
    bar = dialog.scroll.verticalScrollBar()
    assert dialog.height() <= screen.height() - SCREEN_MARGIN
    assert bar.isVisible() and bar.maximum() > 0  # the FORM scrolls, not the window
    assert inside(dialog.save_button, dialog) and inside(dialog.cancel_button, dialog)
    for field in (dialog.student_number, dialog.registration_number, dialog.date_of_birth, dialog.height_cm):
        assert field.width() <= FIELD_WIDTHS["short"]  # short data, short field
    for field in (dialog.last_name, dialog.first_name):
        assert field.width() <= FIELD_WIDTHS["medium"]
    dialog.activateWindow()
    dialog.student_number.setFocus()
    for _ in range(30):  # Tab down to the class list at the bottom of the form
        if dialog.focusWidget() is dialog.enroll:
            break
        QTest.keyClick(dialog.focusWidget(), Qt.Key_Tab)
    assert dialog.focusWidget() is dialog.enroll and bar.value() > 0
    viewport = dialog.scroll.viewport()
    assert viewport.rect().contains(dialog.enroll.mapTo(viewport, dialog.enroll.rect().center()))
    QTest.keyClick(dialog, Qt.Key_Escape)
    assert dialog.result() == QDialog.Rejected


@pytest.mark.parametrize("screen", [QSize(1280, 720), QSize(1024, 768)], ids=["1280x720", "1024x768"])
def test_long_teacher_form_scrolls_with_buttons_always_visible(qapp, screen):
    dialog = on_screen(TeacherDialog(CATEGORIES, SUBJECTS, teacher=TEACHER), screen)
    bar = dialog.scroll.verticalScrollBar()
    assert dialog.height() <= screen.height() - SCREEN_MARGIN
    assert bar.isVisible() and bar.maximum() > 0
    assert inside(dialog.save_button, dialog) and inside(dialog.cancel_button, dialog)
    assert dialog.employee_number.width() <= FIELD_WIDTHS["short"] and dialog.phone.width() <= FIELD_WIDTHS["short"]
    assert dialog.email.width() <= FIELD_WIDTHS["medium"] and dialog.last_name.width() <= FIELD_WIDTHS["medium"]
    dialog.activateWindow()
    dialog.last_name.setFocus()
    for _ in range(30):  # Tab down to the last field
        if dialog.focusWidget() is dialog.bio:
            break
        QTest.keyClick(dialog.focusWidget(), Qt.Key_Tab)
    assert dialog.focusWidget() is dialog.bio and bar.value() > 0
    viewport = dialog.scroll.viewport()
    assert viewport.rect().contains(dialog.bio.mapTo(viewport, dialog.bio.rect().center()))
    dialog.close()
