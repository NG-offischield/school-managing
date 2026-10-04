"""Classes administration (admin desktop "Gestion académique → Classes"):
services + /api/v1/classes/ writes, rules, isolation, permissions, DB."""

from datetime import date

import pytest
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from apps.academics import services as academics
from apps.academics.models import AcademicYearStatus, SchoolClass
from apps.audit.models import AuditLog
from apps.scheduling import services as planning

from .conftest import DB
from .factories import LevelFactory, SchoolFactory, member_with_role
from .planning_world import make_planning_world

pytestmark = DB


@pytest.fixture
def w(school):
    return make_planning_world(school)


def as_(member):
    client = APIClient()
    client.force_authenticate(member.user)
    return client


def data(response, expected=200):
    assert response.status_code == expected, response.json()
    return response.json()["data"]


def error(response, expected):
    assert response.status_code == expected, response.json()
    return response.json()["error"]


def payload(w, **extra):
    return {"name": "4e A", "level": str(w.klass.level_id), "academic_year": str(w.year.pk), **extra}


def test_admin_creates_a_class_with_level_year_and_room(w):
    body = data(
        as_(w.admin).post("/api/v1/classes/", payload(w, capacity=35, main_room=str(w.r12.pk)), format="json"), 201
    )
    assert (body["name"], body["level"], body["academic_year"], body["capacity"]) == (
        "4e A",
        str(w.klass.level_id),
        str(w.year.pk),
        35,
    )
    assert (body["main_room"], body["main_room_name"], body["active"]) == (str(w.r12.pk), "R12 — Salle 12", True)
    assert body["academic_year_name"] == "2025-2026" and body["level_name"] == w.klass.level.name
    created = SchoolClass.objects.get(pk=body["id"])
    assert created.school == w.school
    assert AuditLog.objects.filter(action="CLASS_CREATED", entity_id=created.pk).exists()
    assert AuditLog.objects.filter(action="CLASS_MAIN_ROOM_SET", entity_id=created.pk).exists()


def test_name_is_unique_per_school_and_year(w):
    admin = as_(w.admin)
    data(admin.post("/api/v1/classes/", payload(w), format="json"), 201)
    err = error(admin.post("/api/v1/classes/", payload(w, name="4E a"), format="json"), 409)
    assert (err["code"], err["details"]["rule"]) == ("CONFLICT", "duplicate_class_name")
    next_year = academics.create_academic_year(
        w.school, name="2026-2027", start_date=date(2026, 9, 1), end_date=date(2027, 7, 31)
    )
    data(admin.post("/api/v1/classes/", payload(w, academic_year=str(next_year.pk)), format="json"), 201)
    with pytest.raises(IntegrityError), transaction.atomic():  # PostgreSQL agrees
        SchoolClass.objects.create(school=w.school, name="4e A", level=w.klass.level, academic_year=w.year)


def test_update_class(w):
    admin = as_(w.admin)
    created = data(admin.post("/api/v1/classes/", payload(w), format="json"), 201)
    other_level = LevelFactory(school=w.school, name="Quatrième")
    body = data(
        admin.patch(
            f"/api/v1/classes/{created['id']}/",
            {
                "name": "4e Bilingue",
                "level": str(other_level.pk),
                "capacity": 30,
                "main_room": str(w.lab.pk),
                "public_visible": True,
            },
            format="json",
        )
    )
    assert (body["name"], body["level"], body["capacity"], body["main_room"], body["public_visible"]) == (
        "4e Bilingue",
        str(other_level.pk),
        30,
        str(w.lab.pk),
        True,
    )
    cleared = data(admin.patch(f"/api/v1/classes/{created['id']}/", {"main_room": None}, format="json"))
    assert cleared["main_room"] is None
    next_year = academics.create_academic_year(
        w.school, name="2026-2027", start_date=date(2026, 9, 1), end_date=date(2027, 7, 31)
    )
    err = error(
        admin.patch(f"/api/v1/classes/{created['id']}/", {"academic_year": str(next_year.pk)}, format="json"), 409
    )
    assert err["details"]["rule"] == "class_year_immutable"
    err = error(admin.patch(f"/api/v1/classes/{created['id']}/", {"name": w.klass.name}, format="json"), 409)
    assert err["details"]["rule"] == "duplicate_class_name"


def test_deactivate_and_reactivate(w):
    admin = as_(w.admin)
    created = data(admin.post("/api/v1/classes/", payload(w), format="json"), 201)
    off = data(admin.post(f"/api/v1/classes/{created['id']}/deactivate/"))
    assert off["active"] is False
    listed = data(admin.get("/api/v1/classes/?active=false"))
    assert [c["id"] for c in listed] == [created["id"]]
    on = data(admin.post(f"/api/v1/classes/{created['id']}/reactivate/"))
    assert on["active"] is True
    actions = list(AuditLog.objects.filter(entity_id=created["id"]).values_list("action", flat=True))
    assert {"CLASS_DEACTIVATED", "CLASS_ACTIVATED"} <= set(actions)


