"""Screens driven headless (QT_QPA_PLATFORM=offscreen) with the synchronous
runner and the fake backend: login -> dashboard -> categories -> subjects ->
logout, plus the 401 / 403 / 404 / 409 behaviours and the user messages."""

import pytest
from PySide6.QtCore import Qt

from school_admin.config import AppConfig
from school_admin.ui.app import AppController
from school_admin.ui.dialogs.subject_dialog import SubjectDialog
from school_admin.ui.tasks import ImmediateRunner

from .fake_backend import PASSWORD, fail


@pytest.fixture
def controller(qapp, api, auth):
    ctrl = AppController(api, auth, ImmediateRunner(), AppConfig(api_url="http://testserver/api/v1/"))
    ctrl.confirmations = []

    def confirm(_parent, title, text, **options):
        ctrl.confirmations.append((title, options))
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


def codes(page):
    return [page.table.item(r, 0).text() for r in range(page.table.rowCount())]


def test_login_screen_states_and_errors(controller):
    window = controller.login_window
    assert not window.submit.isEnabled()  # empty form
    assert window.submit.toolTip() == "Saisissez l'identifiant et le mot de passe."
    assert login(controller, "wrong") is None
    assert not window.banner.isHidden() and window.banner.kind == "error"
    assert window.banner.plain_text() == "Connexion refusée — Identifiants invalides."
    assert window.password.text() == ""  # never kept in the form
    shell = login(controller)
    assert shell is not None and shell.current_page is shell.pages["dashboard"]


def test_shell_header_and_dashboard(controller):
    shell = login(controller)
    assert (shell.school_label.text(), shell.school_code.text()) == ("École Test", "TEST01")
    assert shell.user_label.text() == "Ada Admin" and shell.role_label.text() == "Super-administrateur · admin"
    assert shell.logout_button.text() == "Se déconnecter"
    dashboard = shell.pages["dashboard"]
    values = {card.value.text() for card in dashboard.cards}
    assert {"2025-2026", "4", "3", "0", "Indisponible"} <= values
    assert all(card.label.text() for card in dashboard.cards)
    # Présences is a real module now (attendance, gate passages, guardians), no placeholder left.
    assert type(shell.pages["attendance"]).__name__ == "AttendancePage"


def test_sidebar_navigation_and_coming_soon_entries(controller):
    shell = login(controller)
    for key in ("categories", "subjects", "dashboard"):
        shell.open(key)
        assert shell.current_key == key and shell.current_page is shell.pages[key]
    labels = [shell.nav.item(i).text() for i in range(shell.nav.count())]
    assert "GESTION ACADÉMIQUE" in labels and "Présences" in labels and "Communication" in labels
    assert not any("Bientôt" in label for label in labels)  # every module of the sidebar is available
    headers = [shell.nav.item(i) for i in range(shell.nav.count()) if shell.nav.item(i).text().isupper()]
    assert headers and all(item.flags() == Qt.NoItemFlags for item in headers)  # not selectable
    page = shell.open("attendance")
    assert page.title == "Présences" and shell.current_key == "attendance"


def test_categories_add_edit_deactivate_reactivate(controller, backend):
    shell = login(controller)
    page = shell.open("categories")
    page.open_dialog = lambda category=None: {"code": "SCI", "name": "Scientifique", "description": "Maths"}
    page.add()
    assert codes(page) == ["SCI"]
    assert page.banner.kind == "success" and page.banner.plain_text() == "Catégorie « SCI » créée avec succès."
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
    assert controller.confirmations[-1] == (
        "Désactiver la catégorie ?",
        {"confirm_text": "Désactiver", "danger": True},
    )
    page.status.setCurrentIndex(1)  # "Inactives"
    page.table.selectRow(0)
    assert page.table.item(0, 3).text() == "○  Inactive" and page.toggle_button.text() == "Réactiver"
    assert page.toggle_button.property("variant") == "secondary"  # reactivating is not dangerous
    page.toggle()  # reactivation needs no confirmation
    page.status.setCurrentIndex(0)
    assert page.table.item(0, 3).text() == "●  Active"
    page.table.selectRow(0)
    assert page.toggle_button.property("variant") == "danger"


def test_actions_explain_why_they_are_disabled(controller, backend):
    backend.add_category("SCI", "Scientifique")
    page = login(controller).open("categories")
    assert not page.edit_button.isEnabled() and not page.toggle_button.isEnabled()
    assert page.edit_button.toolTip() == "Sélectionnez d'abord une catégorie dans la liste."
    assert page.add_button.property("variant") == "primary"
    assert page.refresh_button.property("variant") == "secondary"
    page.table.selectRow(0)
    assert page.edit_button.isEnabled() and page.toggle_button.property("variant") == "danger"


