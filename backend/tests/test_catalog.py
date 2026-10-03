"""Administration of the pedagogical catalogue: categories and subjects
(services + API for the PySide6 admin desktop). ADR 0010."""

from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from apps.academics import services
from apps.academics.models import GradingScale, PedagogicalCategory, Subject
from apps.audit.models import AuditLog
from apps.gradebook import services as gb

from .conftest import DB
from .factories import CategoryFactory, SchoolFactory, SubjectFactory, admin_of, member_with_role
from .gradebook_world import make_world

pytestmark = DB

CATS = "/api/v1/pedagogical-categories/"
SUBJECTS = "/api/v1/subjects/"


def as_(membership):
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


def body(response, status=200):
    assert response.status_code == status, response.json()
    return response.json()


@pytest.fixture
def admin(school):
    return admin_of(school)


# =============================================================================
# Categories — services
# =============================================================================


def test_admin_creates_category_normalised_and_audited(school, admin):
    category = services.create_category(school, actor=admin, code=" sports ", name=" Sports ")
    assert (category.code, category.name, category.school, category.active) == ("SPORTS", "Sports", school, True)
    log = AuditLog.objects.get(action="CATEGORY_CREATED")
    assert (log.actor, log.entity_id, log.layer, log.school) == (admin, category.pk, "ADMINISTRATIVE", school)
    assert log.new_data["code"] == "SPORTS"


@pytest.mark.parametrize("role", ["TEACHER", "PARENT", "STAFF", "GUARDIAN", "CONTENT_MANAGER"])
def test_non_admins_cannot_create_categories(school, role):
    with pytest.raises(PermissionDenied):
        services.create_category(school, actor=member_with_role(school, role), code="X", name="X")
    assert not PedagogicalCategory.objects.filter(code="X").exists()


def test_admin_of_another_school_cannot_create_here(school):
    with pytest.raises(PermissionDenied):
        services.create_category(school, actor=admin_of(SchoolFactory()), code="X", name="X")


def test_duplicate_code_in_school_is_a_conflict_but_allowed_elsewhere(school, admin):
    services.create_category(school, actor=admin, code="ART", name="Arts")
    with pytest.raises(ValidationError) as exc:
        services.create_category(school, actor=admin, code="art", name="Arts bis")
    assert exc.value.code == "duplicate_code"
    other = SchoolFactory()
    services.create_category(other, actor=admin_of(other), code="ART", name="Arts")


def test_update_category_but_never_its_code(school, admin):
    category = services.create_category(school, actor=admin, code="SCI", name="Sciences")
    services.update_category(category, actor=admin, name="Sciences exactes", description="Maths, PC")
    category.refresh_from_db()
    assert (category.name, category.description) == ("Sciences exactes", "Maths, PC")
    with pytest.raises(ValidationError) as exc:
        services.update_category(category, actor=admin, code="SCIENCES")
    assert exc.value.code == "code_immutable"
    log = AuditLog.objects.get(action="CATEGORY_UPDATED")
    assert (log.old_data["name"], log.new_data["name"]) == ("Sciences", "Sciences exactes")


def test_used_category_is_protected_then_deactivatable(school, admin):
    category = services.create_category(school, actor=admin, code="SCI", name="Sciences")
    subject = services.create_subject(school, actor=admin, code="MATH", name="Maths", category=category)
    # Never deleted: PROTECT at database level.
    with pytest.raises(IntegrityError), transaction.atomic():
        PedagogicalCategory.objects.filter(pk=category.pk).delete()
    # Not deactivatable while an active subject uses it.
    with pytest.raises(ValidationError) as exc:
        services.set_category_active(category, False, actor=admin)
    assert exc.value.code == "category_in_use"
    services.set_subject_active(subject, False, actor=admin)
    services.set_category_active(category, False, actor=admin)
    category.refresh_from_db()
    assert category.active is False and Subject.objects.filter(pk=subject.pk).exists()
    # Reactivating the subject needs an active category.
    with pytest.raises(ValidationError) as exc:
        services.set_subject_active(subject, True, actor=admin)
    assert exc.value.code == "category_inactive"
    services.set_category_active(category, True, actor=admin)
    services.set_subject_active(subject, True, actor=admin)


# =============================================================================
# Subjects — services
# =============================================================================


def test_create_subject_with_valid_category(school, admin):
    category = CategoryFactory(school=school)
    scale = GradingScale.objects.get(school=school, code="SUR100")
    subject = services.create_subject(
        school,
        actor=admin,
        code="eps",
        name="Sport",
        category=category,
        subject_type="PRACTICAL",
        default_grading_scale=scale,
    )
    assert (subject.code, subject.category, subject.default_grading_scale) == ("EPS", category, scale)
    assert AuditLog.objects.filter(action="SUBJECT_CREATED", entity_id=subject.pk).exists()


