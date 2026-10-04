"""Gestion académique → Élèves: client service, dialogs (cascade année →
niveau → classe, photo, validation), page (server pages, filters, record,
add / edit / enroll / change class / withdraw / archive), errors 403/404/409."""

from datetime import date

import pytest
from PySide6.QtCore import QBuffer, QDate, QIODevice, QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest

from school_admin.api.errors import Conflict, NotFound, ValidationFailed
from school_admin.config import AppConfig
from school_admin.models import AcademicYear, Enrollment, Level, SchoolClass, Student
from school_admin.services.classes import ReferenceService
from school_admin.services.students import StudentService
from school_admin.ui.app import AppController
from school_admin.ui.dialogs.student_dialogs import (
    CHOOSE_CLASS,
    EARLIEST,
    ChangeClassDialog,
    EnrollDialog,
    StudentDialog,
    StudentRecordDialog,
)
from school_admin.ui.tasks import ImmediateRunner

from .fake_backend import PASSWORD, fail


def png_bytes(width=200, height=240):
    image = QImage(width, height, QImage.Format_RGB32)
    image.fill(QColor("#1D4ED8"))
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


@pytest.fixture
def students(logged_in, api):
    return StudentService(api)


@pytest.fixture
def refs(logged_in, api):
    return ReferenceService(api)


# =============================================================================
# Client service
# =============================================================================


def test_list_is_paginated_and_filtered_by_the_api(students, backend):
    rows, total = students.page(status="ACTIVE")
    assert total == 3 and [s.last_name for s in rows] == ["Ekane", "Fotso", "Ndiaye"]
    awa = next(s for s in rows if s.last_name == "Ndiaye")
    assert (awa.enrollment.class_name, awa.enrollment.level_code, awa.enrollment.year_name) == (
        "6e A",
        "6E",
        "2025-2026",
    )
    assert next(s for s in rows if s.last_name == "Fotso").enrollment is None
    assert [s.last_name for s in students.page(level_id="l5")[0]] == ["Ekane"]
    assert [s.last_name for s in students.page(enrollment_status="NONE", status="ACTIVE")[0]] == ["Fotso"]
    assert [s.last_name for s in students.page(search="mat-004")[0]] == ["Mbia"]
    StudentService.PAGE_SIZE, original = 2, StudentService.PAGE_SIZE
    try:
        rows, total = students.page(page=2)
        assert (len(rows), total) == (2, 4)  # one page from the server, the total from meta
    finally:
        StudentService.PAGE_SIZE = original


def test_create_with_enrollment_update_archive_reactivate(students, backend):
    six_b = next(c for c in backend.classes.values() if c["name"] == "6e B")["id"]
    created = students.create(
        student_number="MAT-010",
        registration_number="INS-010",
        last_name="Kamga",
        first_name="Lina",
        sex="F",
        date_of_birth=date(2013, 4, 2),
        birth_place="",
        address="",
        height_cm=None,
        class_id=six_b,
    )
    assert created.enrollment.class_name == "6e B" and created.birth_place == ""
    edited = students.update(created.id, first_name="Lina Grâce", height_cm=140)
    assert (edited.first_name, edited.height_cm) == ("Lina Grâce", 140)
    with pytest.raises(Conflict) as exc:
        students.archive(created.id)  # still in a class
    assert exc.value.rule == "active_enrollment"
    enrollment = students.enrollments(created.id)[0]
    assert students.withdraw(enrollment.id).status == "WITHDRAWN"
    assert students.archive(created.id).status == "ARCHIVED"
    assert students.reactivate(created.id).status == "ACTIVE"
    assert [h.action for h in students.history(created.id)][:3] == [
        "STUDENT_REACTIVATED",
        "STUDENT_ARCHIVED",
        "STUDENT_WITHDRAWN",
    ]


