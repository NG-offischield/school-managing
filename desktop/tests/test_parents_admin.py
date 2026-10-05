"""Gestion académique → Parents (ADR 0026): registrations and link requests
decided by the school; every rule is the server's and is explained."""

import pytest

from school_admin.api.errors import Conflict, Forbidden, NotFound, ValidationFailed
from school_admin.config import AppConfig
from school_admin.messages import explain
from school_admin.services.parents import ParentAdminService
from school_admin.ui.app import AppController
from school_admin.ui.dialogs.parent_dialogs import (
    IdentityCheckDialog,
    LinkApprovalDialog,
    LinkRequestDialog,
    StudentApprovalDialog,
)
from school_admin.ui.tasks import ImmediateRunner

from .fake_backend import PASSWORD


@pytest.fixture
def parents(logged_in, api, backend):
    backend.seed_parents()
    return ParentAdminService(api)


def test_registrations_service(parents, backend):
    rows, total = parents.registrations(status="PENDING")
    assert total == 2 and {r.applicant_name for r in rows} == {"Awa Mbarga", "Paul Ndiaye"}
    assert parents.registrations(search="paul")[0][0].email == "paul@example.cm"
    approved = parents.approve_registration("reg1")
    assert approved.status_label == "Validée"
    with pytest.raises(Conflict) as exc:
        parents.approve_registration("reg1")
    assert explain(exc.value) == "Cette inscription a déjà été traitée."
    with pytest.raises(ValidationFailed):
        parents.reject_registration("reg2", "  ")  # a reason is required (also checked by the server)
    assert parents.reject_registration("reg2", "Personne inconnue").rejection_reason == "Personne inconnue"
    with pytest.raises(NotFound):
        parents.approve_registration("reg-other-school")


def test_link_request_service_follows_the_server_rules(parents, backend):
    request = parents.link_request("lr1")
    assert (request.identity_label, request.ready) == ("À vérifier (pièce d'identité)", False)
    with pytest.raises(ValidationFailed):
        parents.verify_identity("lr1", "CNI", " ")
    with pytest.raises(Conflict) as exc:
        parents.verify_identity("lr1", "CNI", "CM 0000 0000")
    assert explain(exc.value) == "Le numéro saisi ne correspond pas à la pièce déclarée par le parent."
    assert parents.verify_identity("lr1", "CNI", "cm 1234-5678").identity_status == "VERIFIED"
    with pytest.raises(Conflict) as exc:
        parents.approve("lr1")
    assert exc.value.rule == "student_approval_required"
    assert parents.record_student_approval("lr1", "APPROVED", " en classe ").student_approval_note == "en classe"
    approved = parents.approve("lr1", can_view_financial_data=True)
    assert approved.status == "APPROVED"
    assert backend.link_requests["lr1"]["_rights"] == {
        "can_pay": False,
        "can_view_financial_data": True,
        "can_receive_notifications": True,
        "can_submit_complaints": True,
    }
    with pytest.raises(Conflict) as exc:
        parents.reject("lr1", "trop tard")
    assert exc.value.rule == "request_not_pending"


def test_identity_is_rejected_after_three_mismatches(parents):
    for _ in range(3):
        with pytest.raises(Conflict):
            parents.verify_identity("lr1", "CNI", "AAAA0000")
    with pytest.raises(Conflict) as exc:
        parents.verify_identity("lr1", "CNI", "CM12345678")
    assert explain(exc.value).startswith("Vérification d'identité refusée")


def test_sponsored_parent_never_gets_more_than_the_sponsor(parents):
    parents.record_student_approval("lr2", "NOT_REQUIRED")
    with pytest.raises(Conflict) as exc:
        parents.approve("lr2", can_pay=True, can_view_financial_data=True)
    assert explain(exc.value).startswith("Un parent parrainé ne peut pas avoir plus de droits")
    assert parents.approve("lr2", can_pay=True).status == "APPROVED"


def test_only_administrators(parents, backend):
    backend.roles = ["TEACHER"]
    with pytest.raises(Forbidden):
        parents.registrations()
    with pytest.raises(Forbidden):
        parents.approve("lr1")