def test_subject_without_category_is_refused(school, admin):
    with pytest.raises(ValidationError) as exc:
        services.create_subject(school, actor=admin, code="X", name="X", category=None)
    assert exc.value.code == "category_required"


def test_subject_with_category_of_another_school_is_refused(school, admin):
    foreign = CategoryFactory(school=SchoolFactory())
    with pytest.raises(ValidationError) as exc:
        services.create_subject(school, actor=admin, code="X", name="X", category=foreign)
    assert exc.value.code == "category_other_school"
    assert not Subject.objects.filter(code="X").exists()


def test_subject_with_inactive_category_is_refused(school, admin):
    category = CategoryFactory(school=school, active=False)
    with pytest.raises(ValidationError) as exc:
        services.create_subject(school, actor=admin, code="X", name="X", category=category)
    assert exc.value.code == "category_inactive"


def test_update_subject(school, admin):
    a, b = CategoryFactory(school=school), CategoryFactory(school=school)
    subject = services.create_subject(school, actor=admin, code="PHYS", name="Physique", category=a)
    services.update_subject(subject, actor=admin, name="Physique-Chimie", category=b, subject_type="PRACTICAL")
    subject.refresh_from_db()
    assert (subject.name, subject.category, subject.subject_type) == ("Physique-Chimie", b, "PRACTICAL")
    with pytest.raises(ValidationError):
        services.update_subject(subject, actor=admin, code="PC")
    with pytest.raises(ValidationError):
        services.update_subject(subject, actor=admin, category=CategoryFactory(school=SchoolFactory()))
    with pytest.raises(PermissionDenied):
        services.update_subject(subject, actor=member_with_role(school, "TEACHER"), name="x")


def test_subject_taught_in_active_course_cannot_be_deactivated(school):
    w = make_world(school)
    with pytest.raises(ValidationError) as exc:
        services.set_subject_active(w.maths, False, actor=w.admin)
    assert exc.value.code == "subject_in_use"
    # Once the course is inactive, the subject can be deactivated...
    w.course_maths.active = False
    w.course_maths.save()
    services.set_subject_active(w.maths, False, actor=w.admin)
    # ...and no new course can use it (existing academic features stay coherent).
    from .factories import SchoolClassFactory

    with pytest.raises(ValidationError) as exc:
        gb.create_course(SchoolClassFactory(school=school, academic_year=w.year), w.maths, w.tm, actor=w.admin)
    assert exc.value.code == "subject_inactive"


def test_existing_grades_and_averages_survive_deactivation(school):
    w = make_world(school)
    w.grade(w.assess(), w.students[0], 15)
    w.course_maths.active = False
    w.course_maths.save()
    services.set_subject_active(w.maths, False, actor=w.admin)
    assert gb.subject_fraction(w.students[0].pk, [w.course_maths.pk], w.s1) == Decimal("0.75")


# =============================================================================
# API (PySide6 desktop contract)
# =============================================================================


def test_category_crud_api_for_admin(school, admin):
    client = as_(admin)
    created = body(client.post(CATS, {"code": "lit", "name": "Lettres"}, format="json"), 201)["data"]
    assert created["code"] == "LIT"
    cid = created["id"]
    updated = body(client.patch(f"{CATS}{cid}/", {"name": "Lettres modernes"}, format="json"))["data"]
    assert updated["name"] == "Lettres modernes"
    assert body(client.post(f"{CATS}{cid}/deactivate/"))["data"]["active"] is False
    assert body(client.post(f"{CATS}{cid}/reactivate/"))["data"]["active"] is True
    detail = body(client.get(f"{CATS}{cid}/"))["data"]
    assert detail["code"] == "LIT"


def test_category_selector_list(school, admin):
    CategoryFactory(school=school, code="SCI", name="Sciences")
    CategoryFactory(school=school, code="OLD", name="Ancienne", active=False)
    CategoryFactory(school=SchoolFactory(), code="ALIEN")
    rows = body(as_(member_with_role(school, "TEACHER")).get(f"{CATS}?active=true&page_size=100"))["data"]
    assert [(r["code"], r["active"]) for r in rows] == [("SCI", True)]
    found = body(as_(admin).get(f"{CATS}?search=anc"))["data"]
    assert [r["code"] for r in found] == ["OLD"]


