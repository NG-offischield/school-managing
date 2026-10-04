"""Gestion académique → Cours: client service, form (Année → Classe → Matière
→ Enseignant from the SERVER's eligible list), record, page (server pages,
search, filters, add / edit / (de)activate), errors 403 / 404 / 409."""

import pytest
from PySide6.QtCore import QSize
from PySide6.QtTest import QTest

from school_admin.api.errors import Conflict, NotFound, ValidationFailed
from school_admin.config import AppConfig
from school_admin.models import AcademicYear, Course, EligibleTeacher, SchoolClass, Subject
from school_admin.services.courses import CourseService
from school_admin.ui.app import AppController
from school_admin.ui.dialogs.course_dialogs import CHOOSE_TEACHER, CourseDialog, CourseRecordDialog
from school_admin.ui.tasks import ImmediateRunner

from .fake_backend import PASSWORD, fail


def class_id(backend, name):
    return next(c["id"] for c in backend.classes.values() if c["name"] == name)


@pytest.fixture
def courses(logged_in, api, backend):
    backend.seed_teachers()
    return CourseService(api)


# =============================================================================
# Client service
# =============================================================================


def test_create_list_update_and_activation(courses, backend):
    six_a = class_id(backend, "6e A")
    created = courses.create(class_id=six_a, subject_id=backend.math, teacher_id=backend.tm, coefficient="4")
    assert (created.subject_code, created.class_name, created.teacher_number, created.coefficient) == (
        "MATH",
        "6e A",
        "ENS-001",
        "4",
    )
    rows, total = courses.page()
    assert total == 1 and rows[0].year_name == "2025-2026"
    assert courses.page(class_id=class_id(backend, "5e A"))[0] == []
    assert len(courses.page(search="mbarga")[0]) == 1
    edited = courses.update(created.id, coefficient="4,5", weekly_hours="5")  # French decimal comma accepted
    assert (edited.coefficient, edited.weekly_hours) == ("4.5", "5")
    assert courses.deactivate(created.id).active is False
    assert courses.reactivate(created.id).active is True


def test_eligible_teachers_and_rules_are_the_servers(courses, backend):
    six_a = class_id(backend, "6e A")
    eligible, excluded = courses.eligible_teachers(six_a, backend.math)
    assert [t.number for t in eligible] == ["ENS-001"] and excluded == []
    backend._qualify(backend.tf, backend.math)  # other category: pending review
    eligible, excluded = courses.eligible_teachers(six_a, backend.math)
    assert [(t.number, t.reason) for t in excluded] == [("ENS-002", "teacher_not_qualified")]
    with pytest.raises(ValidationFailed) as exc:
        courses.create(class_id=six_a, subject_id=backend.math, teacher_id=backend.tf)
    assert exc.value.rule == "teacher_not_qualified"
    with pytest.raises(ValidationFailed) as exc:  # refused before any call
        courses.create(class_id=None, subject_id=None, teacher_id=None)
    assert set(exc.value.field_errors()) == {"class_id", "subject_id", "teacher_id"}
    courses.create(class_id=six_a, subject_id=backend.math, teacher_id=backend.tm)
    with pytest.raises(Conflict) as exc:
        courses.create(class_id=six_a, subject_id=backend.math, teacher_id=backend.tm)
    assert exc.value.rule == "duplicate_course"
    with pytest.raises(NotFound):
        courses.get("another-school-course")


# =============================================================================
# Dialogs
# =============================================================================

YEARS = [AcademicYear("y1", "2025-2026", "ACTIVE", True)]
CLASSES = [
    SchoolClass("c1", "6e A", "l6", "", "y1", "", None, None, "", False, True),
    SchoolClass("c9", "6e Z", "l6", "", "y2", "", None, None, "", False, True),
]
SUBJECTS = [Subject("s1", "MATH", "Mathématiques", "k1", "SCI — Scientifique", "THEORETICAL", False, True)]
SCALES = [{"id": "sc20", "code": "SUR20", "label": "/20"}]


