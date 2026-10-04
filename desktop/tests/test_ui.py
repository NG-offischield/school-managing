"""Screens driven headless (QT_QPA_PLATFORM=offscreen) with the synchronous
runner and the fake backend: login -> dashboard -> categories -> subjects ->
logout, plus the 401 / 403 / 404 / 409 behaviours."""

import pytest
from PySide6.QtWidgets import QApplication

from school_admin.config import AppConfig
from school_admin.ui.app import AppController
from school_admin.ui.dialogs.subject_dialog import SubjectDialog
from school_admin.ui.tasks import ImmediateRunner

from .fake_backend import PASSWORD, fail


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def controller(qapp, api, auth):
    ctrl = AppController(api, auth, ImmediateRunner(), AppConfig(api_url="http://testserver/api/v1/"))
    ctrl.confirmations = []

    def confirm(_parent, title, text):
        ctrl.confirmations.append(title)
        return ctrl.confirm_answer

    ctrl.confirm_answer = True
    ctrl.page_options = {"categories": {"confirm": confirm}, "subjects": {"confirm": confirm}}
    yield ctrl
    if ctrl.main_window is not None:
        ctrl.main_window.close()
    ctrl.login_window.close()


def login(ctrl, password=PASSWORD):
    window = ctrl.login_window
    window.identifier.setText("admin")
    window.password.setText(password)
    window.attempt()
    return ctrl.main_window


def test_login_screen_states_and_errors(controller):
    window = controller.login_window
    assert not window.submit.isEnabled()  # empty form
    assert login(controller, "wrong") is None
    assert not window.banner.isHidden() and window.banner.text() == "Identifiants invalides."
    assert window.password.text() == ""  # never kept in the form
    shell = login(controller)
    assert shell is not None and shell.current_page is shell.pages["dashboard"]


def test_shell_header_navigation_and_dashboard(controller):
    shell = login(controller)
    assert "École Test" in shell.school_label.text() and "Ada Admin" in shell.user_label.text()
    dashboard = shell.pages["dashboard"]
    values = {card.value.text() for card in dashboard.cards}
    assert {"2025-2026", "4", "120", "9", "37", "Indisponible"} <= values
    # Future modules are reserved, not faked.
    assert type(shell.pages["finance"]).__name__ == "PlaceholderPage"


def test_categories_add_edit_deactivate_reactivate(controller, backend):
    shell = login(controller)
    page = shell.open("categories")
    page.open_dialog = lambda category=None: {"code": "SCI", "name": "Scientifique", "description": "Maths"}
    page.add()
    assert [page.table.item(r, 0).text() for r in range(page.table.rowCount())] == ["SCI"]
    assert page.banner.kind == "success"
    page.table.selectRow(0)
    page.open_dialog = lambda category=None: {"code": category.code, "name": "Sciences", "description": ""}
    page.edit()
    assert page.table.item(0, 1).text() == "Sciences"
    controller.confirm_answer = False
    page.table.selectRow(0)
    page.toggle()  # cancelled confirmation: nothing sent
    assert ("POST", f"pedagogical-categories/{page.rows[0].id}/deactivate/") not in backend.calls
    controller.confirm_answer = True
    page.table.selectRow(0)
    page.toggle()
    assert controller.confirmations[-1] == "Désactiver la catégorie"
    page.status.setCurrentIndex(1)  # "Inactives"
    page.table.selectRow(0)
    assert page.table.item(0, 3).text() == "Inactive" and page.toggle_button.text() == "Réactiver"
    page.table.selectRow(0)
    page.toggle()  # reactivation needs no confirmation
    page.status.setCurrentIndex(0)
    assert page.table.item(0, 3).text() == "Active"


def test_search_filters_the_list(controller, backend):
    backend.add_category("SCI", "Scientifique")
    backend.add_category("LIT", "Littéraire")
    page = login(controller).open("categories")
    page.search.setText("litt")
    page.reload()
    assert [page.table.item(r, 0).text() for r in range(page.table.rowCount())] == ["LIT"]


def test_subject_requires_a_category_from_the_list(controller, backend, qapp):
    backend.add_category("SCI", "Scientifique")
    backend.add_category("OLD", "Ancienne", active=False)
    page = login(controller).open("subjects")
    offered = {}

    def dialog_values(categories, subject=None):
        dialog = SubjectDialog(categories)
        offered["labels"] = [dialog.category.itemText(i) for i in range(dialog.category.count())]
        dialog.code.setText("MATH")
        dialog.name.setText("Mathématiques")
        offered["without_category"] = dialog.save_enabled
        assert not dialog.category.isEditable()  # no free text
        dialog.category.setCurrentIndex(1)
        offered["with_category"] = dialog.save_enabled
        return dialog.values()

    page.open_dialog = dialog_values
    page.add()
    assert offered["labels"] == ["— Choisir une catégorie —", "SCI — Scientifique"]  # active ones only
    assert (offered["without_category"], offered["with_category"]) == (False, True)
    assert page.table.item(0, 0).text() == "MATH" and page.table.item(0, 2).text() == "SCI — Scientifique"
    # The filter offers the categories; filtering by another one empties the list.
    assert page.category_filter.count() == 3


@pytest.mark.parametrize(
    ("status", "code", "kind", "title"),
    [
        (403, "PERMISSION_DENIED", "error", "Permission refusée"),
        (404, "NOT_FOUND", "warning", "Ressource indisponible"),
        (409, "CONFLICT", "warning", "Conflit"),
    ],
)
def test_errors_are_explained(controller, backend, status, code, kind, title):
    page = login(controller).open("categories")
    backend.forced[("POST", "pedagogical-categories/")] = fail(status, code, "Message du serveur.")
    page.open_dialog = lambda category=None: {"code": "SCI", "name": "Scientifique", "description": ""}
    page.add()
    assert page.banner.kind == kind and page.banner.text().startswith(f"{title} — Message du serveur.")
    assert controller.main_window is not None  # stays in the shell


def test_offline_is_explained(controller, backend):
    page = login(controller).open("categories")
    backend.offline = True
    page.reload()
    assert page.banner.kind == "error" and "Hors ligne" in page.banner.text()


def test_expired_session_returns_to_login(controller, backend):
    shell = login(controller)
    backend.expire_access_tokens()
    backend.revoked |= backend.refresh_tokens  # refresh impossible too
    shell.open("categories")
    assert controller.main_window is None and not controller.login_window.isHidden()
    assert "expiré" in controller.login_window.banner.text()


def test_logout_returns_to_login_and_revokes(controller, backend, api):
    shell = login(controller)
    shell.logout_button.click()
    assert controller.main_window is None and api.access_token is None
    assert backend.revoked and "déconnecté" in controller.login_window.banner.text()