def test_record_buttons_follow_the_state(qapp, parents):
    request = parents.link_request("lr1")
    assert set(LinkRequestDialog(request).action_buttons) == {"verify_identity", "student_approval", "reject"}
    parents.verify_identity("lr1", "CNI", "CM12345678")
    parents.record_student_approval("lr1", "APPROVED")
    ready = LinkRequestDialog(parents.link_request("lr1"))
    assert set(ready.action_buttons) == {"student_approval", "approve", "reject"}
    ready.action_buttons["approve"].click()
    assert ready.action == "approve"
    parents.approve("lr1")
    assert LinkRequestDialog(parents.link_request("lr1")).action_buttons == {}


def test_dialog_values(qapp, parents):
    request = parents.link_request("lr1")
    identity = IdentityCheckDialog(request)
    assert identity.document_type.currentData() == "CNI" and not identity.save_button.isEnabled()
    identity.number.setText(" CM 1234 ")
    assert identity.save_button.isEnabled()
    assert identity.values() == {"document_type": "CNI", "document_number": "CM 1234"}
    approval = StudentApprovalDialog(request)
    assert approval.values() == {"decision": "APPROVED", "note": ""}
    rights = LinkApprovalDialog(request)
    assert rights.values() == {  # financial rights are never granted by default
        "can_pay": False,
        "can_view_financial_data": False,
        "can_receive_notifications": True,
        "can_submit_complaints": True,
    }


@pytest.fixture
def controller(qapp, api, auth, backend):
    backend.seed_parents()
    ctrl = AppController(api, auth, ImmediateRunner(), AppConfig(api_url="http://testserver/api/v1/"))
    yield ctrl
    if ctrl.main_window is not None:
        ctrl.main_window.close()
    ctrl.login_window.close()


def open_parents(ctrl):
    window = ctrl.login_window
    window.identifier.setText("admin")
    window.password.setText(PASSWORD)
    window.attempt()
    return ctrl.main_window.open("parents")


def test_link_requests_page_runs_the_whole_decision(controller, backend):
    page = open_parents(controller).links
    assert page.table.rowCount() == 2  # pending requests by default
    script = {"record": "verify_identity", "identity": {"document_type": "CNI", "document_number": "CM 0000"}}
    page.ask = lambda kind, **context: script.get(kind)
    page.select_id("lr1")
    page.open_row()
    assert "ne correspond pas à la pièce déclarée" in page.banner.plain_text()
    assert backend.link_requests["lr1"]["identity_failed_checks"] == 1

    script["identity"] = {"document_type": "CNI", "document_number": "cm12345678"}
    page.select_id("lr1")
    page.open_row()
    assert page.banner.plain_text() == "Identité de Awa Mbarga vérifiée."

    script.update(record="student_approval", student_approval={"decision": "APPROVED", "note": ""})
    page.select_id("lr1")
    page.open_row()
    assert page.banner.plain_text() == "Réponse de l'élève enregistrée : confirmée par l'élève."

    script.update(record="approve", approve={"can_pay": False, "can_view_financial_data": False})
    page.select_id("lr1")
    page.open_row()
    assert page.banner.plain_text() == "Awa Mbarga est maintenant parent vérifié de Élève Zéro."
    assert backend.link_requests["lr1"]["status"] == "APPROVED"

    script.update(record="reject", reason={"reason": "Lien non établi"})
    page.select_id("lr2")
    page.open_row()
    assert backend.link_requests["lr2"]["status"] == "REJECTED"
    assert page.table.rowCount() == 0  # nothing pending any more


def test_registrations_page_approves_and_rejects(controller, backend):
    parents_page = open_parents(controller)
    parents_page.tabs.setCurrentWidget(parents_page.registrations)
    page = parents_page.registrations
    assert page.table.rowCount() == 2
    page.confirm = lambda *a, **k: True
    page.select_id("reg1")
    assert page.approve_button.isEnabled()
    page.approve_button.click()
    assert page.banner.plain_text() == "Inscription de Awa Mbarga validée."
    page.ask = lambda kind, **context: {"reason": "Inconnu de l'école"}
    page.select_id("reg2")
    page.reject_button.click()
    assert backend.registrations["reg2"]["status"] == "REJECTED"
    page.status.setCurrentIndex(page.status.findData(None))
    page.select_id("reg3")
    assert not page.approve_button.isEnabled()  # already decided