def test_course_dialog_cascade_uses_the_servers_teachers(qapp):
    asked = []

    def find(class_id, subject_id, done):
        asked.append((class_id, subject_id))
        done(
            (
                [EligibleTeacher("t1", "ENS-001", "Mbarga Jean", "SCI")],
                [EligibleTeacher("t2", "ENS-002", "Ngo Marie", "LIT", "teacher_not_qualified")],
            )
        )

    dialog = CourseDialog((YEARS, CLASSES, SUBJECTS, SCALES), find)
    assert dialog.year.currentData() == "y1"
    assert [dialog.school_class.itemText(i) for i in range(dialog.school_class.count())] == [
        "Choisir une classe…",
        "6e A",
    ]  # classes of the chosen year only
    assert not dialog.teacher.isEnabled() and asked == []
    assert dialog.status.text() == "Pour enregistrer, complétez : Classe, Matière, Enseignant."
    dialog.school_class.setCurrentIndex(1)
    dialog.subject.setCurrentIndex(1)
    assert asked == [("c1", "s1")]  # the server is asked, nothing is judged here
    assert [dialog.teacher.itemText(i) for i in range(dialog.teacher.count())] == [
        CHOOSE_TEACHER,
        "Mbarga Jean (ENS-001, SCI)",
    ]
    assert "Non proposés : Ngo Marie (matière non validée)." in dialog.teacher_hint.text()
    dialog.teacher.setCurrentIndex(1)
    dialog.coefficient.setText("4")
    dialog.scale.setCurrentIndex(1)
    assert dialog.save_enabled
    assert dialog.values() == {
        "teacher_id": "t1",
        "coefficient": "4",
        "weekly_hours": None,
        "scale_id": "sc20",
        "class_id": "c1",
        "subject_id": "s1",
    }


def test_course_dialog_without_eligible_teacher_says_why(qapp):
    dialog = CourseDialog((YEARS, CLASSES, SUBJECTS, SCALES), lambda c, s, done: done(([], [])))
    dialog.school_class.setCurrentIndex(1)
    dialog.subject.setCurrentIndex(1)
    assert not dialog.teacher.isEnabled() and "Aucun enseignant autorisé" in dialog.teacher_hint.text()
    assert not dialog.save_enabled


def course_row(**extra):
    values = {
        "id": "k1",
        "subject_id": "s1",
        "subject_code": "MATH",
        "subject_name": "Mathématiques",
        "teacher_id": "t1",
        "teacher_number": "ENS-001",
        "teacher_name": "Mbarga Jean",
        "class_id": "c1",
        "class_name": "6e A",
        "level_code": "6E",
        "year_id": "y1",
        "year_name": "2025-2026",
        "coefficient": "4.00",
        "weekly_hours": "5.00",
        "active": True,
        "published_slot_count": 2,
        "upcoming_session_count": 6,
    }
    return Course(**{**values, **extra})


def test_edit_dialog_fixes_identity_and_record(qapp):
    found = []
    dialog = CourseDialog(
        (YEARS, CLASSES, SUBJECTS, SCALES),
        lambda c, s, done: (found.append((c, s)), done(([EligibleTeacher("t1", "ENS-001", "Mbarga Jean", "SCI")], []))),
        course=course_row(),
    )
    assert not dialog.year.isEnabled() and not dialog.school_class.isEnabled() and not dialog.subject.isEnabled()
    assert dialog.teacher.currentData() == "t1" and dialog.coefficient.text() == "4.00"
    assert "class_id" not in dialog.values()  # identity is never sent
    record = CourseRecordDialog(course_row())
    texts = " ".join(label.text() for label in record.content.findChildren(type(record.status)))
    for expected in ("COURS", "ENSEIGNANT", "ÉVALUATION", "PLANNING", "Mbarga Jean (ENS-001)", "6"):
        assert expected in texts
    record.edit_button.click()
    assert record.action == "edit"


# =============================================================================
# Page
# =============================================================================


@pytest.fixture
def controller(qapp, api, auth, backend):
    backend.seed_teachers()
    backend.add_course(class_id(backend, "6e A"), backend.math, backend.tm, "4.00")
    backend.add_course(class_id(backend, "5e A"), backend.fr, backend.tf, "2.00")
    ctrl = AppController(api, auth, ImmediateRunner(), AppConfig(api_url="http://testserver/api/v1/"))
    ctrl.confirmations = []
    ctrl.confirm_answer = True

    def confirm(_parent, title, text, **options):
        ctrl.confirmations.append((title, text, options))
        return ctrl.confirm_answer

    ctrl.page_options = {"courses": {"confirm": confirm}}
    yield ctrl
    if ctrl.main_window is not None:
        ctrl.main_window.close()
    ctrl.login_window.close()


def open_courses(ctrl):
    window = ctrl.login_window
    window.identifier.setText("admin")
    window.password.setText(PASSWORD)
    window.attempt()
    return ctrl.main_window, ctrl.main_window.open("courses")


def column(page, index=0):
    return [page.table.item(r, index).text() for r in range(page.table.rowCount())]


