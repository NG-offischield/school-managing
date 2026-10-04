"""Gestion académique → Enseignants: client service, dialogs (form,
qualifications with the SERVER's compatibility verdict, override, record),
page (server pages, search, filters, add / edit / (de)activate), errors."""

from datetime import date

import pytest
from PySide6.QtCore import QDate, QSize
from PySide6.QtTest import QTest

from school_admin.api.errors import Conflict, NotFound, ValidationFailed
from school_admin.config import AppConfig
from school_admin.models import Category, CompatibilityVerdict, Qualification, Subject, Teacher
from school_admin.services.catalog import CategoryService, SubjectService
from school_admin.services.teachers import TeacherService
from school_admin.ui.app import AppController
from school_admin.ui.dialogs.teacher_dialogs import (
    QualificationsDialog,
    TeacherDialog,
    TeacherRecordDialog,
    verdict_text,
)
from school_admin.ui.tasks import ImmediateRunner

from .fake_backend import PASSWORD, fail


@pytest.fixture
def staff(logged_in, api, backend):
    backend.seed_teachers()
    return TeacherService(api)


# =============================================================================
# Client service
# =============================================================================


def test_list_paginated_filtered_and_detail(staff, backend):
    rows, total = staff.page()
    assert total == 2 and [t.last_name for t in rows] == ["Mbarga", "Ngo"]
    jean = rows[0]
    assert (jean.number, jean.category_label, jean.primary_subject_label, jean.subjects) == (
        "ENS-001",
        "SCI — Scientifique",
        "MATH — Mathématiques",
        ("MATH",),
    )
    assert [t.last_name for t in staff.page(category_id=backend.lit)[0]] == ["Ngo"]
    assert [t.last_name for t in staff.page(subject_id=backend.math)[0]] == ["Mbarga"]
    assert [t.last_name for t in staff.page(search="ens-002")[0]] == ["Ngo"]
    assert staff.page(status="inactive")[0] == []
    assert staff.get(backend.tm).active_course_count == 0


def test_create_update_activation(staff, backend):
    created = staff.create(
        last_name="Ekotto",
        first_name="Paul",
        email="paul.ekotto@ecole.test",
        phone="",
        employee_number="ENS-010",
        hire_date=date(2024, 9, 1),
        category_id=backend.sci,
        primary_subject_id=backend.phy,
        address="",
        qualification_summary="",
        bio="",
    )
    assert (created.number, created.subjects, created.account_activated) == ("ENS-010", ("PHY",), False)
    edited = staff.update(created.id, phone="+237 699 00 00 00", professional_status="PROBATION")
    assert edited.phone == "+237 699 00 00 00" and not edited.active
    assert staff.reactivate(created.id).active
    assert staff.deactivate(created.id).professional_status == "INACTIVE"
    backend.teachers_in_use.add(backend.tm)
    with pytest.raises(Conflict) as exc:
        staff.deactivate(backend.tm)
    assert exc.value.rule == "teacher_in_use"


def test_server_rules_are_relayed(staff, backend):
    with pytest.raises(ValidationFailed) as exc:  # refused before any call
        staff.create(
            last_name="", first_name="", email="", employee_number="", category_id=None, primary_subject_id=None
        )
    assert set(exc.value.field_errors()) == set(
        ["last_name", "first_name", "email", "employee_number", "category_id", "primary_subject_id"]
    )
    base = {
        "last_name": "X",
        "first_name": "Y",
        "email": "jean.mbarga@ecole.test",
        "employee_number": "ENS-099",
        "category_id": backend.sci,
        "primary_subject_id": backend.math,
    }
    with pytest.raises(Conflict) as exc:
        staff.create(**base)
    assert exc.value.rule == "email_in_use"
    with pytest.raises(Conflict) as exc:
        staff.create(**{**base, "email": "z@ecole.test", "employee_number": "ens-001"})
    assert exc.value.rule == "duplicate_employee_number"
    with pytest.raises(NotFound):
        staff.get("another-school-teacher")


