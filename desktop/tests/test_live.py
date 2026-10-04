"""End-to-end against a REAL running backend (opt-in: `pytest -m live`).

Required environment (never committed):
    SCHOOL_ADMIN_E2E_URL        e.g. http://127.0.0.1:8000/api/v1/
    SCHOOL_ADMIN_E2E_USER       the SUPER_ADMIN created by `manage.py bootstrap_school`
    SCHOOL_ADMIN_E2E_PASSWORD   its password (environment only)

Runs the vertical through the real screens (headless): login -> dashboard ->
categories -> add category -> subjects -> add subject with that category ->
years -> add a year, make it current -> levels -> add a level ->
classes -> add a class in that year and level, edit / deactivate / reactivate
-> dashboard charts -> level still used (409) -> students: add (enrolled,
with a photo), record, edit, search, filter, change class, withdraw,
archive -> teachers: add (no password), record, compatibility verdict, add +
verify a subject, search, edit, deactivate / reactivate -> courses: create a
course (eligible teacher from the server), schedule it with the planning API,
deactivation refused while scheduled -> planning: generate the week's
sessions, week view filtered by class, new room + change room, move,
substitute (or the server's explained refusal), cancel -> timetable PDF
branded with the SCHOOL (never School Managing) -> finance: fee type, invoice
(obligation), simulated wallet payment (succeeded) and a declined one, refund,
receipt branded with the school -> payroll: correction, period, calculate,
verify, approve, pay (treasury debit), history -> previous current year
restored, test year closed -> logout.
Codes and dates are random so the test can be replayed; it creates a few
rows. Run it against a TEST backend (it switches the current year, then
restores it).
"""

import os
import re
import secrets
import uuid
import zlib
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from PySide6.QtCore import QDate
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from school_admin.api import ApiClient
from school_admin.auth.session import AuthService
from school_admin.auth.token_store import MemoryTokenStore
from school_admin.config import AppConfig
from school_admin.services.planning import monday_of
from school_admin.ui.app import AppController
from school_admin.ui.dialogs.class_dialog import ClassDialog
from school_admin.ui.dialogs.course_dialogs import CourseDialog
from school_admin.ui.dialogs.student_dialogs import ChangeClassDialog, StudentDialog
from school_admin.ui.dialogs.subject_dialog import SubjectDialog
from school_admin.ui.dialogs.teacher_dialogs import QualificationsDialog, TeacherDialog
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


def pdf_text(raw):
    """Text of a PDF (deflated content streams + raw bytes) for branding checks."""
    assert raw.startswith(b"%PDF")
    return (
        b"".join(
            zlib.decompress(stream)
            for stream in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", raw, re.S)
            if stream[:1] == b"x"
        )
        + raw
    )


