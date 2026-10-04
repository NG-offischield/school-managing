"""Account lifecycle on the desktop (ADR 0024): state in the teacher record,
activation code shown ONCE (never in a banner, a log or a repr), revocation,
suspension / re-activation. Rules are the server's."""

import pytest
from PySide6.QtWidgets import QApplication

from school_admin.api.errors import Conflict, Forbidden, NotFound, ValidationFailed
from school_admin.config import AppConfig
from school_admin.messages import explain
from school_admin.services.accounts import AccountService
from school_admin.services.teachers import TeacherService
from school_admin.ui.app import AppController
from school_admin.ui.dialogs.teacher_dialogs import ActivationCodeDialog, TeacherRecordDialog
from school_admin.ui.tasks import ImmediateRunner

from .fake_backend import PASSWORD


@pytest.fixture
def accounts(logged_in, api, backend):
    backend.seed_teachers()
    return AccountService(api)


def test_account_service(accounts, backend, api):
    teacher = TeacherService(api).get(backend.tm)
    assert (teacher.membership_id, teacher.account_state) == (f"mem-{backend.tm}", "NOT_ACTIVATED")
    summary = accounts.summary(teacher.membership_id)
    assert (summary.state_label, summary.login) == ("Non activé", "jean.mbarga@ecole.test")
    issued = accounts.issue_code(teacher.membership_id)
    assert issued.account.state == "PENDING_ACTIVATION" and len(issued.code) == 24
    assert issued.code not in repr(issued)  # never in a log or a traceback
    assert accounts.revoke_code(teacher.membership_id).state == "NOT_ACTIVATED"
    with pytest.raises(Conflict) as exc:
        accounts.revoke_code(teacher.membership_id)
    assert explain(exc.value) == "Aucun code d'activation en attente pour ce compte."
    with pytest.raises(ValidationFailed):
        accounts.disable(teacher.membership_id, "  ")
    assert accounts.disable(teacher.membership_id, "Fin de contrat").state == "DISABLED"
    with pytest.raises(Conflict) as exc:
        accounts.issue_code(teacher.membership_id)
    assert exc.value.rule == "account_disabled"
    assert accounts.enable(teacher.membership_id).state == "NOT_ACTIVATED"
    backend.accounts[teacher.membership_id]["state"] = "ACTIVE"
    with pytest.raises(Conflict) as exc:
        accounts.issue_code(teacher.membership_id)
    assert explain(exc.value).startswith("Ce compte est déjà activé")
    with pytest.raises(NotFound):
        accounts.summary("mem-other-school")
    backend.roles = ["TEACHER"]
    with pytest.raises(Forbidden):
        accounts.issue_code(teacher.membership_id)


@pytest.fixture
def controller(qapp, api, auth, backend):
    backend.seed_teachers()
    ctrl = AppController(api, auth, ImmediateRunner(), AppConfig(api_url="http://testserver/api/v1/"))
    yield ctrl
    if ctrl.main_window is not None:
        ctrl.main_window.close()
    ctrl.login_window.close()


def open_teachers(ctrl):
    window = ctrl.login_window
    window.identifier.setText("admin")
    window.password.setText(PASSWORD)
    window.attempt()
    return ctrl.main_window.open("teachers")


def test_record_shows_the_state_and_runs_the_actions(controller, backend):
    page = open_teachers(controller)
    seen = {}
    script = {"record": "issue_code"}

    def ask(kind, **context):
        seen.setdefault(kind, []).append(context)
        if kind == "suspend":
            return {"reason": "Départ"}
        return script.get(kind)

    page.ask = ask
    page.confirm = lambda *a, **k: True
    page.select_id(backend.tm)
    page.open_record()
    assert seen["record"][0]["account"].state == "NOT_ACTIVATED"
    issued = seen["code"][0]["issued"]
    assert issued.account.state == "PENDING_ACTIVATION"
    banner = page.banner.plain_text()
    assert banner.startswith("Code d'activation remis pour Mbarga Jean") and issued.code not in banner
    for action, state, message in (
        ("revoke_code", "NOT_ACTIVATED", "Code d'activation de Mbarga Jean révoqué."),
        ("disable_account", "DISABLED", "Compte de Mbarga Jean suspendu : connexion impossible, sessions fermées."),
        ("enable_account", "NOT_ACTIVATED", "Compte de Mbarga Jean réactivé."),
    ):
        if action == "revoke_code":
            backend.accounts[f"mem-{backend.tm}"]["state"] = "PENDING_ACTIVATION"
        script["record"] = action
        page.select_id(backend.tm)
        page.open_record()
        assert page.banner.plain_text() == message
        assert backend.accounts[f"mem-{backend.tm}"]["state"] == state
    script["record"] = "issue_code"
    backend.accounts[f"mem-{backend.tm}"]["state"] = "ACTIVE"
    page.select_id(backend.tm)
    page.open_record()
    assert "déjà activé" in page.banner.plain_text()  # 409 explained


def test_record_buttons_follow_the_state(qapp, api, logged_in, backend):
    backend.seed_teachers()
    teacher = TeacherService(api).get(backend.tm)
    service = AccountService(api)
    expected = {
        "NOT_ACTIVATED": {"issue_code", "disable_account"},
        "PENDING_ACTIVATION": {"issue_code", "revoke_code", "disable_account"},
        "ACTIVE": {"disable_account"},
        "DISABLED": {"enable_account"},
    }
    for state, buttons in expected.items():
        backend.accounts[teacher.membership_id]["state"] = state
        dialog = TeacherRecordDialog(teacher, [], [], account=service.summary(teacher.membership_id))
        assert set(dialog.account_buttons) == buttons, state
        dialog.account_buttons[sorted(buttons)[0]].click()
        assert dialog.action == sorted(buttons)[0]
    no_account = TeacherRecordDialog(teacher, [], [], account=None)
    assert no_account.account_buttons == {}


def test_code_dialog_shows_the_code_once_and_copies_it(qapp, accounts, backend):
    issued = accounts.issue_code(backend.account_for(backend.tm))
    dialog = ActivationCodeDialog("Mbarga Jean", issued)
    assert dialog.code.text() == issued.code
    dialog.copy_button.click()
    assert QApplication.clipboard().text() == issued.code and dialog.copy_button.text() == "Copié"
    texts = " ".join(label.text() for label in dialog.content.findChildren(type(dialog.status)))
    assert "jean.mbarga@ecole.test" in texts and "une seule fois" in texts
