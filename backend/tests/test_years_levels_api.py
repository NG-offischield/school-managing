"""Academic years and levels administration (admin desktop "Gestion
académique → Années scolaires / Niveaux"), plus the dashboard aggregates:
services + API, rules, isolation, permissions, DB (ADR 0017)."""

from datetime import date, timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.academics import services as academics
from apps.academics.models import AcademicYear, AcademicYearStatus, Level
from apps.attendance.models import StudentDailyAttendance
from apps.audit.models import AuditLog
from apps.people.models import EnrollmentStatus

from .conftest import DB
from .factories import LevelFactory, SchoolClassFactory, SchoolFactory, member_with_role
from .gradebook_world import make_world
from .test_classes_api import as_, data, error

pytestmark = DB

YEARS = "/api/v1/academic-years/"
LEVELS = "/api/v1/levels/"


@pytest.fixture
def w(school):
    return make_world(school)  # 2025-2026 current, periods, class 3e A with 3 pupils


def next_year(admin, **extra):
    body = {"name": "2026-2027", "start_date": "2026-09-01", "end_date": "2027-07-31", **extra}
    return admin.post(YEARS, body, format="json")


# --- academic years -----------------------------------------------------------


def test_admin_creates_a_planned_year(w):
    body = data(next_year(as_(w.admin)), 201)
    assert (body["name"], body["status"], body["is_current"], body["class_count"]) == (
        "2026-2027",
        "PLANNED",
        False,
        0,
    )
    year = AcademicYear.objects.get(pk=body["id"])
    assert year.school == w.school
    assert AuditLog.objects.filter(action="ACADEMIC_YEAR_CREATED", entity_id=year.pk).exists()
    listed = data(as_(w.admin).get(YEARS))
    assert [y["name"] for y in listed] == ["2026-2027", "2025-2026"]
    assert listed[1]["class_count"] == 1


def test_year_rules_duplicate_overlap_dates(w):
    admin = as_(w.admin)
    err = error(next_year(admin, name="2025-2026"), 409)
    assert err["details"]["rule"] == "duplicate_year_name"
    err = error(next_year(admin, start_date="2026-06-01"), 409)  # overlaps 2025-2026
    assert err["details"]["rule"] == "year_overlap"
    err = error(next_year(admin, end_date="2026-08-01"), 400)
    assert err["details"]["rule"] == "invalid_dates" or err["code"] == "BUSINESS_RULE_VIOLATION"
    err = error(next_year(admin, name="  "), 400)
    assert err["code"] == "VALIDATION_ERROR"
    with pytest.raises(IntegrityError), transaction.atomic():  # PostgreSQL agrees on overlaps
        AcademicYear.objects.create(school=w.school, name="X", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31))


def test_update_year_name_and_dates(w):
    admin = as_(w.admin)
    created = data(next_year(admin), 201)
    url = f"{YEARS}{created['id']}/"
    body = data(admin.patch(url, {"name": "2026/2027", "end_date": "2027-07-15"}, format="json"))
    assert (body["name"], body["end_date"]) == ("2026/2027", "2027-07-15")
    assert AuditLog.objects.filter(action="ACADEMIC_YEAR_UPDATED", entity_id=created["id"]).exists()
    # The current year cannot shrink below its periods.
    err = error(admin.patch(f"{YEARS}{w.year.pk}/", {"start_date": "2025-10-01"}, format="json"), 409)
    assert err["details"]["rule"] == "year_content_outside_dates"


def test_set_current_switches_the_single_current_year(w):
    admin = as_(w.admin)
    created = data(next_year(admin), 201)
    body = data(admin.post(f"{YEARS}{created['id']}/set-current/"))
    assert (body["is_current"], body["status"]) == (True, "ACTIVE")
    w.year.refresh_from_db()
    assert (w.year.is_current, w.year.status) == (False, AcademicYearStatus.ACTIVE)
    assert AcademicYear.objects.filter(school=w.school, is_current=True).count() == 1
    assert AuditLog.objects.filter(action="ACADEMIC_YEAR_SET_CURRENT", entity_id=created["id"]).exists()