def test_qualifications_and_verdicts_come_from_the_server(staff, backend):
    backend.rules[(backend.sci, backend.mus)] = "INCOMPATIBLE"
    verdict = staff.compatibility(backend.tm, backend.mus)
    assert (verdict.result, verdict.reason, verdict.result_label) == (
        "INCOMPATIBLE",
        "rule_incompatible",
        "Incompatible",
    )
    from school_admin.api.errors import ValidationFailed as Refused

    with pytest.raises(Refused) as exc:
        staff.add_qualification(backend.tm, backend.mus)
    assert exc.value.rule == "incompatible_subject"
    staff.grant_override(backend.tm, backend.mus, "Diplôme de conservatoire")
    assert staff.compatibility(backend.tm, backend.mus).result == "OVERRIDDEN"
    added = staff.add_qualification(backend.tm, backend.mus)
    assert (added.status, added.current) == ("DECLARED", "OVERRIDDEN")
    physics = staff.add_qualification(backend.tm, backend.phy)
    assert staff.verify(physics.id).status == "VERIFIED"
    assert staff.reject(physics.id, "Pas de diplôme").status == "REJECTED"
    with pytest.raises(ValidationFailed):
        staff.reject(physics.id, " ")  # a reason is required
    with pytest.raises(Conflict) as exc:
        staff.add_qualification(backend.tm, backend.mus)
    assert exc.value.rule == "already_qualified"


# =============================================================================
# Dialogs
# =============================================================================

CATEGORIES = [Category("c1", "SCI", "Scientifique", "", True), Category("c2", "LIT", "Littéraire", "", True)]
SUBJECTS = [
    Subject("s1", "MATH", "Mathématiques", "c1", "SCI — Scientifique", "THEORETICAL", False, True),
    Subject("s2", "FR", "Français", "c2", "LIT — Littéraire", "THEORETICAL", False, True),
]


def test_teacher_dialog_validation_and_values(qapp):
    dialog = TeacherDialog(CATEGORIES, SUBJECTS)
    assert dialog.status.text() == (
        "Pour enregistrer, complétez : Nom, Prénom(s), E-mail, Matricule, Catégorie pédagogique, Matière principale."
    )
    assert "sans mot de passe" in " ".join(lbl.text() for lbl in dialog.header.findChildren(type(dialog.status)))
    dialog.last_name.setText("Ekotto")
    dialog.first_name.setText("Paul")
    dialog.email.setText("paul")
    dialog.employee_number.setText("ENS-010")
    dialog.category.setCurrentIndex(1)
    dialog.primary_subject.setCurrentIndex(1)
    assert dialog.status.text().endswith("une adresse e-mail valide.")
    dialog.email.setText("paul@ecole.test")
    assert dialog.save_enabled and dialog.professional_status is None  # statuses only when editing
    dialog.hire_date.setDate(QDate(2024, 9, 1))
    values = dialog.values()
    assert (values["category_id"], values["primary_subject_id"], values["hire_date"]) == ("c1", "s1", date(2024, 9, 1))
    assert [dialog.primary_subject.itemText(i) for i in range(1, 3)] == [
        "MATH — Mathématiques (SCI)",
        "FR — Français (LIT)",
    ]


def test_teacher_dialog_edit_keeps_values(qapp):
    teacher = Teacher(
        "t1",
        "ENS-1",
        "Jean",
        "Mbarga",
        "j@ecole.test",
        "",
        "c1",
        "SCI — Scientifique",
        "s1",
        "MATH — Mathématiques",
        ("MATH",),
        "ACTIVE",
        "ON_LEAVE",
        False,
    )
    dialog = TeacherDialog(CATEGORIES, SUBJECTS, teacher=teacher)
    assert (dialog.category.currentData(), dialog.primary_subject.currentData()) == ("c1", "s1")
    assert (dialog.professional_status.currentData(), dialog.employment_status.currentData()) == ("ACTIVE", "ON_LEAVE")
    assert dialog.hire_date.text() == "jj/mm/aaaa" and dialog.values()["hire_date"] is None