def test_a_class_in_use_cannot_be_deactivated(w):
    # 3e A has enrolled pupils and active courses.
    err = error(as_(w.admin).post(f"/api/v1/classes/{w.klass.pk}/deactivate/"), 409)
    assert (err["code"], err["details"]["rule"]) == ("CONFLICT", "class_in_use")
    w.klass.refresh_from_db()
    assert w.klass.active


def test_business_rules(w):
    admin = as_(w.admin)
    inactive_level = LevelFactory(school=w.school, active=False)
    err = error(admin.post("/api/v1/classes/", payload(w, level=str(inactive_level.pk)), format="json"), 400)
    assert err["details"]["rule"] == "level_inactive"
    planning.set_room_active(w.lab, False, actor=w.admin)
    err = error(admin.post("/api/v1/classes/", payload(w, main_room=str(w.lab.pk)), format="json"), 400)
    assert err["details"]["rule"] == "room_inactive"
    assert not SchoolClass.objects.filter(name="4e A").exists()  # all-or-nothing
    small = planning.create_room(w.school, actor=w.admin, code="S2", name="Petite", capacity=2)
    err = error(admin.patch(f"/api/v1/classes/{w.klass.pk}/", {"main_room": str(small.pk)}, format="json"), 409)
    assert err["details"]["rule"] == "room_capacity_exceeded"  # 3 pupils enrolled
    err = error(
        admin.post(
            "/api/v1/classes/",
            {"name": "", "level": str(w.klass.level_id), "academic_year": str(w.year.pk)},
            format="json",
        ),
        400,
    )
    assert err["code"] == "VALIDATION_ERROR"
    err = error(admin.post("/api/v1/classes/", {"name": "X", "academic_year": str(w.year.pk)}, format="json"), 400)
    assert "level" in err["details"]


def test_closed_year_refuses_new_classes(w):
    closed = academics.create_academic_year(
        w.school,
        name="2024-2025",
        start_date=date(2024, 9, 1),
        end_date=date(2025, 7, 31),
        status=AcademicYearStatus.CLOSED,
    )
    err = error(as_(w.admin).post("/api/v1/classes/", payload(w, academic_year=str(closed.pk)), format="json"), 400)
    assert err["details"]["rule"] == "year_closed"


def test_cross_school_ids_are_404(w):
    other = make_planning_world(SchoolFactory())
    admin = as_(w.admin)
    for field, value in (
        ("level", other.klass.level_id),
        ("academic_year", other.year.pk),
        ("main_room", other.r12.pk),
    ):
        err = error(admin.post("/api/v1/classes/", payload(w, **{field: str(value)}), format="json"), 404)
        assert err["code"] == "NOT_FOUND"
    for method, url in (
        ("get", f"/api/v1/classes/{other.klass.pk}/"),
        ("patch", f"/api/v1/classes/{other.klass.pk}/"),
        ("post", f"/api/v1/classes/{other.klass.pk}/deactivate/"),
    ):
        assert error(getattr(admin, method)(url, {}, format="json"), 404)["code"] == "NOT_FOUND"
    assert str(other.klass.pk) not in {c["id"] for c in data(admin.get("/api/v1/classes/"))}
    with pytest.raises(IntegrityError), transaction.atomic():  # composite keys: level of another school
        SchoolClass.objects.create(school=w.school, name="Z", level=other.klass.level, academic_year=w.year)


def test_permissions(w):
    for member in (w.tm_member, member_with_role(w.school, "PARENT"), member_with_role(w.school, "STAFF")):
        client = as_(member)
        assert error(client.post("/api/v1/classes/", payload(w), format="json"), 403)["code"] == "PERMISSION_DENIED"
        assert error(client.patch(f"/api/v1/classes/{w.klass.pk}/", {"name": "X"}, format="json"), 403)
        assert error(client.post(f"/api/v1/classes/{w.klass.pk}/deactivate/"), 403)
    assert len(data(as_(w.tm_member).get("/api/v1/classes/"))) == 2  # reading stays open to members


def test_list_filters(w):
    admin = as_(w.admin)
    names = lambda query: [c["name"] for c in data(admin.get(f"/api/v1/classes/{query}"))]  # noqa: E731
    assert names("") == ["3e A", "3e B"]
    assert names("?search=b") == ["3e B"]
    assert names(f"?academic_year={w.year.pk}") == ["3e A", "3e B"]
    other_level = LevelFactory(school=w.school)
    academics.create_class(w.school, actor=w.admin, name="CE1", level=other_level, academic_year=w.year)
    assert names(f"?level={other_level.pk}") == ["CE1"]
    assert names("?active=true") == names("")
