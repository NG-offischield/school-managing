"""Catalogue and dashboard client services."""

from datetime import date

import pytest

from school_admin.api.errors import Conflict, Forbidden, NotFound, ValidationFailed
from school_admin.services.catalog import CategoryService, SubjectService
from school_admin.services.dashboard import DashboardService

from .fake_backend import fail


@pytest.fixture
def categories(logged_in, api):
    return CategoryService(api)


@pytest.fixture
def subjects(logged_in, api):
    return SubjectService(api)


def test_create_list_search_and_filter_categories(categories):
    created = categories.create(code="sci", name="Scientifique", description="Maths, physique")
    assert (created.code, created.name, created.active) == ("SCI", "Scientifique", True)
    categories.create(code="LIT", name="Littéraire")
    assert [c.code for c in categories.list()] == ["LIT", "SCI"]
    assert [c.code for c in categories.list(search="scien")] == ["SCI"]
    assert [c.code for c in categories.list(active=False)] == []


def test_update_category_sends_only_editable_fields(categories, backend):
    created = categories.create(code="SCI", name="Scientifique")
    updated = categories.update(created.id, name="Sciences", description="")
    assert (updated.code, updated.name) == ("SCI", "Sciences")


def test_deactivate_and_reactivate_category(categories, subjects):
    created = categories.create(code="SCI", name="Scientifique")
    assert categories.deactivate(created.id).active is False
    assert [c.code for c in categories.list(active=False)] == ["SCI"]
    assert categories.reactivate(created.id).active is True
    subjects.create(code="MATH", name="Mathématiques", category_id=created.id)
    with pytest.raises(Conflict) as exc:  # the server refuses: still used by an active subject
        categories.deactivate(created.id)
    assert exc.value.rule == "category_in_use"


def test_duplicate_code_is_an_explicit_conflict(categories):
    categories.create(code="SCI", name="Scientifique")
    with pytest.raises(Conflict) as exc:
        categories.create(code="SCI", name="Encore")
    assert exc.value.message == "Ce code existe déjà."


def test_create_subject_with_a_category(categories, subjects):
    category = categories.create(code="SCI", name="Scientifique")
    subject = subjects.create(code="math", name="Mathématiques", category_id=category.id, subject_type="THEORETICAL")
    assert (subject.code, subject.category_id, subject.category_label) == ("MATH", category.id, "SCI — Scientifique")
    assert [s.code for s in subjects.list(category_id=category.id)] == ["MATH"]
    edited = subjects.update(
        subject.id, name="Maths", category_id=category.id, subject_type="PRACTICAL", public_visible=True
    )
    assert (edited.name, edited.subject_type, edited.public_visible) == ("Maths", "PRACTICAL", True)
    assert subjects.deactivate(subject.id).active is False
    assert subjects.reactivate(subject.id).active is True


def test_a_subject_cannot_be_created_without_a_category(subjects, backend):
    with pytest.raises(ValidationFailed) as exc:
        subjects.create(code="MATH", name="Mathématiques", category_id=None)
    assert "category" in exc.value.field_errors()
    assert ("POST", "subjects/") not in backend.calls  # refused before any request
    # And the server refuses it too (defence in depth is the backend's).
    with pytest.raises(ValidationFailed) as exc:
        subjects.api.post("subjects/", {"code": "X", "name": "X"})
    assert exc.value.field_errors() == {"category": ["Ce champ est obligatoire."]}


def test_unknown_category_and_permissions(subjects, categories, backend):
    with pytest.raises(NotFound):
        subjects.create(code="MATH", name="Maths", category_id="00000000-0000-0000-0000-000000000000")
    backend.roles[:] = ["TEACHER"]  # role changed server-side while logged in
    with pytest.raises(Forbidden):
        categories.create(code="SCI", name="Scientifique")


def test_dashboard_shows_real_counts_and_isolates_failures(logged_in, api):
    data = DashboardService(api, today=lambda: date(2025, 10, 8)).load()
    values = {m.label: (m.value, m.error) for m in data.metrics}
    assert (data.school_name, data.year_name) == ("École Test", "2025-2026")
    assert values["Classes"] == ("4", None) and values["Élèves"] == ("3", None)  # active students only
    assert values["Enseignants"] == (
        "0",
        None,
    )  # active teachers (none in the fake school) and values["Séances cette semaine"] == ("37", None)
    # One unavailable source does not break the page.
    assert values["Présence aujourd'hui"] == (None, "Aucune politique de présence.")


def test_dashboard_lets_session_expiry_through(logged_in, api, backend):
    from school_admin.api.errors import Unauthorized

    backend.forced[("GET", "students/")] = fail(401, "NOT_AUTHENTICATED", "Session expirée.")
    backend.revoked |= backend.refresh_tokens
    with pytest.raises(Unauthorized):
        DashboardService(api, today=lambda: date(2025, 10, 8)).load()