def test_verdict_text_only_explains_the_server_answer():
    rule = {"category": "SCI", "level": None, "compatible": False, "requires_admin_review": False}
    verdict = CompatibilityVerdict("INCOMPATIBLE", "rule_incompatible", "MUS — Musique", rule=rule)
    assert verdict_text(verdict) == (
        "MUS — Musique — Incompatible. Règle de la catégorie SCI (tous niveaux) : matière interdite à ce profil. "
        "Une dérogation motivée est possible."
    )
    override = {"approved_by": "Ada Admin", "reason": "Conservatoire", "expires_at": None}
    assert verdict_text(CompatibilityVerdict("OVERRIDDEN", "override", "MUS — Musique", override=override)).endswith(
        "Dérogation accordée par Ada Admin : « Conservatoire »."
    )


def test_qualifications_dialog_flow(qapp, staff, backend):
    backend.rules[(backend.sci, backend.mus)] = "INCOMPATIBLE"
    jean = staff.get(backend.tm)
    subjects = SubjectService(staff.api).list(active=True)
    reasons = []

    def ask(_parent, title, _text, **options):
        reasons.append(title)
        return {"reason": "Diplôme de conservatoire", "expires_at": None}

    dialog = QualificationsDialog(jean, staff, ImmediateRunner(), subjects, [], ask=ask)
    assert list(dialog.subject_rows) == ["MATH"]
    _, verify, withdraw = dialog.subject_rows["MATH"]
    assert verify.isEnabled() and not withdraw.isEnabled()  # the primary subject cannot be withdrawn
    dialog.subject.setCurrentIndex(dialog.subject.findText("MUS — Musique (LIT)"))
    assert not dialog.override_button.isEnabled()  # check first
    dialog.check_button.click()
    assert dialog.verdict.result == "INCOMPATIBLE" and dialog.verdict_label.property("kind") == "error"
    assert "Une dérogation motivée est possible." in dialog.verdict_label.text()
    dialog.add_button.click()
    assert dialog.banner.kind == "error" or dialog.banner.kind == "warning"
    assert "dérogation motivée est nécessaire" in dialog.banner.plain_text()
    assert dialog.override_button.isEnabled()
    dialog.override_button.click()
    assert reasons == ["Accorder une dérogation ?"]
    assert dialog.verdict.result == "OVERRIDDEN" and dialog.verdict_label.property("kind") == "info"
    dialog.add_button.click()
    assert set(dialog.subject_rows) == {"MATH", "MUS"} and dialog.changed
    _, verify, withdraw = dialog.subject_rows["MUS"]
    verify.click()
    assert "validée" in dialog.banner.plain_text()
    _, _, withdraw = dialog.subject_rows["MUS"]
    withdraw.click()
    assert reasons[-1] == "Retirer la matière ?" and "retirée" in dialog.banner.plain_text()
    assert "Règle : MUS — interdit" in dialog.rules_label.text()
    assert "Dérogation : MUS" in dialog.rules_label.text()


def test_record_dialog_sections_and_actions(qapp):
    teacher = Teacher(
        "t1",
        "ENS-1",
        "Jean",
        "Mbarga",
        "j@ecole.test",
        "+237",
        "c1",
        "SCI — Scientifique",
        "s1",
        "MATH — Mathématiques",
        ("MATH",),
        "ACTIVE",
        "ACTIVE",
        True,
        None,
        "Akwa",
        "",
        "",
        False,
        2,
        5,
    )
    quals = [Qualification("q1", "s1", "MATH", "Mathématiques", "VERIFIED", "ADMIN", "COMPATIBLE", "COMPATIBLE")]
    rates = [
        {
            "vacation_rate": "5000.00",
            "currency": "XAF",
            "vacation_minutes": 60,
            "effective_from": "2025-09-01",
            "active": True,
        }
    ]
    record = TeacherRecordDialog(teacher, quals, rates)
    texts = " ".join(label.text() for label in record.content.findChildren(type(record.status)))
    for expected in (
        "IDENTITÉ",
        "PROFIL PROFESSIONNEL",
        "QUALIFICATIONS",
        "PLANNING",
        "RÉMUNÉRATION",
        "COMPTE",
        "5000.00 XAF / 60 min",
        "Vérifiée · Compatible",
        "non activé",
    ):
        assert expected in texts, expected
    record.qualifications_button.click()
    assert record.action == "qualifications"


