"""Vie scolaire → Planning (ADR 0021): week view, slots, sessions, rooms,
availability requests, breaks — all through the EXISTING planning API; the
client never recomputes a conflict, it shows the server's answer. Plus the
software branding (School Managing) of the desktop."""

from datetime import date, datetime, time

import pytest
from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtTest import QTest

from school_admin.api.errors import ApiError, Conflict, Forbidden, NotFound, ValidationFailed
from school_admin.config import AppConfig
from school_admin.messages import explain_conflicts
from school_admin.services.planning import PlanningService, monday_of
from school_admin.ui import branding
from school_admin.ui.app import AppController
from school_admin.ui.dialogs.planning_dialogs import SessionDialog, SlotDialog
from school_admin.ui.tasks import ImmediateRunner

from .fake_backend import PASSWORD

MONDAY = date(2026, 3, 2)


@pytest.fixture
def planning(logged_in, api, backend):
    backend.seed_planning()
    return PlanningService(api)


# =============================================================================
# Service: the server's answers, relayed
# =============================================================================


def test_week_slots_rooms_and_filters(planning, backend):
    week = planning.week(MONDAY)
    assert [(s.subject_code, s.class_name, s.hours, s.room_code) for s in week] == [
        ("MATH", "6e A", "08:00–10:00", "R12"),
        ("FR", "5e A", "10:00–12:00", "LAB"),
    ]
    assert [s.subject_code for s in planning.week(MONDAY, teacher_id=backend.tf)] == ["FR"]
    assert planning.week(date(2026, 3, 9)) == []
    slots = planning.slots()
    assert [(s.code, s.when) for s in slots] == [
        ("MATH — 6e A", "Lundi 08:00–10:00"),
        ("FR — 5e A", "Mercredi 10:00–12:00"),
    ]
    assert [r.code for r in planning.rooms(active=True)] == ["R12", "LAB"]
    assert monday_of(date(2026, 3, 5)) == MONDAY


def test_conflicts_are_the_servers_and_explained(planning, backend):
    check = planning.check_slot(
        course_id=backend.c_fr, weekday=1, start_time=time(9, 0), end_time=time(11, 0), room_id="r1"
    )
    assert check["conflicts"][0]["kinds"] == ["ROOM"]  # MATH 6e A is in R12 on Monday 08-10
    assert explain_conflicts(check["conflicts"]) == "salle déjà occupée — lundi 08:00–10:00"
    with pytest.raises(Conflict) as exc:
        planning.create_slot(
            course_id=backend.c_fr, weekday=1, start_time=time(9, 0), end_time=time(11, 0), room_id="r1"
        )
    assert exc.value.rule == "planning_conflict"
    from school_admin.messages import explain

    assert explain(exc.value) == (
        "Ce créneau entre en conflit avec le planning existant. Salle déjà occupée — lundi 08:00–10:00."
    )
    ok = planning.create_slot(course_id=backend.c_fr, weekday=2, start_time=time(8, 0), end_time=time(9, 0))
    assert ok.when == "Mardi 08:00–09:00"


def test_session_actions(planning, backend):
    math = planning.week(MONDAY)[0]
    moved = planning.move(
        math.id, new_start=datetime(2026, 3, 3, 14, 0), new_end=datetime(2026, 3, 3, 16, 0), reason="Sortie"
    )
    assert (moved.date, moved.hours, moved.is_moved) == (date(2026, 3, 3), "14:00–16:00", True)
    assert planning.change_room(math.id, "r2", "Travaux").room_code == "LAB"
    substituted = planning.substitute(math.id, backend.tf, "Absence")
    assert (substituted.teacher_name, substituted.planned_teacher_name, substituted.is_substituted) == (
        "Marie Ngo",
        "Jean Mbarga",
        True,
    )
    assert planning.restore_teacher(math.id, "Retour").is_substituted is False
    with pytest.raises(ValidationFailed) as exc:
        planning.restore_teacher(math.id, "Encore")
    assert exc.value.rule == "not_substituted"
    with pytest.raises(ValidationFailed):
        planning.cancel(math.id, "  ")  # a reason is required (refused before any call)
    assert planning.cancel(math.id, "Grève").status == "CANCELLED"
    with pytest.raises(ValidationFailed) as exc:
        planning.cancel(math.id, "Encore")
    assert exc.value.rule == "session_not_scheduled"
    backend.incompatible_substitutes.add(backend.tm)
    fr = planning.week(MONDAY)[1]
    with pytest.raises(ValidationFailed) as exc:
        planning.substitute(fr.id, backend.tm, "Absence")
    assert exc.value.rule == "teacher_incompatible"
    with pytest.raises(NotFound):
        planning.cancel("another-school-session", "x")