def test_full_vertical_against_the_real_backend(live, tmp_path):
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

    # --- Élèves: create (enrolled in the test class, with a photo), record,
    #     edit, search, filter, change class, withdraw, archive ---
    second = live.classes.create(
        name=f"D{suffix}", level_id=live.levels.list(search=f"N{suffix}")[0].id, academic_year_id=new_year.id
    )
    students = shell.open("students")
    assert students.year_filter.currentData() == new_year.id

    def fill_student(kind, **context):
        if kind == "student" and context.get("student") is None:
            years, levels, classes_ = context["references"]
            dialog = StudentDialog((years, levels, classes_), choose_file=lambda _parent: str(photo_path))
            dialog.student_number.setText(f"E2E-{suffix}")
            dialog.registration_number.setText(f"INS-E2E-{suffix}")
            dialog.last_name.setText(f"Testeur{suffix}")
            dialog.first_name.setText("Élève")
            dialog.sex.setCurrentIndex(dialog.sex.findData("F"))
            dialog.date_of_birth.setDate(QDate(2013, 3, 14))
            dialog.pick_photo()
            dialog.enroll.setChecked(True)
            dialog.picker.year.setCurrentIndex(dialog.picker.year.findData(new_year.id))
            dialog.picker.level.setCurrentIndex(dialog.picker.level.findText(f"Niveau E2E {suffix} (N{suffix})"))
            dialog.picker.school_class.setCurrentIndex(dialog.picker.school_class.findData(class_id))
            assert dialog.save_enabled, dialog.status.text()
            return {**dialog.values(), "photo_change": dialog.photo_change}
        if kind == "student":
            dialog = StudentDialog(None, student=context["student"], photo=context.get("photo"))
            dialog.birth_place.setText("Douala")
            return {**dialog.values(), "photo_change": dialog.photo_change}
        if kind == "record":
            return record_actions.pop(0) if record_actions else None
        if kind == "change_class":
            dialog = ChangeClassDialog(context["references"], enrollment=context["enrollment"])
            dialog.picker.school_class.setCurrentIndex(dialog.picker.school_class.findData(second.id))
            return dialog.values()
        return None

    image = QImage(240, 300, QImage.Format_RGB32)
    image.fill(QColor("#1D4ED8"))
    photo_path = tmp_path / "photo élève.png"
    image.save(str(photo_path))
    class_id = next(c.id for c in live.references.classes(academic_year_id=new_year.id) if c.name == f"C{suffix} bis")
    record_actions = []
    students.ask = fill_student
    students.add()
    assert students.banner.kind == "success", students.banner.plain_text()
    student = students.selected()
    assert student.enrollment.class_name == f"C{suffix} bis" and student.has_photo
    assert live.students.photo(student.id).startswith(b"\xff\xd8")  # re-encoded JPEG from the server
    students.edit()
    assert students.banner.kind == "success", students.banner.plain_text()
    assert live.students.get(student.id).birth_place == "Douala"
    students.search.setText(f"testeur{suffix}")
    students.reload_first_page()
    assert [students.table.item(r, 0).text() for r in range(students.table.rowCount())] == [f"E2E-{suffix}"]
    students.class_filter.setCurrentIndex(students.class_filter.findData(class_id))
    assert students.table.rowCount() == 1
    students.table.selectRow(0)
    record_actions = ["change_class"]
    students.open_record()
    assert students.banner.kind == "success", students.banner.plain_text()
    students.class_filter.setCurrentIndex(0)
    students.table.selectRow(0)
    assert students.selected().enrollment.class_name == f"D{suffix}"
    history = [h.action for h in live.students.history(student.id)]
    assert "STUDENT_CLASS_CHANGED" in history and "STUDENT_ENROLLED" in history
    students.confirm = lambda *args, **kwargs: True
    record_actions = ["withdraw"]
    students.open_record()
    assert students.banner.kind == "success", students.banner.plain_text()
    students.table.selectRow(0)
    students.toggle_archive()
    assert students.banner.plain_text().endswith("archivé avec succès."), students.banner.plain_text()

    # --- Enseignants: create (account without password), record, compatibility
    #     verdict from the server, add + verify a subject, search, edit,
    #     deactivate / reactivate ---
    own_category = next(c for c in live.categories.list(active=True) if c.code == f"E2E{suffix}")
    own_subject = next(x for x in live.subjects.list(active=True) if x.code == f"S{suffix}")
    other_category = live.categories.create(code=f"F{suffix}", name=f"Autre catégorie {suffix}", description="")
    other_subject = live.subjects.create(
        code=f"T{suffix}", name=f"Autre matière {suffix}", category_id=other_category.id
    )
    teachers = shell.open("teachers")

    def fill_teacher(kind, **context):
        if kind == "teacher" and context.get("teacher") is None:
            dialog = TeacherDialog(context["categories"], context["subjects"])
            dialog.last_name.setText(f"Prof{suffix}")
            dialog.first_name.setText("Essai")
            dialog.email.setText(f"prof.{suffix.lower()}@e2e.test")
            dialog.employee_number.setText(f"ENS-{suffix}")
            dialog.category.setCurrentIndex(dialog.category.findData(own_category.id))
            dialog.primary_subject.setCurrentIndex(dialog.primary_subject.findData(own_subject.id))
            assert dialog.save_enabled, dialog.status.text()
            return dialog.values()
        if kind == "teacher":
            dialog = TeacherDialog(context["categories"], context["subjects"], teacher=context["teacher"])
            dialog.phone.setText("+237 600 00 00 00")
            return dialog.values()
        if kind == "record":
            return None
        return None

    teachers.ask = fill_teacher
    teachers.add()
    assert teachers.banner.kind == "success", teachers.banner.plain_text()
    teacher = teachers.selected()
    assert teacher.subjects == (f"S{suffix}",) and not teacher.account_activated  # no password created
    teachers.open_record()
    dialog = QualificationsDialog(
        teacher, live.teachers, live.runner, live.subjects.list(active=True), live.references.levels()
    )
    dialog.subject.setCurrentIndex(dialog.subject.findData(other_subject.id))
    dialog.check()
    assert dialog.verdict.result == "REQUIRES_REVIEW" and dialog.verdict.reason == "no_rule"  # the server decides
    dialog.add()
    assert f"T{suffix}" in dialog.subject_rows, dialog.banner.plain_text()
    dialog.subject_rows[f"T{suffix}"][1].click()  # Valider
    assert "validée" in dialog.banner.plain_text(), dialog.banner.plain_text()
    dialog.close()
    teachers.search.setText(f"prof{suffix}")
    teachers.reload_first_page()
    assert [teachers.table.item(r, 0).text() for r in range(teachers.table.rowCount())] == [f"ENS-{suffix}"]
    teachers.table.selectRow(0)
    assert set(teachers.selected().subjects) == {f"S{suffix}", f"T{suffix}"}
    teachers.edit()
    assert teachers.banner.kind == "success", teachers.banner.plain_text()
    assert live.teachers.get(teacher.id).phone == "+237 600 00 00 00"
    teachers.confirm = lambda *args, **kwargs: True
    teachers.toggle()
    assert teachers.banner.plain_text().endswith("désactivé avec succès."), teachers.banner.plain_text()
    teachers.status.setCurrentIndex(1)  # Inactifs
    teachers.table.selectRow(0)
    teachers.toggle()
    assert teachers.banner.plain_text().endswith("réactivé avec succès."), teachers.banner.plain_text()

    # --- Cours: Matière + Enseignant + Classe + Année -> Course, then the
    #     existing planning uses it (a slot through the planning API) ---
    courses = shell.open("courses")
    offered = {}

    def fill_course(kind, **context):
        if kind != "course" or context.get("course") is not None:
            return None
        dialog = CourseDialog(context["references"], courses.find_teachers)
        dialog.year.setCurrentIndex(dialog.year.findData(new_year.id))
        dialog.school_class.setCurrentIndex(dialog.school_class.findData(class_id))
        dialog.subject.setCurrentIndex(dialog.subject.findData(own_subject.id))
        offered["teachers"] = [dialog.teacher.itemData(i) for i in range(1, dialog.teacher.count())]
        dialog.teacher.setCurrentIndex(dialog.teacher.findData(teacher.id))
        dialog.coefficient.setText("3")
        assert dialog.save_enabled, dialog.status.text()
        return dialog.values()

    courses.ask = fill_course
    courses.add()
    assert courses.banner.kind == "success", courses.banner.plain_text()
    assert teacher.id in offered["teachers"]  # proposed by the server as eligible
    course = courses.selected()
    assert (course.class_name, course.subject_code, course.teacher_id, course.year_name) == (
        f"C{suffix} bis",
        f"S{suffix}",
        teacher.id,
        new_year.name,
    )
    slot = live.api.post(
        "admin/schedules/",
        {"course": course.id, "weekday": 2, "start_time": "08:00", "end_time": "10:00"},
    )
    timetable = live.api.list_all("schedules/", school_class=class_id)
    assert [(row["id"], row["course"]) for row in timetable] == [(slot["id"], course.id)]
    assert live.courses.get(course.id).published_slot_count == 1
    courses.confirm = lambda *args, **kwargs: True
    courses.toggle()
    assert courses.banner.kind == "warning" and "planning" in courses.banner.plain_text()  # still scheduled

    # --- Planning (Vie scolaire): the week of the test year, through the screens ---
    monday = monday_of(date(first, 10, 15))
    planning = shell.open("planning")
    week = planning.week
    week.monday = monday
    week.ask = lambda kind, **context: {
        "date_from": monday,
        "date_to": monday + timedelta(days=6),
        "class_id": class_id,
    }
    week.generate()
    assert week.banner.plain_text().startswith("1 séance(s) créée(s)"), week.banner.plain_text()
    week.class_filter.setCurrentIndex(week.class_filter.findData(class_id))
    assert [s.course_id for s in week.sessions] == [course.id], week.banner.plain_text()
    session = week.sessions[0]
    assert (session.date, session.hours, session.teacher_id, session.status) == (
        monday + timedelta(days=1),
        "08:00–10:00",
        teacher.id,
        "SCHEDULED",
    )
    week.select(session.id)
    assert week.current().id == session.id and week.session_button.isEnabled()

    rooms = planning.open_tab("rooms")
    rooms.ask = lambda kind, **context: {
        "code": f"R{suffix}",
        "name": f"Salle E2E {suffix}",
        "room_type": "CLASSROOM",
        "capacity": 30,
        "bench_count": 15,
    }
    rooms.add()
    assert rooms.banner.plain_text() == f"Salle « R{suffix} » créée avec succès.", rooms.banner.plain_text()
    room_id = next(r.id for r in live.planning.rooms(search=f"R{suffix}"))

    planning.open_tab("week")
    week.select(session.id)
    week.ask = lambda kind, **context: {"room_id": room_id, "reason": "Test E2E : changement de salle"}
    week.session_action("room")
    assert week.banner.plain_text() == "Salle de la séance modifiée.", week.banner.plain_text()
    assert week.current().room_code == f"R{suffix}"
    thursday = monday + timedelta(days=3)
    week.ask = lambda kind, **context: {
        "new_start": datetime.combine(thursday, datetime.min.time()).replace(hour=14),
        "new_end": datetime.combine(thursday, datetime.min.time()).replace(hour=16),
        "reason": "Test E2E : déplacement",
    }
    week.session_action("move")
    assert week.banner.plain_text() == "Séance déplacée.", week.banner.plain_text()
    assert (week.current().date, week.current().hours, week.current().is_moved) == (thursday, "14:00–16:00", True)
    other = next((t for t in live.teachers.all() if t.id != teacher.id), None)
    if other is not None:
        week.ask = lambda kind, **context: {"teacher_id": other.id, "reason": "Test E2E : remplacement"}
        week.session_action("substitute")
        if week.banner.property("kind") == "success":
            assert week.current().teacher_id == other.id and week.current().planned_teacher_id == teacher.id
            week.ask = lambda kind, **context: {"reason": "Test E2E : retour"}
            week.session_action("restore")
            assert week.banner.plain_text() == "Enseignant prévu restauré.", week.banner.plain_text()
            assert week.current().teacher_id == teacher.id
        else:  # the server's compatibility verdict, explained, never hidden
            assert week.banner.plain_text().startswith("Impossible de remplacer l'enseignant — ")
    week.ask = lambda kind, **context: {"reason": "Test E2E : annulation"}
    week.session_action("cancel")
    assert week.banner.plain_text() == "Séance annulée.", week.banner.plain_text()
    assert week.current().status == "CANCELLED"
    week.toggle_view()
    assert week.table.rowCount() == 1 and week.table.item(0, 6).text() == "Annulée"

    # --- Official documents keep the SCHOOL's branding (never School Managing) ---
    raw = live.api.get_bytes(f"reports/schedule.pdf/?school_class={class_id}&date={monday.isoformat()}")
    assert raw.startswith(b"%PDF")
    text = pdf_text(raw)
    assert b"School Managing" not in text and b"School\\040Managing" not in text
    school_ascii = dashboard.data.school_name.encode("latin-1", "ignore")
    assert school_ascii[:12] in text, "school name missing from the timetable"

    # --- Finance (desktop): obligation, simulated payments, refund, receipt ---
    me = live.api.get("auth/me/")
    membership = next(m["id"] for m in me["memberships"] if m["status"] == "ACTIVE")
    wallet = live.api.post(
        "admin/finance/wallets/",
        {"owner": membership, "provider_code": "FAKE_ORANGE", "wallet_identifier": f"69{suffix}01"},
    )
    live.api.post(f"admin/finance/wallets/{wallet['id']}/fund/", {"amount": "100000"})
    declining = live.api.post(
        "admin/finance/wallets/",
        {
            "owner": membership,
            "provider_code": "FAKE_MTN",
            "wallet_identifier": f"67{suffix}02",
            "simulation_behavior": "DECLINE",
        },
    )
    finance = shell.open("finance")
    fees = finance.open_tab("fee_types")
    fees.ask = lambda: {"code": f"F{suffix}", "name": f"Frais E2E {suffix}", "description": ""}
    fees.add()
    assert fees.banner.kind == "success", fees.banner.plain_text()
    fee_id = next(f.id for f in live.finance.fee_types() if f.code == f"F{suffix}")
    invoices = finance.open_tab("invoices")
    invoices.ask = lambda kind, **context: {
        "student_id": student.id,
        "fee_type_id": fee_id,
        "description": "Scolarité E2E",
        "amount": "60000",
        "due_date": date(first, 10, 31),
    }
    invoices.add()
    assert invoices.banner.plain_text().startswith("Facture "), invoices.banner.plain_text()
    invoice = invoices.selected()
    assert (invoice.total, invoice.balance, invoice.status) == (Decimal("60000.00"), Decimal("60000.00"), "ISSUED")

    payments = finance.open_tab("payments")
    offered = {}

    def pay_with(wallet_id, amount, invoice_ids, fee_type=None):
        def answer(kind, **context):
            offered["wallets"] = [w.id for w in context["wallets"]]
            return {
                "student_id": student.id,
                "amount": amount,
                "method": "WALLET",
                "idempotency_key": str(uuid.uuid4()),
                "invoice_ids": invoice_ids,
                "fee_type_id": fee_type,
                "wallet_id": wallet_id,
            }

        payments.ask = answer
        payments.add()
        return payments.selected()

    paid = pay_with(wallet["id"], "60000", [invoice.id])
    assert {wallet["id"], declining["id"]} <= set(offered["wallets"])  # the admin's own wallets
    assert payments.banner.plain_text().startswith(f"Paiement réussi — {paid.reference}"), payments.banner.plain_text()
    assert (paid.status, paid.amount) == ("SUCCEEDED", Decimal("60000.00"))
    refused = pay_with(declining["id"], "5000", [], fee_id)
    assert refused.status == "DECLINED" and payments.banner.plain_text().startswith("Paiement refusé")
    assert live.finance.invoice(invoice.id).status == "PAID"
    payments.ask = lambda kind, **context: {"amount": "10000", "reason": "Test E2E : trop perçu"}
    payments.refund_payment(live.finance.payment(paid.id))
    assert payments.banner.plain_text().startswith("Remboursement de"), payments.banner.plain_text()
    refunds = finance.open_tab("refunds")
    refunds.search.setText(paid.reference)
    refunds.reload_first_page()
    assert [refunds.table.item(r, 1).text() for r in range(refunds.table.rowCount())] == [paid.reference]
    assert live.finance.payment(paid.id).status == "PARTIALLY_REFUNDED"  # history kept
    receipt = pdf_text(live.api.get_bytes(f"payments/{paid.id}/receipt.pdf/"))
    assert b"School Managing" not in receipt and b"School\\040Managing" not in receipt
    assert school_ascii[:12] in receipt, "school name missing from the receipt"

    # --- Paie (desktop): correction -> period -> calculate -> verify -> approve -> pay ---
    live.api.post(
        "admin/payroll/teacher-rates/",
        {
            "teacher": teacher.id,
            "academic_year": new_year.id,
            "vacation_rate": "5000",
            "effective_from": date(first, 9, 1).isoformat(),
        },
    )
    employee_id = live.teachers.get(teacher.id).employee_id
    assert employee_id
    payroll = shell.open("payroll")
    adjustments = payroll.open_tab("adjustments")
    adjustments.ask = lambda employees: {
        "employee_id": employee_id,
        "amount": "15000",
        "reason": "Test E2E : prime",
        "effective_date": date(first, 10, 15),
    }
    adjustments.add()
    assert adjustments.banner.kind == "success", adjustments.banner.plain_text()
    periods = payroll.open_tab("periods")
    periods.ask = lambda kind, **context: (
        {
            "year_id": new_year.id,
            "name": f"Octobre {first} {suffix}",
            "start": date(first, 10, 1),
            "end": date(first, 10, 31),
        }
        if kind == "period"
        else True
    )
    periods.add()
    assert periods.banner.kind == "success", periods.banner.plain_text()
    periods.calculate()
    assert periods.banner.plain_text().startswith("Calcul terminé"), periods.banner.plain_text()
    payrolls = payroll.payrolls
    assert payroll.tabs.currentWidget() is payrolls
    mine = next(r for r in payrolls.rows if r.employee_id == employee_id)
    assert (mine.status, mine.payable) == ("CALCULATED", Decimal("15000.00"))
    detail = live.payroll.payroll(mine.id)
    assert detail.reconstructible and "ADJUSTMENT" in {line.kind for line in detail.lines}
    payrolls.select_id(mine.id)
    payrolls.ask = lambda kind, **context: True if kind == "approve" else {"method": "CASH", "wallet_id": None}
    payrolls.run_action("approve")
    assert payrolls.banner.plain_text().endswith("Paie approuvée : 15\u202f000 XAF."), payrolls.banner.plain_text()
    payrolls.run_action("pay")
    assert "Paie payée" in payrolls.banner.plain_text(), payrolls.banner.plain_text()
    settled = live.payroll.payroll(mine.id)
    assert settled.status == "PAID" and settled.payment_reference.startswith("PAYR-")
    payrolls.run_action("pay")  # a second payment is refused by the server, and said so
    assert "aucun second paiement" in payrolls.banner.plain_text()
    overview = finance.open_tab("overview")
    references = [overview.table.item(r, 2).text() for r in range(overview.table.rowCount())]
    assert settled.payment_reference in references and paid.reference in references  # treasury history

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
