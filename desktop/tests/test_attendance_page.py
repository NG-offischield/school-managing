"""Vie scolaire → Présences (desktop): the day's attendance and the gate
passages, read only; guardians created through the server and activated /
suspended with the EXISTING account endpoints. Widget tests against the fake
backend (tests/fake_attendance.py), not E2E."""

import pytest
from PySide6.QtCore import QDate, QSize
from PySide6.QtTest import QTest

from .fake_attendance import TODAY
from .test_communication_documents import _fits, column, controller, open_module  # noqa: F401 (fixture)

DAY = QDate.fromString(TODAY, "yyyy-MM-dd")


def open_attendance(ctrl, tab):
    shell, page = open_module(ctrl, "attendance")
    view = page.open_tab(tab)
    if hasattr(view, "day"):
        view.day.setDate(DAY)
    return shell, page, view


def test_navigation_entry_is_now_available(controller, backend):  # noqa: F811
    shell, page = open_module(controller, "attendance")
    labels = [shell.nav.item(i).text() for i in range(shell.nav.count())]
    assert "Présences" in labels and not any("Présences" in label and "Bientôt" in label for label in labels)
    assert [page.tabs.tabText(i) for i in range(page.tabs.count())] == [
        "Présences du jour",
        "Passages au portail",
        "Codes QR",
        "Gardiens",
    ]


def test_daily_attendance_is_read_only_and_filtered(controller, backend):  # noqa: F811
    _, _, daily = open_attendance(controller, "daily")
    # computed by the server: no add / edit, only an audited correction
    assert not daily.add_button.isVisible() and not daily.edit_button.isVisible()
    assert sorted(column(daily.table, 0)) == ["Awa Ndiaye", "Bruno Ekane", "Paul Kamga"]
    row = column(daily.table, 0).index("Paul Kamga")
    assert daily.table.item(row, 3).text() == "07:48" and daily.table.item(row, 4).text() == "18 min"
    assert daily.table.item(row, 5).text() == "En retard"
    daily.status.setCurrentIndex(daily.status.findData("ABSENT"))
    assert column(daily.table, 0) == ["Bruno Ekane"]
    daily.status.setCurrentIndex(0)
    # The day chosen in the date filter is what the server is asked for.
    assert any(p == "admin/attendance/daily/" and q.get("date") == TODAY for p, q in backend.attendance_queries)


def test_scans_of_one_guardian(controller, backend):  # noqa: F811
    _, page, scans = open_attendance(controller, "scans")
    assert scans.table.rowCount() == 2 and set(column(scans.table, 3)) == {"Accepté (arrivée)", "QR inconnu"}
    guardians = page.open_tab("guardians")
    guardians.table.selectRow(0)
    guardians.open_scans()
    assert page.tabs.currentWidget() is scans
    assert scans.guardian_filter.currentText() == "Moussa Bello (G-01)"
    gid = scans.guardian_filter.currentData()
    assert any(p == "admin/scans/" and q.get("guardian") == gid for p, q in backend.attendance_queries)


def test_create_activate_suspend_reactivate_a_guardian(controller, backend):  # noqa: F811
    _, page = open_module(controller, "attendance")
    guardians = page.open_tab("guardians")
    guardians.open_dialog = lambda: {
        "first_name": "Ali",
        "last_name": "Kamga",
        "email": "ali@ecole.test",
        "guardian_number": "G-02",
        "phone": "",
    }
    guardians.add()
    assert guardians.banner.plain_text() == "Gardien « Ali Kamga » créé avec succès."
    row = column(guardians.table, 0).index("Ali Kamga")
    assert guardians.table.item(row, 5).text() == "À activer"
    guardians.table.selectRow(row)
    assert guardians.code_button.isEnabled() and guardians.suspend_button.isEnabled()
    shown = {}
    guardians.show_code = lambda guardian, issued: shown.update(name=guardian.name, code=issued.code)
    guardians.issue_code()
    assert shown["name"] == "Ali Kamga" and shown["code"]
    assert shown["code"] not in guardians.banner.plain_text()  # the code is never written in the banner
    guardians.ask_suspend = lambda *a, **k: {"reason": "Fin de contrat"}
    guardians.table.selectRow(column(guardians.table, 0).index("Ali Kamga"))
    guardians.suspend()
    row = column(guardians.table, 0).index("Ali Kamga")
    assert guardians.table.item(row, 5).text() == "Suspendu"
    guardians.table.selectRow(row)
    assert guardians.enable_button.isEnabled() and not guardians.suspend_button.isEnabled()
    guardians.enable()
    assert guardians.banner.plain_text() == "Compte de Ali Kamga réactivé."