def test_generation_requests_breaks_and_permissions(planning, backend):
    summary = planning.generate(date_from=date(2026, 3, 9), date_to=date(2026, 3, 15))
    assert (summary["created"], summary["existing"]) == (2, 0)
    assert planning.generate(date_from=date(2026, 3, 9), date_to=date(2026, 3, 15))["existing"] == 2  # idempotent
    pending = planning.requests()
    assert [r.reason for r in pending] == ["Rendez-vous médical"]
    assert [s.code for s in planning.impacted(pending[0].id)] == ["MATH — 6e A"]
    request, impacted = planning.decide(pending[0].id, "APPROVED", "Bon rétablissement")
    assert request.status == "APPROVED" and len(impacted) == 1
    with pytest.raises(Conflict) as exc:
        planning.decide(pending[0].id, "REJECTED")
    assert exc.value.rule == "already_decided"
    created = planning.create_break(
        year_id="y1", name="Examens", start=datetime(2026, 6, 1), end=datetime(2026, 6, 5, 18), break_type="EXAM"
    )
    assert (
        planning.update_break(
            created.id,
            name="Examens blancs",
            start=created.start,
            end=created.end,
            break_type="EXAM",
            affects_scheduling=False,
        ).name
        == "Examens blancs"
    )
    backend.roles = ["TEACHER"]  # the role changed on the server
    with pytest.raises(Forbidden):
        planning.generate(date_from=MONDAY, date_to=MONDAY)


# =============================================================================
# Dialogs
# =============================================================================


def test_slot_dialog_shows_the_server_verdict(qapp, planning, backend):
    from school_admin.services.courses import CourseService

    courses = CourseService(planning.api).all()
    asked = []
    dialog = SlotDialog(
        courses,
        planning.rooms(active=True),
        lambda payload, done: (asked.append(payload), done(planning.check_slot(**payload))),
    )
    dialog.course.setCurrentIndex(dialog.course.findData(backend.c_fr))
    dialog.weekday.setCurrentIndex(0)  # Monday
    dialog.room.setCurrentIndex(dialog.room.findData("r1"))
    dialog.check_button.click()
    assert asked and asked[0]["weekday"] == 1  # the server is asked
    assert dialog.verdict.property("kind") == "warning" and "salle déjà occupée" in dialog.verdict.text()
    dialog.weekday.setCurrentIndex(1)
    dialog.check_button.click()
    assert dialog.verdict.property("kind") == "success"
    dialog.end_time.setTime(dialog.start_time.time())
    assert not dialog.save_enabled and "heure de fin" in dialog.status.text()


def test_session_dialog_actions_follow_the_session_state(qapp, planning):
    session = planning.week(MONDAY)[0]
    dialog = SessionDialog(session)
    assert dialog.buttons["cancel"].isEnabled() and not dialog.buttons["restore"].isEnabled()
    texts = " ".join(label.text() for label in dialog.content.findChildren(type(dialog.status)))
    for expected in ("Enseignant prévu", "Enseignant réel", "R12", "08:00–10:00", "Planifiée"):
        assert expected in texts
    dialog.buttons["move"].click()
    assert dialog.action == "move"


# =============================================================================
# Page
# =============================================================================


@pytest.fixture
def controller(qapp, api, auth, backend):
    backend.seed_planning()
    ctrl = AppController(api, auth, ImmediateRunner(), AppConfig(api_url="http://testserver/api/v1/"))
    ctrl.confirmations = []
    ctrl.page_options = {"planning": {"today": lambda: date(2026, 3, 4)}}
    yield ctrl
    if ctrl.main_window is not None:
        ctrl.main_window.close()
    ctrl.login_window.close()


def open_planning(ctrl):
    window = ctrl.login_window
    window.identifier.setText("admin")
    window.password.setText(PASSWORD)
    window.attempt()
    return ctrl.main_window, ctrl.main_window.open("planning")