def test_enroll_and_change_class_rules_are_the_servers(students, backend):
    chloe = backend.chloe
    six_a = next(c for c in backend.classes.values() if c["name"] == "6e A")["id"]
    six_b = next(c for c in backend.classes.values() if c["name"] == "6e B")["id"]
    with pytest.raises(ValidationFailed) as exc:
        students.enroll(chloe, None)  # refused before any call
    assert "school_class" in exc.value.field_errors()
    enrollment = students.enroll(chloe, six_a)
    assert (enrollment.class_name, enrollment.status) == ("6e A", "ACTIVE")
    with pytest.raises(Conflict) as exc:
        students.enroll(chloe, six_b)
    assert exc.value.rule == "already_enrolled"
    with pytest.raises(Conflict) as exc:
        students.change_class(enrollment.id, six_a)
    assert exc.value.rule == "same_class"
    moved = students.change_class(enrollment.id, six_b)
    assert moved.class_name == "6e B"
    backend.classes[six_a]["capacity"] = 1  # Awa already fills it
    with pytest.raises(Conflict) as exc:
        students.change_class(enrollment.id, six_a)
    assert exc.value.rule == "class_full"
    with pytest.raises(Conflict) as exc:
        students.create(
            student_number="mat-001",
            registration_number="X",
            last_name="X",
            first_name="Y",
            sex="M",
            date_of_birth=date(2013, 1, 1),
        )
    assert exc.value.rule == "duplicate_student_number"
    with pytest.raises(NotFound):
        students.get("another-school-student")
    with pytest.raises(ValidationFailed) as exc:
        students.create(student_number="", registration_number="", last_name="", first_name="", sex=None)
    assert set(exc.value.field_errors()) >= {"student_number", "last_name", "sex", "date_of_birth"}


def test_photo_sends_only_bytes_never_a_local_path(students, backend):
    content = png_bytes()
    saved = students.set_photo(backend.chloe, content, "PNG")
    assert saved.has_photo and students.photo(backend.chloe) == content
    raw = backend.photo_uploads[-1]
    assert b'filename="photo.png"' in raw and b"C:\\" not in raw and b"Users" not in raw
    with pytest.raises(ValidationFailed):
        students.set_photo(backend.chloe, b"%PDF-1.4", "pdf")  # refused before sending
    assert students.remove_photo(backend.chloe).has_photo is False
    assert students.photo(backend.chloe) is None


# =============================================================================
# Dialogs
# =============================================================================


YEARS = [
    AcademicYear("y1", "2025-2026", "ACTIVE", True, date(2025, 9, 1), date(2026, 7, 31)),
    AcademicYear("y2", "2026-2027", "PLANNED", False, date(2026, 9, 1), date(2027, 7, 31)),
]
LEVELS = [Level("l6", "6E", "Sixième", 1, True), Level("l5", "5E", "Cinquième", 2, True)]


def school_class(cid, name, level, year="y1", capacity=None):
    return SchoolClass(cid, name, level, "", year, "", capacity, None, "", False, True)


CLASSES = [
    school_class("c1", "6e A", "l6", capacity=40),
    school_class("c2", "6e B", "l6"),
    school_class("c3", "5e A", "l5"),
    school_class("c9", "6e A", "l6", year="y2"),
]