def test_close_year_rules(w):
    admin = as_(w.admin)
    url = f"{YEARS}{w.year.pk}/close/"
    assert error(admin.post(url), 409)["details"]["rule"] == "year_is_current"
    created = data(next_year(admin), 201)
    data(admin.post(f"{YEARS}{created['id']}/set-current/"))
    assert error(admin.post(url), 409)["details"]["rule"] == "year_has_active_enrollments"
    w.klass.enrollments.update(status=EnrollmentStatus.COMPLETED)
    body = data(admin.post(url))
    assert body["status"] == "CLOSED"
    assert AuditLog.objects.filter(action="ACADEMIC_YEAR_CLOSED", entity_id=w.year.pk).exists()
    # A closed year is frozen: no edit, no new current, no second closing, no new class.
    assert error(admin.patch(f"{YEARS}{w.year.pk}/", {"name": "x"}, format="json"), 400)["details"]["rule"] == (
        "year_closed"
    )
    assert error(admin.post(f"{YEARS}{w.year.pk}/set-current/"), 400)["details"]["rule"] == "year_closed"
    assert error(admin.post(url), 400)["details"]["rule"] == "year_closed"
    payload = {"name": "3e Z", "level": str(w.klass.level_id), "academic_year": str(w.year.pk)}
    assert error(admin.post("/api/v1/classes/", payload, format="json"), 400)["details"]["rule"] == "year_closed"


def test_years_isolation_and_permissions(w):
    other = SchoolFactory(code="OTHER1")
    foreign = academics.create_academic_year(
        other, name="2026-2027", start_date=date(2026, 9, 1), end_date=date(2027, 7, 31)
    )
    admin = as_(w.admin)
    assert [y["id"] for y in data(admin.get(YEARS))] == [str(w.year.pk)]
    assert error(admin.get(f"{YEARS}{foreign.pk}/"), 404)
    assert error(admin.patch(f"{YEARS}{foreign.pk}/", {"name": "x"}, format="json"), 404)
    assert error(admin.post(f"{YEARS}{foreign.pk}/set-current/"), 404)
    assert error(admin.post(f"{YEARS}{foreign.pk}/close/"), 404)
    # Same name in another school is fine.
    data(next_year(admin), 201)
    teacher = as_(w.tm_member)
    assert data(teacher.get(YEARS))  # members read
    assert error(next_year(teacher, name="2030-2031", start_date="2030-09-01", end_date="2031-07-31"), 403)
    assert error(teacher.post(f"{YEARS}{w.year.pk}/close/"), 403)
    assert error(admin.get(f"{YEARS}?status=NOPE"), 400)


# --- levels ---------------------------------------------------------------------


def test_level_crud_and_rules(w):
    admin = as_(w.admin)
    body = data(
        admin.post(LEVELS, {"code": "6e", "name": "Sixième", "cycle": "COLLEGE", "order_index": 1}, format="json"),
        201,
    )
    assert (body["code"], body["name"], body["cycle"], body["active"], body["class_count"]) == (
        "6E",
        "Sixième",
        "COLLEGE",
        True,
        0,
    )
    assert AuditLog.objects.filter(action="LEVEL_CREATED", entity_id=body["id"]).exists()
    assert error(admin.post(LEVELS, {"code": "6E", "name": "Bis"}, format="json"), 409)["details"]["rule"] == (
        "duplicate_code"
    )
    url = f"{LEVELS}{body['id']}/"
    body = data(admin.patch(url, {"name": "6e (Sixième)", "order_index": 2, "first_character": "6"}, format="json"))
    assert (body["name"], body["order_index"], body["first_character"]) == ("6e (Sixième)", 2, "6")
    assert error(admin.patch(url, {"code": "SIX"}, format="json"), 400)["details"]["rule"] == "code_immutable"
    with pytest.raises(IntegrityError), transaction.atomic():
        Level.objects.create(school=w.school, code="6E", name="Doublon")


def test_level_deactivation_refused_while_used_by_an_open_class(w):
    admin = as_(w.admin)
    used = f"{LEVELS}{w.klass.level_id}/"
    assert data(admin.get(used))["class_count"] == 1
    assert error(admin.post(f"{used}deactivate/"), 409)["details"]["rule"] == "level_in_use"
    free = LevelFactory(school=w.school)
    body = data(admin.post(f"{LEVELS}{free.pk}/deactivate/"))
    assert body["active"] is False
    assert [lv["id"] for lv in data(admin.get(f"{LEVELS}?active=false"))] == [str(free.pk)]
    # An inactive level is refused for new classes, then accepted again once reactivated.
    payload = {"name": "4e A", "level": str(free.pk), "academic_year": str(w.year.pk)}
    assert error(admin.post("/api/v1/classes/", payload, format="json"), 400)["details"]["rule"] == "level_inactive"
    assert data(admin.post(f"{LEVELS}{free.pk}/reactivate/"))["active"] is True
    data(admin.post("/api/v1/classes/", payload, format="json"), 201)
    assert AuditLog.objects.filter(action="LEVEL_DEACTIVATED", entity_id=free.pk).exists()