def test_navigation_week_view_and_filters(controller, backend):
    shell, page = open_planning(controller)
    labels = [shell.nav.item(i).text() for i in range(shell.nav.count())]
    assert "Planning" in labels and "Planning   ·  Bientôt" not in labels
    assert [page.tabs.tabText(i) for i in range(page.tabs.count())] == [
        "Semaine",
        "Créneaux",
        "Salles",
        "Disponibilités",
        "Vacances",
    ]
    week = page.week
    assert week.week_label.text() == "Semaine du 02/03 au 08/03/2026"
    assert [s.code for s in week.sessions] == ["MATH — 6e A", "FR — 5e A"] and week.count_label.text() == "2 séances"
    week.teacher_filter.setCurrentIndex(week.teacher_filter.findData(backend.tf))
    assert [s.code for s in week.sessions] == ["FR — 5e A"]
    week.teacher_filter.setCurrentIndex(0)
    week.next_button.click()
    assert week.sessions == [] and week.week_label.text() == "Semaine du 09/03 au 15/03/2026"
    week.today_button.click()
    assert len(week.sessions) == 2
    week.toggle_view()
    assert week.table.rowCount() == 2 and week.table.item(0, 6).text() == "Planifiée"


def test_week_click_selects_and_actions(controller, backend):
    shell, page = open_planning(controller)
    week = page.week
    shell.resize(QSize(1366, 768))
    shell.show()
    QTest.qWaitForWindowExposed(shell)
    week.week.repaint()
    rect, session = next((r, s) for r, s in week.week.blocks if s.subject_code == "MATH")
    QTest.mouseClick(week.week, Qt.LeftButton, pos=rect.center().toPoint())
    assert week.current().id == session.id and week.session_button.isEnabled()
    answers = {"substitute": {"teacher_id": backend.tf, "reason": "Absence"}}
    week.ask = lambda kind, **context: answers.get(kind)
    week.session_action("substitute")
    assert week.banner.plain_text() == "Enseignant remplacé pour cette séance."
    assert week.current().is_substituted and week.current().teacher_name == "Marie Ngo"
    answers["move"] = {
        "new_start": datetime(2026, 3, 9, 8, 0),
        "new_end": datetime(2026, 3, 9, 10, 0),
        "reason": "Report",
    }
    week.session_action("move")
    assert week.week_label.text() == "Semaine du 09/03 au 15/03/2026"  # follows the moved session
    assert [s.date for s in week.sessions] == [date(2026, 3, 9)]
    answers["cancel"] = {"reason": "Grève"}
    week.session_action("cancel")
    assert week.current().status == "CANCELLED" and week.banner.plain_text() == "Séance annulée."
    assert week.session_button.menu().actions()[0].isEnabled() is False  # nothing left to do on it
    shell.close()


def test_week_conflict_is_explained_not_hidden(controller, backend):
    _, page = open_planning(controller)
    week = page.week
    week.select(next(s.id for s in week.sessions if s.subject_code == "FR"))
    week.ask = lambda kind, **c: {
        "new_start": datetime(2026, 3, 2, 8, 0),
        "new_end": datetime(2026, 3, 2, 9, 0),
        "reason": "Essai",
    }
    for row in backend.teaching_sessions.values():  # both courses now share the 6e A class
        row["_class"] = backend._class("6e A")
    week.session_action("move")
    assert week.banner.property("kind") == "warning"
    assert week.banner.plain_text().startswith("Impossible de déplacer la séance — Ce créneau entre en conflit")
    assert "Classe déjà occupée — le 02/03 08:00–10:00" in week.banner.plain_text()


def test_generate_from_the_week(controller, backend):
    _, page = open_planning(controller)
    week = page.week
    week.ask = lambda kind, **c: {"date_from": date(2026, 3, 9), "date_to": date(2026, 3, 15), "class_id": None}
    week.generate()
    assert week.banner.plain_text() == "2 séance(s) créée(s), 0 déjà présente(s)."


def test_slots_tab_check_end_reschedule(controller, backend):
    _, page = open_planning(controller)
    slots = page.open_tab("slots")
    assert [slots.table.item(r, 0).text() for r in range(slots.table.rowCount())] == [
        "FR — Français",  # sorted by the catalog
        "MATH — Mathématiques",
    ]
    slots.ask = lambda kind, **c: {
        "course_id": backend.c_fr,
        "weekday": 1,
        "start_time": time(9, 0),
        "end_time": time(11, 0),
        "room_id": "r1",
        "effective_from": None,
        "effective_to": None,
    }
    slots.add()
    assert (
        slots.banner.property("kind") == "warning"
        and "Salle déjà occupée — lundi 08:00–10:00" in slots.banner.plain_text()
    )
    slots.table.selectRow(0)
    slots.ask = lambda kind, **c: {"last_date": date(2026, 6, 30), "reason": "Fin du module"}
    slots.end_slot()
    assert slots.banner.plain_text().startswith("Créneau « FR — 5e A · Mercredi 10:00–12:00 » terminé")
    slots.table.selectRow(0)
    slots.ask = lambda kind, **c: {
        "from_date": date(2026, 4, 1),
        "weekday": 2,
        "start_time": time(8, 0),
        "end_time": time(10, 0),
        "room_id": None,
        "reason": "Nouvel horaire",
    }
    slots.reschedule()
    assert "reprogrammé" in slots.banner.plain_text()