def test_student_dialog_validation_and_cascade(qapp):
    dialog = StudentDialog((YEARS, LEVELS, CLASSES))
    assert not dialog.save_enabled
    assert dialog.status.text() == (
        "Pour enregistrer, complétez : Matricule, N° d'inscription, Nom, Prénom(s), Sexe, Date de naissance."
    )
    dialog.student_number.setText("MAT-010")
    dialog.registration_number.setText("INS-010")
    dialog.last_name.setText("Kamga")
    dialog.first_name.setText("Lina")
    dialog.sex.setCurrentIndex(dialog.sex.findData("F"))
    assert dialog.date_of_birth.date() == EARLIEST and dialog.date_of_birth.text() == "jj/mm/aaaa"
    dialog.date_of_birth.setDate(QDate(2013, 4, 2))
    assert dialog.save_enabled  # enrollment is optional
    dialog.enroll.setChecked(True)
    assert not dialog.save_enabled and dialog.status.text().endswith("Classe.")
    picker = dialog.picker
    assert picker.year.currentData() == "y1"  # the current year first
    assert not picker.school_class.isEnabled() and "niveau" in picker.hint.text()
    picker.level.setCurrentIndex(picker.level.findData("l6"))
    offered = [picker.school_class.itemText(i) for i in range(picker.school_class.count())]
    assert offered == [CHOOSE_CLASS, "6e A · 40 places", "6e B"]  # this year AND this level only
    picker.level.setCurrentIndex(picker.level.findData("l5"))
    assert [picker.school_class.itemData(i) for i in range(1, picker.school_class.count())] == ["c3"]
    picker.year.setCurrentIndex(picker.year.findData("y2"))
    assert picker.school_class.count() == 1 and picker.hint.text().startswith("Aucune classe active")
    picker.level.setCurrentIndex(picker.level.findData("l6"))
    picker.school_class.setCurrentIndex(1)
    assert dialog.save_enabled
    values = dialog.values()
    assert values["class_id"] == "c9" and values["date_of_birth"] == date(2013, 4, 2)
    assert values["sex"] == "F" and values["height_cm"] is None


def test_student_dialog_photo_preview_and_checks(qapp, tmp_path):
    good = tmp_path / "élève photo.png"
    good.write_bytes(png_bytes())
    fake = tmp_path / "virus.png"
    fake.write_bytes(b"not an image")
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF")
    big = tmp_path / "big.jpg"
    big.write_bytes(b"\xff\xd8" + b"0" * (3 * 1024 * 1024 + 10))
    chosen = []
    dialog = StudentDialog(None, choose_file=lambda _parent: chosen.pop(0))
    for path, message in (
        (fake, "Ce fichier n'est pas une image lisible."),
        (pdf, "Format non accepté : JPEG, PNG ou WebP."),
        (big, "Photo trop lourde : 3 Mo au plus."),
    ):
        chosen.append(str(path))
        dialog.pick_photo()
        assert dialog.photo_status.text() == message and dialog.photo_change is None
    chosen.append(str(good))
    dialog.pick_photo()
    kind, content, extension = dialog.photo_change
    assert (kind, extension) == ("set", "png") and content == good.read_bytes()
    assert dialog.photo.pixmap() is not None and not dialog.photo.pixmap().isNull()  # preview before saving
    dialog.drop_photo()
    assert dialog.photo_change == ("remove",)


def test_edit_dialog_has_no_enrollment_and_keeps_values(qapp):
    student = Student("s1", "MAT-1", "INS-1", "Awa", "Ndiaye", date(2013, 2, 1), "F", "ACTIVE", "Douala", "", 140, True)
    dialog = StudentDialog(None, student=student, photo=png_bytes())
    assert dialog.picker is None and dialog.save_enabled
    assert (dialog.last_name.text(), dialog.date_of_birth.date(), dialog.height_cm.text()) == (
        "Ndiaye",
        QDate(2013, 2, 1),
        "140",
    )
    assert dialog.remove_photo_button.isEnabled()