def test_duplicate_number_is_explained(controller, backend):  # noqa: F811
    _, page = open_module(controller, "attendance")
    guardians = page.open_tab("guardians")
    guardians.open_dialog = lambda: {
        "first_name": "X",
        "last_name": "Y",
        "email": "x@ecole.test",
        "guardian_number": "G-01",
        "phone": "",
    }
    guardians.add()
    assert guardians.banner.kind in ("warning", "error") and guardians.banner.plain_text()
    assert len(backend.guardians) == 1


@pytest.mark.parametrize("size", [QSize(1366, 768), QSize(1280, 720), QSize(1024, 768)])
@pytest.mark.parametrize("tab", ["daily", "scans", "codes", "guardians"])
def test_attendance_tabs_fit(controller, backend, size, tab):  # noqa: F811
    shell, _, view = open_attendance(controller, tab)
    if tab == "codes":  # the list exists once a class is chosen (before: the empty state)
        view.class_filter.setCurrentIndex(view.class_filter.findText("6e A"))
    shell.resize(size)
    shell.show()
    QTest.qWaitForWindowExposed(shell)
    _fits(view, tab)
    shell.close()


# =============================================================================
# Correction (POST admin/attendance/{id}/correct/, reason mandatory, audited)
# =============================================================================


def test_correction_needs_a_reason_and_the_server_decides_late_or_present(controller, backend):  # noqa: F811
    from school_admin.ui.pages.attendance_page import CorrectionDialog

    _, _, daily = open_attendance(controller, "daily")
    row = column(daily.table, 0).index("Bruno Ekane")
    daily.table.selectRow(row)
    assert daily.correct_button.isEnabled()
    record = daily.selected()
    dialog = CorrectionDialog(record)
    assert not dialog.save_enabled  # no reason yet
    dialog.target.setCurrentIndex(dialog.target.findData("PRESENT"))
    assert dialog.arrival.isEnabled()
    dialog.reason.setPlainText("Arrivé avec sa mère, carte oubliée")
    assert dialog.save_enabled
    values = dialog.values()
    assert values["status"] == "PRESENT" and values["arrival"].strftime("%H:%M") == "07:30"
    dialog.close()
    from datetime import time

    daily.open_correction = lambda _record: {"status": "PRESENT", "reason": "Carte oubliée", "arrival": time(7, 45)}
    daily.correct()
    assert backend.corrections[-1] == {
        "status": "PRESENT",
        "reason": "Carte oubliée",
        "arrival_time": f"{TODAY}T07:45:00",  # local time of that day, sent as entered
    }
    row = column(daily.table, 0).index("Bruno Ekane")
    assert daily.table.item(row, 5).text() == "En retard"  # 07:45 after 07:30: the server says late
    assert daily.banner.plain_text() == "Correction de Bruno Ekane enregistrée."
    daily.table.selectRow(row)
    daily.open_correction = lambda _record: {"status": "EXCUSED", "reason": "Certificat médical", "arrival": None}
    daily.correct()
    assert backend.corrections[-1] == {"status": "EXCUSED", "reason": "Certificat médical"}  # no arrival time
    row = column(daily.table, 0).index("Bruno Ekane")
    assert daily.table.item(row, 5).text() == "Absence justifiée" and daily.table.item(row, 3).text() == "—"


def test_correction_without_reason_never_reaches_the_server(controller, backend):  # noqa: F811
    _, _, daily = open_attendance(controller, "daily")
    daily.table.selectRow(0)
    daily.open_correction = lambda _record: {"status": "ABSENT", "reason": " ", "arrival": None}
    daily.correct()
    assert backend.corrections == [] and daily.banner.isVisible()