def test_navigation_list_search_filters(controller, backend):
    shell, page = open_courses(controller)
    labels = [shell.nav.item(i).text() for i in range(shell.nav.count())]
    start = labels.index("GESTION ACADÉMIQUE")
    assert labels[start + 8] == "Cours" and "Cours   ·  Bientôt" not in labels
    assert [page.table.horizontalHeaderItem(c).text() for c in range(7)] == [
        "Matière",
        "Enseignant",
        "Classe",
        "Niveau",
        "Année scolaire",
        "Coefficient",
        "Statut",
    ]
    assert page.year_filter.currentText() == "2025-2026 — année courante"
    assert column(page) == ["FR — Français", "MATH — Mathématiques"] and page.count_label.text() == "2 cours"
    row = column(page).index("MATH — Mathématiques")
    assert [page.table.item(row, c).text() for c in (1, 2, 3, 5)] == ["Mbarga Jean (ENS-001)", "6e A", "6E", "4.00"]
    page.class_filter.setCurrentIndex(page.class_filter.findData(class_id(backend, "6e A")))
    assert column(page) == ["MATH — Mathématiques"]
    page.class_filter.setCurrentIndex(0)
    page.subject_filter.setCurrentIndex(page.subject_filter.findData(backend.fr))
    assert column(page) == ["FR — Français"]
    page.subject_filter.setCurrentIndex(0)
    page.search.setText("zzz")
    page.reload_first_page()
    assert page.empty.text() == "Aucun cours ne correspond à ces critères."


def test_add_edit_record_and_activation(controller, backend):
    _, page = open_courses(controller)
    six_b = class_id(backend, "6e B")
    seen = {}

    def ask(kind, **context):
        if kind == "course" and context.get("course") is None:
            years, classes, subjects, scales = context["references"]
            seen["years"] = [y.name for y in years]
            seen["scales"] = [s["code"] for s in scales]
            return {
                "class_id": six_b,
                "subject_id": backend.math,
                "teacher_id": backend.tm,
                "coefficient": "4",
                "weekly_hours": "5",
                "scale_id": "sc20",
            }
        if kind == "course":
            return {"teacher_id": backend.tm, "coefficient": "4", "weekly_hours": "6", "scale_id": None}
        return "edit"  # the record asks to edit

    page.ask = ask
    page.add()
    assert seen == {"years": ["2025-2026", "2026-2027"], "scales": ["SUR20"]}
    assert page.banner.plain_text() == "Cours « MATH — 6e B » (Mbarga Jean) créé avec succès."
    assert page.selected().class_name == "6e B"
    page.open_record()
    assert page.banner.plain_text() == "Cours « MATH — 6e B » (Mbarga Jean) modifié avec succès."
    page.toggle()
    title, text, options = controller.confirmations[-1]
    assert title == "Désactiver le cours ?" and "s'il est encore utilisé" in text
    assert page.banner.plain_text() == "Cours « MATH — 6e B » (Mbarga Jean) désactivé avec succès."
    page.status.setCurrentIndex(1)  # Inactifs
    page.table.selectRow(0)
    page.toggle()
    assert page.banner.plain_text() == "Cours « MATH — 6e B » (Mbarga Jean) réactivé avec succès."


def test_errors_are_explained(controller, backend):
    _, page = open_courses(controller)
    scheduled = next(c for c in backend.courses.values() if c["subject"] == backend.math)
    backend.courses_scheduled.add(scheduled["id"])
    page.table.selectRow(column(page).index("MATH — Mathématiques"))
    page.toggle()
    assert page.banner.kind == "warning" and page.banner.plain_text() == (
        "Impossible de désactiver le cours — Ce cours est encore utilisé par le planning "
        "(créneaux en cours ou séances à venir)."
    )
    values = {"class_id": class_id(backend, "6e B"), "subject_id": backend.math, "teacher_id": backend.tm}
    for status, details, text in (
        (403, None, "Permission refusée : Message du serveur."),
        (409, {"rule": "duplicate_course"}, "Cet enseignant a déjà cette matière dans cette classe."),
        (404, None, "Message du serveur. La liste va être actualisée."),
        (400, {"rule": "incompatible_subject"}, None),
    ):
        backend.forced[("POST", "courses/")] = fail(status, "X", "Message du serveur.", details)
        page.ask = lambda kind, **c: dict(values)
        page.add()
        assert page.banner.plain_text().startswith("Impossible de créer le cours — "), status
        if text:
            assert page.banner.plain_text().endswith(text), status


@pytest.mark.parametrize("size", [QSize(1366, 768), QSize(1280, 720), QSize(1024, 768)])
def test_toolbar_and_filters_fit(controller, size):
    shell, page = open_courses(controller)
    shell.resize(size)
    shell.show()
    QTest.qWaitForWindowExposed(shell)
    rows = (
        [page.refresh_button, page.record_button, page.edit_button, page.toggle_button, page.add_button],
        [page.search, page.status, page.count_label],
        [page.year_filter, page.class_filter, page.subject_filter],
    )
    for row in rows:
        for left, right in zip(row, row[1:], strict=False):
            assert left.geometry().right() < right.geometry().left()
        for widget in row:
            assert widget.isVisible() and page.rect().contains(widget.mapTo(page, widget.rect().bottomRight()))
    shell.close()