def test_enroll_and_change_class_dialogs(qapp):
    student = Student("s1", "MAT-1", "INS-1", "Awa", "Ndiaye", date(2013, 2, 1), "F", "ACTIVE")
    enroll = EnrollDialog((YEARS, LEVELS, CLASSES), student=student)
    assert not enroll.save_enabled
    enroll.picker.level.setCurrentIndex(enroll.picker.level.findData("l5"))
    enroll.picker.school_class.setCurrentIndex(1)
    enroll.enrollment_date.setDate(QDate(2025, 10, 1))
    enroll.picker.school_class.setCurrentIndex(1)  # choosing again keeps the date
    assert enroll.values() == {"class_id": "c3", "enrollment_date": date(2025, 10, 1)}
    enroll.picker.year.setCurrentIndex(enroll.picker.year.findData("y2"))
    assert enroll.enrollment_date.minimumDate() == QDate(2026, 9, 1)  # date kept inside the year
    current = Enrollment("e1", "y1", "2025-2026", "c1", "6e A", "l6", "6E", "Sixième", "ACTIVE")
    change = ChangeClassDialog(([], LEVELS, [c for c in CLASSES if c.year_id == "y1"]), enrollment=current)
    assert not change.picker.year.isEnabled() and change.picker.year.currentText() == "2025-2026"
    assert change.picker.level.currentData() == "l6"
    offered = [change.picker.school_class.itemData(i) for i in range(1, change.picker.school_class.count())]
    assert offered == ["c2"]  # same year and level, not the current class
    change.picker.school_class.setCurrentIndex(1)
    assert change.values() == {"class_id": "c2"}


def test_record_dialog_sections_and_actions(qapp):
    student = Student("s1", "MAT-1", "INS-1", "Awa", "Ndiaye", date(2013, 2, 1), "F", "ACTIVE", "Douala", "Akwa", 140)
    enrollments = [Enrollment("e1", "y1", "2025-2026", "c1", "6e A", "l6", "6E", "Sixième", "ACTIVE", date(2025, 9, 2))]
    record = StudentRecordDialog(student, enrollments, [], png_bytes())
    texts = " ".join(label.text() for label in record.content.findChildren(type(record.status)))
    for expected in ("IDENTITÉ", "SCOLARITÉ", "INFORMATIONS COMPLÉMENTAIRES", "HISTORIQUE DES INSCRIPTIONS", "6e A"):
        assert expected in texts
    assert not record.enroll_button.isEnabled() and record.change_button.isEnabled()
    record.change_button.click()
    assert record.action == "change_class" and record.result() == record.DialogCode.Accepted


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

    ctrl.page_options = {"students": {"confirm": confirm}}
    yield ctrl
    if ctrl.main_window is not None:
        ctrl.main_window.close()
    ctrl.login_window.close()


def open_students(ctrl):
    window = ctrl.login_window
    window.identifier.setText("admin")
    window.password.setText(PASSWORD)
    window.attempt()
    return ctrl.main_window, ctrl.main_window.open("students")


def names(page, column=1):
    return [page.table.item(r, column).text() for r in range(page.table.rowCount())]


def select(page, last_name):
    page.table.selectRow(names(page).index(last_name))


def test_navigation_list_and_columns(controller):
    shell, page = open_students(controller)
    labels = [shell.nav.item(i).text() for i in range(shell.nav.count())]
    start = labels.index("GESTION ACADÉMIQUE")
    assert labels[start + 6] == "Élèves" and "Élèves   ·  Bientôt" not in labels
    assert [page.table.horizontalHeaderItem(c).text() for c in range(8)] == [
        "Matricule",
        "Nom",
        "Prénom(s)",
        "Sexe",
        "Classe",
        "Niveau",
        "Année scolaire",
        "Statut",
    ]
    assert page.year_filter.currentText() == "2025-2026 — année courante"
    assert names(page) == ["Ekane", "Ndiaye"]  # active pupils of the current year
    row = names(page).index("Ndiaye")
    assert [page.table.item(row, c).text() for c in range(8)] == [
        "MAT-001",
        "Ndiaye",
        "Awa",
        "Féminin",
        "6e A",
        "6E",
        "2025-2026",
        "●  Actif",
    ]
    assert page.count_label.text() == "2 élèves" and page.page_label.text() == "Page 1 / 1"