# =============================================================================
# Page
# =============================================================================


@pytest.fixture
def controller(qapp, api, auth, backend):
    backend.seed_teachers()
    ctrl = AppController(api, auth, ImmediateRunner(), AppConfig(api_url="http://testserver/api/v1/"))
    ctrl.confirmations = []
    ctrl.confirm_answer = True

    def confirm(_parent, title, text, **options):
        ctrl.confirmations.append((title, text, options))
        return ctrl.confirm_answer

    ctrl.page_options = {"teachers": {"confirm": confirm}}
    yield ctrl
    if ctrl.main_window is not None:
        ctrl.main_window.close()
    ctrl.login_window.close()


def open_teachers(ctrl):
    window = ctrl.login_window
    window.identifier.setText("admin")
    window.password.setText(PASSWORD)
    window.attempt()
    return ctrl.main_window, ctrl.main_window.open("teachers")


def names(page):
    return [page.table.item(r, 1).text() for r in range(page.table.rowCount())]


def test_navigation_list_search_filters(controller, backend):
    shell, page = open_teachers(controller)
    labels = [shell.nav.item(i).text() for i in range(shell.nav.count())]
    start = labels.index("GESTION ACADÉMIQUE")
    assert labels[start + 7] == "Enseignants" and "Enseignants   ·  Bientôt" not in labels
    assert [page.table.horizontalHeaderItem(c).text() for c in range(7)] == [
        "Matricule",
        "Nom",
        "Prénom(s)",
        "Catégorie",
        "Matière principale",
        "Matières",
        "Statut",
    ]
    assert names(page) == ["Mbarga", "Ngo"] and page.count_label.text() == "2 enseignants"
    assert [page.table.item(0, c).text() for c in (0, 3, 4, 5, 6)] == [
        "ENS-001",
        "SCI",
        "MATH — Mathématiques",
        "MATH",
        "●  Actif",
    ]
    page.category_filter.setCurrentIndex(page.category_filter.findData(backend.lit))
    assert names(page) == ["Ngo"]
    page.category_filter.setCurrentIndex(0)
    page.subject_filter.setCurrentIndex(page.subject_filter.findData(backend.math))
    assert names(page) == ["Mbarga"]
    page.subject_filter.setCurrentIndex(0)
    page.search.setText("marie")
    page.reload_first_page()
    assert names(page) == ["Ngo"]
    page.search.setText("zzz")
    page.reload_first_page()
    assert page.empty.text() == "Aucun enseignant ne correspond à ces critères."


def test_add_edit_record_and_activation(controller, backend):
    _, page = open_teachers(controller)

    def ask(kind, **context):
        if kind == "teacher" and context.get("teacher") is None:
            assert [c.code for c in context["categories"]] == ["LIT", "SCI"] or len(context["categories"]) == 2
            return {
                "last_name": "Ekotto",
                "first_name": "Paul",
                "email": "paul.ekotto@ecole.test",
                "phone": "",
                "employee_number": "ENS-010",
                "hire_date": None,
                "category_id": backend.sci,
                "primary_subject_id": backend.phy,
                "address": "",
                "qualification_summary": "",
                "bio": "",
            }
        if kind == "teacher":
            return {"phone": "+237 600", "professional_status": "ACTIVE", "employment_status": "ACTIVE"}
        if kind == "record":
            return "edit"
        return False

    page.ask = ask
    page.add()
    assert page.banner.plain_text() == "Enseignant « Ekotto Paul » (ENS-010) créé avec succès."
    assert page.selected().subjects == ("PHY",)
    page.open_record()  # -> "edit" from the record
    assert page.banner.plain_text() == "Enseignant « Ekotto Paul » (ENS-010) modifié avec succès."
    page.toggle()
    title, text, options = controller.confirmations[-1]
    assert title == "Désactiver l'enseignant ?" and "s'il est encore utilisé" in text
    assert page.banner.plain_text() == "Enseignant « Ekotto Paul » (ENS-010) désactivé avec succès."
    page.status.setCurrentIndex(1)  # Inactifs
    assert names(page) == ["Ekotto"] and page.toggle_button.text() == "Réactiver"
    page.table.selectRow(0)
    page.toggle()
    assert page.banner.plain_text() == "Enseignant « Ekotto Paul » (ENS-010) réactivé avec succès."