def test_levels_isolation_permissions_and_search(w):
    foreign = LevelFactory(school=SchoolFactory(code="OTHER2"), code="6E")
    admin = as_(w.admin)
    assert str(foreign.pk) not in {lv["id"] for lv in data(admin.get(LEVELS))}
    assert error(admin.get(f"{LEVELS}{foreign.pk}/"), 404)
    assert error(admin.patch(f"{LEVELS}{foreign.pk}/", {"name": "x"}, format="json"), 404)
    assert error(admin.post(f"{LEVELS}{foreign.pk}/deactivate/"), 404)
    data(admin.post(LEVELS, {"code": "6E", "name": "Sixième"}, format="json"), 201)  # same code, other school
    assert [lv["code"] for lv in data(admin.get(f"{LEVELS}?search=sixi"))] == ["6E"]
    teacher = as_(w.tm_member)
    assert data(teacher.get(LEVELS))
    assert error(teacher.post(LEVELS, {"code": "5E", "name": "Cinquième"}, format="json"), 403)
    assert error(teacher.post(f"{LEVELS}{w.klass.level_id}/deactivate/"), 403)


# --- dashboard aggregates ---------------------------------------------------------


def test_dashboard_enrollments_by_level_class_and_month(w):
    other_level = LevelFactory(school=w.school, code="2NDE", name="Seconde")
    SchoolClassFactory(school=w.school, name="2nde A", academic_year=w.year, level=other_level)
    body = data(as_(w.admin).get("/api/v1/admin/dashboard/enrollments/"))
    assert (body["academic_year"], body["total"]) == (str(w.year.pk), 3)
    assert [(r["code"], r["count"]) for r in body["by_level"]] == [(w.klass.level.code, 3)]
    assert {(r["name"], r["count"]) for r in body["by_class"]} == {("3e A", 3), ("2nde A", 0)}
    assert body["by_month"][0]["month"] == "2025-09"
    assert body["by_month"][-1]["month"] == "2026-07"
    assert all(m["enrolled"] == 3 for m in body["by_month"] if m["month"] >= f"{date.today():%Y-%m}")


def test_dashboard_enrollments_without_current_year(school):
    admin = member_with_role(school, "ADMIN")
    body = data(as_(admin).get("/api/v1/admin/dashboard/enrollments/"))
    assert (body["academic_year"], body["total"], body["by_month"]) == (None, 0, [])


def test_dashboard_attendance_trend(w):
    day = date(2026, 3, 2)
    statuses = ["PRESENT", "LATE", "ABSENT"]
    for offset in (0, 1):
        for student, status in zip(w.students, statuses, strict=True):
            StudentDailyAttendance.objects.create(
                school=w.school,
                student=student,
                academic_year=w.year,
                date=day + timedelta(days=offset),
                status=status,
                arrival_time=None if status == "ABSENT" else timezone.now(),
                late_minutes=10 if status == "LATE" else 0,
            )
    body = data(as_(w.admin).get("/api/v1/admin/dashboard/attendance-trend/?days=7&end=2026-03-05"))
    assert (body["date_from"], body["date_to"]) == ("2026-02-27", "2026-03-05")
    assert [d["date"] for d in body["days"]] == ["2026-03-02", "2026-03-03"]
    assert {k: body["days"][0][k] for k in ("PRESENT", "LATE", "ABSENT", "EXCUSED", "total")} == {
        "PRESENT": 1,
        "LATE": 1,
        "ABSENT": 1,
        "EXCUSED": 0,
        "total": 3,
    }
    assert error(as_(w.admin).get("/api/v1/admin/dashboard/attendance-trend/?days=500"), 400)


def test_dashboard_activity_and_permissions(w):
    admin = as_(w.admin)
    data(admin.post(LEVELS, {"code": "CM2", "name": "Cours moyen 2"}, format="json"), 201)
    rows = data(admin.get("/api/v1/admin/dashboard/activity/?limit=5"))
    assert rows[0]["action"] == "LEVEL_CREATED" and rows[0]["label"] == "Cours moyen 2"
    assert rows[0]["entity_type"] == "Level" and set(rows[0]) == {"id", "at", "action", "entity_type", "label", "actor"}
    other = SchoolFactory(code="OTHER3")
    other_admin = member_with_role(other, "ADMIN")
    assert data(as_(other_admin).get("/api/v1/admin/dashboard/activity/")) == []
    teacher = as_(w.tm_member)
    for url in ("activity/", "enrollments/", "attendance-trend/"):
        assert error(teacher.get(f"/api/v1/admin/dashboard/{url}"), 403)