def test_search_and_filters(controller):
    _, page = open_students(controller)
    page.level_filter.setCurrentIndex(page.level_filter.findData("l6"))
    assert names(page) == ["Ndiaye"]
    classes = [page.class_filter.itemText(i) for i in range(page.class_filter.count())]
    assert classes == ["Toutes les classes", "6e A", "6e B"]  # follow the year and the level
    page.level_filter.setCurrentIndex(0)
    page.year_filter.setCurrentIndex(0)  # all years
    page.enrollment_filter.setCurrentIndex(page.enrollment_filter.findData("NONE"))
    assert names(page) == ["Fotso"] and page.table.item(0, 4).text() == "Non inscrit"
    page.enrollment_filter.setCurrentIndex(0)
    page.status.setCurrentIndex(1)  # Archivés
    assert names(page) == ["Mbia"]
    page.status.setCurrentIndex(2)  # Tous
    page.search.setText("ndia")
    page.reload_first_page()
    assert names(page) == ["Ndiaye"]
    page.search.setText("zzz")
    page.reload_first_page()
    assert names(page) == [] and page.empty.text() == "Aucun élève ne correspond à ces critères."


def test_server_pages(controller, backend):
    for i in range(55):
        backend.add_student(f"P{i:03d}", f"Zeta{i:03d}", "Test", "M")
    _, page = open_students(controller)
    page.year_filter.setCurrentIndex(0)
    assert page.count_label.text() == "58 élèves" and page.page_label.text() == "Page 1 / 2"
    assert page.table.rowCount() == 50 and not page.previous_button.isEnabled()
    page.next_button.click()
    assert page.page_label.text() == "Page 2 / 2" and page.table.rowCount() == 8 and not page.next_button.isEnabled()
    page.search.setText("zeta05")
    page.reload_first_page()
    assert page.page_label.text() == "Page 1 / 1"  # a new search restarts at page 1
    calls = [p for m, p in backend.calls if p == "students/"]
    assert calls  # every page came from the API


def test_add_with_enrollment_and_photo(controller, backend):
    _, page = open_students(controller)
    seen = {}

    def ask(kind, **context):
        years, levels, classes = context["references"]
        seen["years"] = [y.name for y in years]
        seen["classes"] = {c.name for c in classes}
        six_b = next(c for c in classes if c.name == "6e B" and c.year_id == "y1")
        return {
            "student_number": "MAT-020",
            "registration_number": "INS-020",
            "last_name": "Abena",
            "first_name": "Paul",
            "sex": "M",
            "date_of_birth": date(2013, 6, 1),
            "birth_place": "Yaoundé",
            "address": "",
            "height_cm": None,
            "class_id": six_b.id,
            "photo_change": ("set", png_bytes(), "png"),
        }

    page.ask = ask
    page.add()
    assert seen["years"] == ["2025-2026", "2026-2027"]  # open years only
    assert page.banner.plain_text() == "Élève « Abena Paul » (MAT-020) créé avec succès."
    row = names(page).index("Abena")
    assert page.table.item(row, 4).text() == "6e B" and page.selected().has_photo


