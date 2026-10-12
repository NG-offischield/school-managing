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
        "Gardiens",
    ]


def test_daily_attendance_is_read_only_and_filtered(controller, backend):  # noqa: F811
    _, _, daily = open_attendance(controller, "daily")
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
@pytest.mark.parametrize("tab", ["daily", "scans", "guardians"])
def test_attendance_tabs_fit(controller, backend, size, tab):  # noqa: F811
    shell, _, view = open_attendance(controller, tab)
    shell.resize(size)
    shell.show()
    QTest.qWaitForWindowExposed(shell)
    _fits(view, tab)
    shell.close()