def test_rooms_tab(controller, backend):
    _, page = open_planning(controller)
    rooms = page.open_tab("rooms")
    assert [rooms.table.item(r, 0).text() for r in range(rooms.table.rowCount())] == ["LAB", "R12"]
    rooms.ask = lambda kind, **c: {
        "code": "R20",
        "name": "Salle 20",
        "room_type": "CLASSROOM",
        "capacity": 35,
        "bench_count": 18,
    }
    rooms.add()
    assert rooms.banner.plain_text() == "Salle « R20 » créée avec succès."
    backend.rooms_in_use.add("r1")
    rooms.table.selectRow([rooms.table.item(r, 0).text() for r in range(rooms.table.rowCount())].index("R12"))
    rooms.confirm = lambda *a, **k: True
    rooms.toggle()
    assert (
        rooms.banner.property("kind") == "warning" and "encore utilisée par des créneaux" in rooms.banner.plain_text()
    )
    rooms.ask = lambda kind, **c: {"class_id": backend._class("6e B"), "room_id": "r2"}
    rooms.main_room()
    assert rooms.banner.plain_text() == "Salle principale enregistrée."
    assert backend.classes[backend._class("6e B")]["main_room"] == "r2"


def test_requests_and_breaks_tabs(controller, backend):
    _, page = open_planning(controller)
    requests = page.open_tab("requests")
    assert requests.table.item(0, 0).text() == "Mbarga Jean (ENS-001)" and requests.table.item(0, 3).text() == (
        "Rendez-vous médical"
    )
    requests.table.selectRow(0)
    requests.show_impacted()
    assert requests.banner.plain_text() == "Séances impactées (1) — 02/03 08:00–10:00 MATH — 6e A"
    seen = {}

    def decide(kind, **context):
        seen["impacted"] = [s.code for s in context["impacted"]]
        return {"decision": "APPROVED", "comment": None}

    requests.ask = decide
    requests.decide()
    assert seen["impacted"] == ["MATH — 6e A"]
    assert requests.banner.plain_text() == "Demande validée. 1 séance(s) à réorganiser."
    breaks = page.open_tab("breaks")
    assert (
        breaks.table.item(0, 0).text() == "Vacances de Pâques" and breaks.table.item(0, 2).text() == "06/04/2026 00:00"
    )
    breaks.table.selectRow(0)
    breaks.ask = lambda years, school_break=None: {
        "year_id": "y1",
        "name": "Vacances de printemps",
        "break_type": "HOLIDAY",
        "start": datetime(2026, 4, 6),
        "end": datetime(2026, 4, 20, 23, 59),
        "affects_scheduling": True,
    }
    breaks.edit()
    assert breaks.banner.plain_text() == "Interruption « Vacances de printemps » modifiée avec succès."


@pytest.mark.parametrize("size", [QSize(1366, 768), QSize(1280, 720), QSize(1024, 768)])
def test_planning_toolbars_fit(controller, size):
    shell, page = open_planning(controller)
    shell.resize(size)
    shell.show()
    QTest.qWaitForWindowExposed(shell)
    week = page.week
    rows = (
        [week.previous_button, week.today_button, week.next_button],
        [week.class_filter, week.teacher_filter, week.room_filter, week.subject_filter],
        [week.generate_button, week.slot_button, week.session_button],
    )
    for row in rows:
        for left, right in zip(row, row[1:], strict=False):
            assert left.geometry().right() < right.geometry().left()
        for widget in row:
            assert widget.isVisible() and week.rect().contains(widget.mapTo(week, widget.rect().bottomRight()))
    for name in ("slots", "rooms", "requests", "breaks"):
        tab = page.open_tab(name)
        QTest.qWait(10)
        visible = [b for b in (tab.refresh_button, tab.edit_button, tab.toggle_button, tab.add_button) if b.isVisible()]
        for left, right in zip(visible, visible[1:], strict=False):
            assert left.geometry().right() < right.geometry().left(), name
    shell.close()


# =============================================================================
# Branding: School Managing for the software, never the school's
# =============================================================================