def test_edit_record_enroll_change_withdraw_archive(controller, backend):
    _, page = open_students(controller)
    page.year_filter.setCurrentIndex(0)
    select(page, "Fotso")
    page.ask = lambda kind, **c: {
        **{
            k: getattr(c["student"], k)
            for k in (
                "student_number",
                "registration_number",
                "last_name",
                "sex",
                "date_of_birth",
                "birth_place",
                "address",
                "height_cm",
            )
        },
        "first_name": "Chloé Ange",
        "photo_change": None,
    }
    page.edit()
    assert page.banner.plain_text() == "Élève « Fotso Chloé Ange » (MAT-003) modifié avec succès."
    # Record -> Inscrire
    actions = iter(["enroll"])
    six_a = next(c for c in backend.classes.values() if c["name"] == "6e A")["id"]
    six_b = next(c for c in backend.classes.values() if c["name"] == "6e B")["id"]

    def ask(kind, **context):
        if kind == "record":
            return next(actions, None)
        if kind == "enroll":
            return {"class_id": six_a, "enrollment_date": date(2025, 10, 1)}
        return {"class_id": six_b}

    page.ask = ask
    select(page, "Fotso")
    page.open_record()
    assert page.banner.plain_text().endswith("est inscrit(e) en 6e A (2025-2026).")
    assert page.table.item(names(page).index("Fotso"), 4).text() == "6e A"
    actions = iter(["change_class"])
    select(page, "Fotso")
    page.open_record()
    assert page.banner.plain_text() == "Fotso Chloé Ange passe de 6e A à 6e B."
    actions = iter(["withdraw"])
    select(page, "Fotso")
    page.open_record()
    title, text, options = controller.confirmations[-1]
    assert title == "Retirer l'élève de sa classe ?" and "conservés dans l'historique" in text
    assert options == {"confirm_text": "Retirer", "danger": True}
    select(page, "Fotso")
    page.toggle_archive()
    title, text, _ = controller.confirmations[-1]
    assert title == "Archiver l'élève ?" and "Rien n'est supprimé" in text
    assert page.banner.plain_text() == "Élève « Fotso Chloé Ange » (MAT-003) archivé avec succès."


def test_errors_are_explained(controller, backend):
    _, page = open_students(controller)
    select(page, "Ndiaye")
    page.toggle_archive()  # still in 6e A
    assert page.banner.kind == "warning" and page.banner.plain_text() == (
        "Impossible d'archiver l'élève — L'élève est encore inscrit dans une classe : retirez-le d'abord de sa classe."
    )
    for status, details, kind, text in (
        (403, None, "error", "Permission refusée : Message du serveur."),
        (
            409,
            {"rule": "duplicate_student_number"},
            "warning",
            "Ce matricule est déjà attribué à un autre élève de l'école.",
        ),
        (404, None, "warning", "Message du serveur. La liste va être actualisée."),
    ):
        backend.forced[("POST", "students/")] = fail(status, "X", "Message du serveur.", details)
        page.ask = lambda kind, **c: {
            "student_number": "M",
            "registration_number": "I",
            "last_name": "L",
            "first_name": "F",
            "sex": "M",
            "date_of_birth": date(2013, 1, 1),
            "photo_change": None,
        }
        page.add()
        assert page.banner.kind == kind and page.banner.plain_text() == f"Impossible de créer l'élève — {text}"


def test_cancelled_confirmation_sends_nothing(controller, backend):
    _, page = open_students(controller)
    controller.confirm_answer = False
    select(page, "Ekane")
    page.toggle_archive()
    assert not [c for c in backend.calls if c[1].endswith("/archive/")]


@pytest.mark.parametrize("size", [QSize(1366, 768), QSize(1280, 720)])
def test_toolbar_and_filters_fit(controller, size):
    shell, page = open_students(controller)
    shell.resize(size)
    shell.show()
    QTest.qWaitForWindowExposed(shell)
    buttons = [page.refresh_button, page.record_button, page.edit_button, page.archive_button, page.add_button]
    for left, right in zip(buttons, buttons[1:], strict=False):
        assert left.geometry().right() < right.geometry().left()
    filters = [page.year_filter, page.level_filter, page.class_filter, page.enrollment_filter]
    for left, right in zip(filters, filters[1:], strict=False):
        assert left.geometry().right() < right.geometry().left()
    for widget in [*buttons, *filters, page.next_button]:
        assert widget.isVisible() and page.rect().contains(widget.mapTo(page, widget.rect().bottomRight()))
    shell.close()


def test_dashboard_counts_active_students(controller, backend):
    shell, _ = open_students(controller)
    backend.add_student("MAT-099", "Nouveau", "Élève", "M")
    dashboard = shell.open("dashboard")
    values = {card.label.text(): card.value.text() for card in dashboard.cards}
    assert values["Élèves"] == "4"  # real count of ACTIVE students (archived ones excluded)