def test_errors_are_explained(controller, backend):
    _, page = open_teachers(controller)
    backend.teachers_in_use.add(backend.tm)
    page.table.selectRow(names(page).index("Mbarga"))
    page.toggle()
    assert page.banner.kind == "warning" and page.banner.plain_text() == (
        "Impossible de désactiver l'enseignant — L'enseignant a encore des cours actifs ou des séances à venir : "
        "réaffectez-les d'abord."
    )
    values = {
        "last_name": "X",
        "first_name": "Y",
        "email": "x@ecole.test",
        "employee_number": "E",
        "category_id": backend.sci,
        "primary_subject_id": backend.math,
    }
    for status, details, kind, text in (
        (403, None, "error", "Permission refusée : Message du serveur."),
        (409, {"rule": "email_in_use"}, "warning", "Cette adresse e-mail est déjà utilisée par un autre compte."),
        (404, None, "warning", "Message du serveur. La liste va être actualisée."),
        (
            400,
            {"rule": "incompatible_subject"},
            "warning",
            "Matière incompatible avec la catégorie pédagogique de l'enseignant : "
            "une dérogation motivée est nécessaire.",
        ),
    ):
        backend.forced[("POST", "teachers/")] = fail(status, "X", "Message du serveur.", details)
        page.ask = lambda kind, **c: dict(values)
        page.add()
        assert page.banner.plain_text() == f"Impossible de créer l'enseignant — {text}", status
        assert page.banner.kind in (kind, "error")


def test_qualifications_action_refreshes_the_row(controller, backend):
    _, page = open_teachers(controller)
    page.table.selectRow(names(page).index("Mbarga"))
    seen = {}

    def ask(kind, **context):
        seen["kind"], seen["teacher"] = kind, context["teacher"].name
        backend._qualify(backend.tm, backend.phy)  # what the dialog would have added
        return True

    page.ask = ask
    page.qualifications_button.click()
    assert seen == {"kind": "qualifications", "teacher": "Mbarga Jean"}
    assert page.selected().subjects == ("MATH", "PHY")
    assert page.banner.plain_text() == "Qualifications de « Mbarga Jean » mises à jour."


@pytest.mark.parametrize("size", [QSize(1366, 768), QSize(1280, 720), QSize(1024, 768)])
def test_toolbar_fits(controller, size):
    shell, page = open_teachers(controller)
    shell.resize(size)
    shell.show()
    QTest.qWaitForWindowExposed(shell)
    buttons = [
        page.refresh_button,
        page.record_button,
        page.edit_button,
        page.toggle_button,
        page.qualifications_button,
        page.add_button,
    ]
    for row in (buttons, [page.search, page.status, page.count_label], [page.category_filter, page.subject_filter]):
        for left, right in zip(row, row[1:], strict=False):
            assert left.geometry().right() < right.geometry().left(), (left.accessibleName(), right.accessibleName())
    assert page.search.width() >= 220 and page.category_filter.width() >= page.category_filter.minimumWidth()
    for widget in [*buttons, page.search, page.status, page.category_filter, page.subject_filter, page.next_button]:
        assert widget.isVisible() and page.rect().contains(widget.mapTo(page, widget.rect().bottomRight()))
        assert widget.width() >= min(widget.minimumSizeHint().width(), 120)
    shell.close()


def test_dashboard_counts_active_teachers(controller, backend):
    shell, page = open_teachers(controller)
    backend.teachers[backend.tf]["employment_status"] = "ON_LEAVE"
    dashboard = shell.open("dashboard")
    cards = {card.label.text(): card for card in dashboard.cards}
    assert cards["Enseignants"].value.text() == "1"  # ON_LEAVE is not active
    assert CategoryService(page.service.api).list()  # the categories used by the split exist