def test_category_write_api_errors(school, admin):
    client = as_(admin)
    client.post(CATS, {"code": "SCI", "name": "Sciences"}, format="json")
    duplicate = client.post(CATS, {"code": "sci", "name": "x"}, format="json")
    assert (duplicate.status_code, duplicate.json()["error"]["code"]) == (409, "CONFLICT")
    teacher = as_(member_with_role(school, "TEACHER")).post(CATS, {"code": "Z", "name": "Z"}, format="json")
    assert (teacher.status_code, teacher.json()["error"]["code"]) == (403, "PERMISSION_DENIED")
    invalid = client.post(CATS, {"name": "no code"}, format="json")
    assert invalid.json()["error"]["code"] == "VALIDATION_ERROR"
    foreign = CategoryFactory(school=SchoolFactory())
    assert client.patch(f"{CATS}{foreign.id}/", {"name": "hack"}, format="json").status_code == 404
    assert client.post(f"{CATS}{foreign.id}/deactivate/").status_code == 404
    foreign.refresh_from_db()
    assert foreign.name != "hack" and foreign.active


def test_category_in_use_deactivation_is_409(school, admin):
    subject = SubjectFactory(school=school)
    response = as_(admin).post(f"{CATS}{subject.category_id}/deactivate/")
    assert (response.status_code, response.json()["error"]["details"]["rule"]) == (409, "category_in_use")


def test_subject_crud_api_for_admin(school, admin):
    client = as_(admin)
    category = CategoryFactory(school=school, code="SCI")
    created = body(
        client.post(SUBJECTS, {"code": "math", "name": "Mathématiques", "category": str(category.id)}, format="json"),
        201,
    )["data"]
    assert (created["code"], created["category"]["code"], created["subject_type"]) == ("MATH", "SCI", "THEORETICAL")
    sid = created["id"]
    other_category = CategoryFactory(school=school, code="TECH")
    updated = body(
        client.patch(f"{SUBJECTS}{sid}/", {"category": str(other_category.id), "name": "Maths"}, format="json")
    )["data"]
    assert (updated["category"]["code"], updated["name"]) == ("TECH", "Maths")
    assert body(client.post(f"{SUBJECTS}{sid}/deactivate/"))["data"]["active"] is False
    rows = body(client.get(f"{SUBJECTS}?active=false&category={other_category.id}"))["data"]
    assert [r["id"] for r in rows] == [sid]


def test_subject_api_refuses_missing_or_foreign_category(school, admin):
    client = as_(admin)
    missing = client.post(SUBJECTS, {"code": "X", "name": "X"}, format="json")
    assert (missing.status_code, missing.json()["error"]["code"]) == (400, "VALIDATION_ERROR")
    assert "category" in missing.json()["error"]["details"]
    foreign = CategoryFactory(school=SchoolFactory())
    response = client.post(SUBJECTS, {"code": "X", "name": "X", "category": str(foreign.id)}, format="json")
    assert response.status_code == 404
    free_text = client.post(SUBJECTS, {"code": "X", "name": "X", "category": "Scientifique"}, format="json")
    assert free_text.json()["error"]["code"] == "VALIDATION_ERROR"  # must be an id, never a label
    assert not Subject.objects.filter(code="X").exists()


def test_subject_api_permissions_and_isolation(school, admin):
    subject = SubjectFactory(school=school)
    foreign = SubjectFactory(school=SchoolFactory())
    teacher = as_(member_with_role(school, "TEACHER"))
    assert teacher.patch(f"{SUBJECTS}{subject.id}/", {"name": "x"}, format="json").status_code == 403
    assert teacher.post(f"{SUBJECTS}{subject.id}/deactivate/").status_code == 403
    client = as_(admin)
    assert client.get(f"{SUBJECTS}{foreign.id}/").status_code == 404
    assert client.patch(f"{SUBJECTS}{foreign.id}/", {"name": "x"}, format="json").status_code == 404
    assert str(foreign.id) not in {r["id"] for r in body(client.get(f"{SUBJECTS}?page_size=100"))["data"]}


def test_unauthenticated_writes_are_401(api):
    assert api.post(CATS, {"code": "X", "name": "X"}, format="json").status_code == 401
    assert api.post(SUBJECTS, {}, format="json").status_code == 401


def test_audit_log_is_append_only(school, admin):
    services.create_category(school, actor=admin, code="X", name="X")
    log = AuditLog.objects.get()
    with pytest.raises(IntegrityError), transaction.atomic():
        AuditLog.objects.filter(pk=log.pk).update(action="TAMPERED")
    with pytest.raises(IntegrityError), transaction.atomic():
        AuditLog.objects.filter(pk=log.pk).delete()