def test_empty_list_and_search(controller, backend):
    page = login(controller).open("categories")
    assert page.table_stack.currentWidget() is page.empty
    assert page.empty.text() == "Aucune catégorie pour le moment. Cliquez sur « Ajouter » pour en créer une."
    assert page.count_label.text() == "0 catégorie"
    backend.add_category("SCI", "Scientifique")
    backend.add_category("LIT", "Littéraire")
    page.search.setText("litt")
    page.reload()
    assert codes(page) == ["LIT"] and page.count_label.text() == "1 catégorie"
    page.search.setText("zzz")
    page.reload()
    assert page.empty.text() == "Aucune catégorie ne correspond à ces critères."


def test_subject_requires_a_category_from_the_list(controller, backend):
    backend.add_category("SCI", "Scientifique")
    backend.add_category("OLD", "Ancienne", active=False)
    page = login(controller).open("subjects")
    offered = {}

    def dialog_values(categories, subject=None):
        dialog = SubjectDialog(categories)
        offered["labels"] = [dialog.category.itemText(i) for i in range(dialog.category.count())]
        dialog.code.setText("MATH")
        dialog.name.setText("Mathématiques")
        offered["without_category"] = (dialog.save_enabled, dialog.status.text())
        assert not dialog.category.isEditable()  # no free text
        dialog.category.setCurrentIndex(1)
        offered["with_category"] = dialog.save_enabled
        return dialog.values()

    page.open_dialog = dialog_values
    page.add()
    assert offered["labels"] == ["Choisir une catégorie…", "SCI — Scientifique"]  # active ones only
    assert offered["without_category"] == (False, "Pour enregistrer, complétez : Catégorie.")
    assert offered["with_category"] is True
    assert codes(page) == ["MATH"] and page.table.item(0, 2).text() == "SCI — Scientifique"
    assert page.banner.plain_text() == "Matière « MATH » créée avec succès."
    assert page.category_filter.count() == 3
    assert page.category_filter.itemText(1) == "OLD — Ancienne (inactive)"  # sorted by code


@pytest.mark.parametrize(
    ("status", "code", "details", "kind", "text"),
    [
        (403, "PERMISSION_DENIED", None, "error", "Permission refusée : Message du serveur."),
        (404, "NOT_FOUND", None, "warning", "Message du serveur. La liste va être actualisée."),
        (409, "CONFLICT", {"rule": "duplicate_code"}, "warning", "Ce code est déjà utilisé : choisissez-en un autre."),
        (
            400,
            "BUSINESS_RULE_VIOLATION",
            {"rule": "category_inactive"},
            "warning",
            "Cette catégorie est inactive : choisissez une catégorie active.",
        ),
    ],
)
def test_errors_are_explained(controller, backend, status, code, details, kind, text):
    page = login(controller).open("categories")
    backend.forced[("POST", "pedagogical-categories/")] = fail(status, code, "Message du serveur.", details)
    page.open_dialog = lambda category=None: {"code": "SCI", "name": "Scientifique", "description": ""}
    page.add()
    assert page.banner.kind == kind and not page.banner.isHidden()
    assert page.banner.plain_text() == f"Impossible de créer la catégorie — {text}"
    assert f"HTTP {status}" in page.banner.text()  # technical detail kept, but secondary
    assert "Traceback" not in page.banner.text() and "Error" not in page.banner.plain_text()
    assert controller.main_window is not None  # stays in the shell


def test_offline_is_explained(controller, backend):
    page = login(controller).open("categories")
    backend.offline = True
    page.reload()
    assert page.banner.kind == "error"
    assert page.banner.plain_text().startswith("Impossible de charger les catégories — Serveur injoignable.")


def test_expired_session_returns_to_login(controller, backend):
    shell = login(controller)
    backend.expire_access_tokens()
    backend.revoked |= backend.refresh_tokens  # refresh impossible too
    shell.open("categories")
    assert controller.main_window is None and not controller.login_window.isHidden()
    assert "expiré" in controller.login_window.banner.plain_text()


def test_logout_returns_to_login_and_revokes(controller, backend, api):
    shell = login(controller)
    shell.logout_button.click()
    assert controller.main_window is None and api.access_token is None
    assert backend.revoked and "déconnecté" in controller.login_window.banner.plain_text()


def test_lists_are_sorted_ascending_by_default(controller, backend):
    for code in ("ZOO", "ART", "MID"):
        backend.add_category(code, code.title())
    page = login(controller).open("categories")
    assert codes(page) == ["ART", "MID", "ZOO"]
    assert page.table.horizontalHeader().sortIndicatorOrder() == Qt.AscendingOrder