def test_software_brand_in_login_sidebar_and_about(controller, qapp):
    login = controller.login_window
    assert login.brand.property("software_brand") and login.brand.text() == "School Managing"
    assert login.windowTitle() == "School Managing — Connexion"
    shell, _ = open_planning(controller)
    assert shell.brand.property("software_brand") and shell.brand.text() == "School Managing"
    assert shell.windowTitle() == "School Managing — École Test"  # the school's name stays in the header
    from school_admin.ui.dialogs.about_dialog import AboutDialog

    about = AboutDialog(shell)
    assert about.brand.property("software_brand") and "logo et les couleurs de l'établissement" in " ".join(
        label.text() for label in about.content.findChildren(type(about.status))
    )


def test_brand_files_are_loaded_once_from_the_assets(qapp, tmp_path, monkeypatch):
    from PySide6.QtGui import QColor, QImage

    monkeypatch.setattr(branding, "BRAND_DIR", tmp_path)
    assert branding.brand_file("horizontal") is None and branding.brand_mark().property("brand_source") == "text"
    image = QImage(240, 60, QImage.Format_ARGB32)
    image.fill(QColor("#1D4ED8"))
    image.save(str(tmp_path / "logo-horizontal.png"))
    image.save(str(tmp_path / "app-icon.png"))
    mark = branding.brand_mark("horizontal", 40)
    assert mark.property("brand_source") == "file" and mark.pixmap().height() == 40
    assert not branding.software_icon().isNull()


def test_software_brand_never_depends_on_the_school(qapp):
    """The software's identity is built without any school data."""
    import inspect

    source = inspect.getsource(branding)
    assert "school" not in source.split('"""', 2)[2].lower().replace("school managing", "").replace("school_admin", "")
    assert branding.brand_mark().text() == "School Managing"


def test_week_view_point_hit(qapp, planning):
    from school_admin.ui.week_view import WeekView

    view = WeekView()
    view.resize(800, 600)
    view.set_week(MONDAY, planning.week(MONDAY))
    view.grab()  # paints and lays the blocks out
    rect, session = view.blocks[0]
    assert view.session_at(rect.center()) is session and view.session_at(QPointF(5, 5)) is None


# =============================================================================
# Teacher presence (payroll API: self-reported on mobile, verified here)
# =============================================================================


def test_presence_actions_follow_the_session_state(qapp, planning):
    from dataclasses import replace

    from school_admin.ui.dialogs.planning_dialogs import action_allowed

    session = planning.week(MONDAY)[0]  # 02/03/2026: over
    assert action_allowed("validate", session) and action_allowed("reject", session)
    before = session.start.replace(hour=7)  # the session has not ended yet
    assert not action_allowed("validate", session, now=before) and not action_allowed("reject", session, now=before)
    done = replace(session, status="COMPLETED")
    assert not action_allowed("validate", done) and action_allowed("reject", done)  # correction still possible
    cancelled = replace(session, status="CANCELLED")
    assert not action_allowed("validate", cancelled) and not action_allowed("reject", cancelled)
    dialog = SessionDialog(session)
    assert dialog.buttons["validate"].isEnabled() and dialog.buttons["reject"].isEnabled()


def test_presence_service_relays_the_server(planning, backend):
    session = planning.week(MONDAY)[0]
    with pytest.raises(ValidationFailed):
        planning.reject_presence(session.id, "  ")  # a reason is required, before any call
    assert backend.verifications == []
    planning.validate_presence(session.id)
    assert backend.verifications == [("validate", session.id, None)]  # no empty comment sent
    with pytest.raises(ApiError, match="Déjà validée"):
        planning.validate_presence(session.id)  # the server refuses a second validation


def test_teacher_presence_validated_then_corrected_from_the_week(controller, backend):
    shell, page = open_planning(controller)
    week = page.week
    session = next(s for s in week.sessions if s.subject_code == "MATH")
    week.select(session.id)
    answers = {"validate": {"reason": ""}}
    week.ask = lambda kind, **context: answers.get(kind)
    week.session_action("validate")
    assert week.banner.plain_text() == "Présence validée : la séance est réalisée et payable."
    assert week.current().status == "COMPLETED"
    names = [name for name, _ in SessionDialog.ACTIONS]
    menu = dict(zip(names, week.session_button.menu().actions(), strict=True))
    assert not menu["validate"].isEnabled() and menu["reject"].isEnabled() and not menu["move"].isEnabled()
    answers["reject"] = {"reason": "Enseignant absent, non remplacé"}
    week.session_action("reject")
    assert week.banner.plain_text() == "Séance marquée non assurée : elle ne sera pas payée."
    assert week.current().status == "SCHEDULED"
    assert backend.verifications == [
        ("validate", session.id, None),
        ("reject", session.id, "Enseignant absent, non remplacé"),
    ]