# =============================================================================
# Annual QR codes (admin/qr-codes/: issue, issue-class, reissue, revoke)
# =============================================================================


def open_codes(ctrl, class_name):
    _, _, codes = open_attendance(ctrl, "codes")
    codes.class_filter.setCurrentIndex(codes.class_filter.findText(class_name))
    return codes


def select(codes, name):
    row = column(codes.table, 0).index(name)
    codes.table.selectRow(row)
    return row


def test_qr_codes_issue_reissue_and_revoke_with_history(controller, backend):  # noqa: F811
    _, _, codes = open_attendance(controller, "codes")
    assert codes.table.rowCount() == 0 and not codes.class_button.isEnabled()  # a class first
    codes.class_filter.setCurrentIndex(codes.class_filter.findText("6e A"))
    row = select(codes, "Ndiaye Awa")
    assert codes.table.item(row, 4).text() == "Aucun code"
    assert codes.issue_button.isEnabled() and not codes.revoke_button.isEnabled()
    codes.open_row()  # double-click / Entrée on a pupil without a code = « Émettre »
    row = select(codes, "Ndiaye Awa")
    assert codes.table.item(row, 2).text() == "V1" and codes.table.item(row, 4).text() == "Actif"
    assert codes.banner.plain_text() == "Code QR émis pour Ndiaye Awa."
    asked = []
    codes.ask = lambda _parent, title, text, **options: asked.append(title) or {"reason": "Carte perdue"}
    codes.reissue()
    assert asked == ["Réémettre le code de Ndiaye Awa ?"]
    row = select(codes, "Ndiaye Awa")
    assert codes.table.item(row, 2).text() == "V2" and codes.table.item(row, 4).text() == "Actif"
    history = sorted((q["version"], q["status"]) for q in backend.qr_codes.values())
    assert history == [(1, "REVOKED"), (2, "ACTIVE")]  # the old card no longer passes, kept in history
    codes.ask = lambda *_args, **_options: {"reason": "Élève exclu temporairement"}
    codes.revoke()
    row = select(codes, "Ndiaye Awa")
    assert codes.table.item(row, 4).text() == "Révoqué" and codes.issue_button.isEnabled()  # a new code may follow
    assert all(q["status"] == "REVOKED" for q in backend.qr_codes.values())
    # the token itself is never shown on this screen
    texts = [codes.table.item(r, c).text() for r in range(codes.table.rowCount()) for c in range(5)]
    assert not any(q["token"] in t for q in backend.qr_codes.values() for t in texts)


def test_qr_codes_for_a_whole_class_and_filters(controller, backend):  # noqa: F811
    backend.add_student(
        "MAT-010", "Abena", "Zoé", "F", class_id=next(cid for cid, c in backend.classes.items() if c["name"] == "6e A")
    )
    codes = open_codes(controller, "6e A")
    pupils = codes.table.rowCount()
    assert pupils >= 2 and codes.class_button.isEnabled()
    codes.issue_class()
    assert set(column(codes.table, 4)) == {"Actif"}
    assert codes.banner.plain_text() == f"{pupils} code(s) actif(s) pour la classe 6e A."
    codes.issue_class()  # idempotent: nothing new
    assert len(backend.qr_codes) == pupils
    codes.status.setCurrentIndex(codes.status.findData("NONE"))
    assert codes.table.rowCount() == 0
    codes.status.setCurrentIndex(0)
    codes.search.setText("zoé")
    codes.reload()
    assert column(codes.table, 0) == ["Abena Zoé"]


def test_qr_code_refused_for_a_pupil_not_enrolled(controller, backend):  # noqa: F811
    from school_admin.api.errors import ApiError
    from school_admin.services.attendance import AttendanceService

    service = AttendanceService(controller.api)
    with pytest.raises(ApiError):
        service.issue_code(backend.chloe)  # no class this year: the server refuses
    assert backend.qr_codes == {}
