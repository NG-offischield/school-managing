"""Course administration (admin desktop "Gestion académique → Cours",
ADR 0020): Course = subject + teacher + class + year; creation, update,
(de)activation, compatibility decided by the server, isolation, planning
dependencies, permissions, audit."""

from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

from apps.academics import services as academics
from apps.academics.models import SubjectCompatibilityRule
from apps.audit.models import AuditLog
from apps.gradebook import services as gb
from apps.gradebook.models import Course
from apps.people import services as people
from apps.scheduling.models import ScheduleSlot

from .conftest import DB
from .factories import (
    CategoryFactory,
    LevelFactory,
    SchoolClassFactory,
    SchoolFactory,
    SubjectFactory,
    make_teacher,
    member_with_role,
)
from .planning_world import MONDAY, generate, make_planning_world, slot
from .test_classes_api import as_, data, error

pytestmark = DB

COURSES = "/api/v1/courses/"


@pytest.fixture
def w(school):
    w = make_planning_world(school)  # 3e A: maths (tm, coef 4) + french (tf); 3e B: maths (tm)
    w.physics = SubjectFactory(school=school, code="PHY", name="Physique", category=w.maths.category)
    w.klass_c = SchoolClassFactory(school=school, name="3e C", academic_year=w.year, level=w.klass.level)
    return w


def body(w, **extra):
    return {"school_class": str(w.klass_c.pk), "subject": str(w.maths.pk), "teacher": str(w.tm.pk), **extra}


# =============================================================================
# Create / read
# =============================================================================


def test_create_course_with_labels_and_audit(w):
    created = data(as_(w.admin).post(COURSES, body(w, coefficient="4", weekly_hours="5"), format="json"), 201)
    course = Course.objects.get(pk=created["id"])
    assert (course.school_class, course.subject, course.teacher, course.academic_year) == (
        w.klass_c,
        w.maths,
        w.tm,
        w.year,  # the year is the class's year
    )
    assert (created["coefficient"], created["weekly_hours"], created["active"]) == ("4.00", "5.00", True)
    assert created["teacher_ref"]["number"] == w.tm.employee.employee_number and created["year"]["name"] == "2025-2026"
    assert created["subject_ref"]["code"] == "MATH" and created["published_slot_count"] == 0
    assert AuditLog.objects.filter(action="COURSE_CREATED", entity_id=course.pk).exists()


def test_list_filters_search_and_teacher_scope(w):
    admin = as_(w.admin)
    rows = data(admin.get(COURSES))
    assert len(rows) == 3 and {"class_name", "teacher_name", "subject_ref"} <= set(rows[0])
    assert {r["subject_code"] for r in data(admin.get(f"{COURSES}?school_class={w.klass.pk}"))} == {"MATH", "FR"}
    assert [r["class_name"] for r in data(admin.get(f"{COURSES}?teacher={w.tf.pk}"))] == ["3e A"]
    assert len(data(admin.get(f"{COURSES}?search=fran"))) == 1
    assert len(data(admin.get(f"{COURSES}?academic_year={w.year.pk}&level={w.klass.level_id}"))) == 3
    assert data(admin.get(f"{COURSES}?status=inactive")) == []
    page = admin.get(f"{COURSES}?page_size=2").json()
    assert page["meta"]["count"] == 3 and len(page["data"]) == 2
    # A teacher sees only their own courses (historical scope), without the admin labels.
    mine = data(as_(w.tf_member).get(COURSES))
    assert [r["subject_code"] for r in mine] == ["FR"] and "teacher_ref" not in mine[0]
    assert as_(w.tf_member).get(f"{COURSES}{w.course_maths.pk}/").status_code == 404
    assert data(as_(member_with_role(w.school, "STAFF")).get(COURSES)) == []


# =============================================================================
# Rules
# =============================================================================


def test_frame_rules_subject_category_class_year(w):
    admin = as_(w.admin)
    w.physics.active = False
    w.physics.save()
    assert error(admin.post(COURSES, body(w, subject=str(w.physics.pk)), format="json"), 400)["details"]["rule"] == (
        "subject_inactive"
    )
    category = w.french.category
    category.active = False
    category.save()
    assert (
        error(admin.post(COURSES, body(w, subject=str(w.french.pk), teacher=str(w.tf.pk)), format="json"), 400)[
            "details"
        ]["rule"]
        == "category_inactive"
    )
    category.active = True
    category.save()
    w.klass_c.active = False
    w.klass_c.save()
    assert error(admin.post(COURSES, body(w), format="json"), 400)["details"]["rule"] == "class_inactive"
    closed = academics.create_academic_year(
        w.school, name="2019-2020", start_date=date(2019, 9, 1), end_date=date(2020, 7, 31)
    )
    old_class = SchoolClassFactory(school=w.school, name="Ancienne", academic_year=closed, level=w.klass.level)
    closed.status = "CLOSED"
    closed.save()
    err = error(admin.post(COURSES, body(w, school_class=str(old_class.pk)), format="json"), 400)
    assert err["details"]["rule"] == "year_closed"
    # A course of a closed year (history) is frozen too.
    old_course = Course.objects.create(
        school=w.school, school_class=old_class, subject=w.maths, teacher=w.tm, academic_year=closed
    )
    err = error(admin.patch(f"{COURSES}{old_course.pk}/", {"coefficient": "2"}, format="json"), 400)
    assert err["details"]["rule"] == "year_closed"


def test_teacher_rules_inactive_unqualified_incompatible(w):
    admin = as_(w.admin)
    # Not qualified (no qualification for physics yet).
    err = error(admin.post(COURSES, body(w, subject=str(w.physics.pk)), format="json"), 400)
    assert err["details"]["rule"] == "teacher_not_qualified"
    # Pending review: still not qualified.
    other = SubjectFactory(school=w.school, code="ART", category=CategoryFactory(school=w.school, code="ARTC"))
    people.admin_add_qualification(w.tm, other, actor=w.admin)
    assert error(admin.post(COURSES, body(w, subject=str(other.pk)), format="json"), 400)["details"]["rule"] == (
        "teacher_not_qualified"
    )
    # A rule added AFTER the qualification makes it incompatible at this level: the engine wins today.
    people.admin_add_qualification(w.tm, w.physics, actor=w.admin)
    SubjectCompatibilityRule.objects.create(
        school=w.school,
        pedagogical_category=w.tm.pedagogical_category,
        subject=w.physics,
        level=w.klass.level,
        compatible=False,
    )
    assert error(admin.post(COURSES, body(w, subject=str(w.physics.pk)), format="json"), 400)["details"]["rule"] == (
        "incompatible_subject"
    )
    # Inactive teacher.
    idle = make_teacher(w.school, category=w.maths.category, primary_subject=w.maths)
    idle.professional_status = "INACTIVE"
    idle.save()
    assert error(admin.post(COURSES, body(w, teacher=str(idle.pk)), format="json"), 400)["details"]["rule"] == (
        "teacher_inactive"
    )


def test_duplicate_and_coteaching_coefficient(w):
    admin = as_(w.admin)
    err = error(admin.post(COURSES, body(w, school_class=str(w.klass.pk)), format="json"), 409)
    assert err["details"]["rule"] == "duplicate_course"  # same teacher, subject, class, year
    second = make_teacher(w.school, category=w.maths.category, primary_subject=w.maths)
    err = error(
        admin.post(
            COURSES, body(w, school_class=str(w.klass.pk), teacher=str(second.pk), coefficient="2"), format="json"
        ),
        409,
    )
    assert err["details"]["rule"] == "course_coefficient_conflict" and err["details"]["context"] == {
        "coefficient": "4.00"
    }
    co = data(
        admin.post(
            COURSES, body(w, school_class=str(w.klass.pk), teacher=str(second.pk), coefficient="4"), format="json"
        ),
        201,
    )
    assert co["teacher_ref"]["id"] == str(second.pk)  # co-teaching with the same coefficient
    with pytest.raises(IntegrityError), transaction.atomic():  # PostgreSQL agrees on duplicates
        Course.objects.create(
            school=w.school, school_class=w.klass, subject=w.maths, teacher=w.tm, academic_year=w.year
        )


def test_eligible_teachers_come_from_the_server(w):
    admin = as_(w.admin)
    second = make_teacher(w.school, category=w.maths.category, primary_subject=w.physics)
    people.admin_add_qualification(second, w.maths, actor=w.admin)  # same category: compatible
    idle = make_teacher(w.school, category=w.maths.category, primary_subject=w.maths)
    idle.professional_status = "INACTIVE"
    idle.save()
    reviewer = make_teacher(w.school, category=w.french.category, primary_subject=w.french)
    people.admin_add_qualification(reviewer, w.maths, actor=w.admin)  # other category: pending review
    answer = data(admin.get(f"{COURSES}eligible-teachers/?school_class={w.klass_c.pk}&subject={w.maths.pk}"))
    assert {t["id"] for t in answer["eligible"]} == {str(w.tm.pk), str(second.pk)}
    assert {(t["id"], t["reason"]) for t in answer["excluded"]} == {
        (str(idle.pk), "teacher_inactive"),
        (str(reviewer.pk), "teacher_not_qualified"),
    }
    assert str(w.tf.pk) not in {t["id"] for t in answer["eligible"] + answer["excluded"]}  # no maths at all
    assert error(
        as_(w.tm_member).get(f"{COURSES}eligible-teachers/?school_class={w.klass_c.pk}&subject={w.maths.pk}"), 403
    )


# =============================================================================
# Update, activation, planning
# =============================================================================


def test_update_course(w):
    admin = as_(w.admin)
    created = data(admin.post(COURSES, body(w), format="json"), 201)
    url = f"{COURSES}{created['id']}/"
    second = make_teacher(w.school, category=w.maths.category, primary_subject=w.maths)
    updated = data(
        admin.patch(url, {"teacher": str(second.pk), "coefficient": "3", "weekly_hours": "4"}, format="json")
    )
    assert (updated["teacher"], updated["coefficient"], updated["weekly_hours"]) == (str(second.pk), "3.00", "4.00")
    err = error(admin.patch(url, {"subject": str(w.physics.pk)}, format="json"), 409)
    assert err["details"]["rule"] == "course_identity_immutable"
    err = error(admin.patch(url, {"teacher": str(w.tf.pk)}, format="json"), 400)
    assert err["details"]["rule"] == "teacher_not_qualified"
    assert AuditLog.objects.filter(action="COURSE_UPDATED", entity_id=created["id"]).exists()


def test_planning_dependencies(w):
    admin = as_(w.admin)
    created = data(admin.post(COURSES, body(w), format="json"), 201)
    course = Course.objects.get(pk=created["id"])
    # The new course is usable by the existing planning, unchanged.
    new_slot = slot(w, course=course, weekday=3, start=(14, 0), end=(16, 0), room=w.lab)
    assert ScheduleSlot.objects.filter(pk=new_slot.pk, course=course, teacher=w.tm).exists()
    generate(w, days=2)
    assert course.sessions.count() == 1  # Wednesday of the generated week
    url = f"{COURSES}{course.pk}/"
    second = make_teacher(w.school, category=w.maths.category, primary_subject=w.maths)
    tuesday = MONDAY + timedelta(days=1)
    with mock.patch("django.utils.timezone.localdate", return_value=tuesday):  # during that week
        detail = data(admin.get(url))
        assert (detail["published_slot_count"], detail["upcoming_session_count"]) == (1, 1)
        err = error(admin.post(f"{url}deactivate/"), 409)
        assert err["details"]["rule"] == "course_scheduled" and err["details"]["context"] == {"slots": 1, "sessions": 1}
        err = error(admin.patch(url, {"teacher": str(second.pk)}, format="json"), 409)
        assert err["details"]["rule"] == "course_scheduled"  # slots and sessions carry the planned teacher
        from apps.scheduling import services as planning

        planning.end_slot(new_slot, actor=w.admin, last_date=tuesday, reason="Fin du module")  # cancels Wednesday
        assert error(admin.post(f"{url}deactivate/"), 409)["details"]["context"] == {"slots": 1, "sessions": 0}
    body_ = data(admin.post(f"{url}deactivate/"))  # today: the slot is over
    assert body_["active"] is False and course.sessions.count() == 1  # history kept
    assert AuditLog.objects.filter(action="COURSE_DEACTIVATED", entity_id=course.pk).exists()


def test_reactivation_rechecks_everything(w):
    admin = as_(w.admin)
    created = data(admin.post(COURSES, body(w), format="json"), 201)
    url = f"{COURSES}{created['id']}/"
    data(admin.post(f"{url}deactivate/"))
    w.tm.professional_status = "INACTIVE"
    w.tm.save()
    assert error(admin.post(f"{url}reactivate/"), 400)["details"]["rule"] == "teacher_inactive"
    w.tm.professional_status = "ACTIVE"
    w.tm.save()
    assert data(admin.post(f"{url}reactivate/"))["active"] is True
    assert AuditLog.objects.filter(action="COURSE_ACTIVATED", entity_id=created["id"]).exists()


# =============================================================================
# Isolation and permissions
# =============================================================================


def test_cross_school_isolation(w):
    other = SchoolFactory(code="OTHERC")
    other_admin = member_with_role(other, "ADMIN")
    category = CategoryFactory(school=other, code="OSCI")
    subject = SubjectFactory(school=other, code="OMATH", category=category)
    teacher = make_teacher(other, category=category, primary_subject=subject)
    year = academics.create_academic_year(
        other, name="2025-2026", start_date=date(2025, 9, 1), end_date=date(2026, 7, 31)
    )
    klass = SchoolClassFactory(school=other, name="X", academic_year=year, level=LevelFactory(school=other))
    foreign = gb.create_course(klass, subject, teacher, actor=other_admin)
    admin = as_(w.admin)
    assert str(foreign.pk) not in {r["id"] for r in data(admin.get(COURSES))}
    for method, url, payload in (
        ("get", f"{COURSES}{foreign.pk}/", None),
        ("patch", f"{COURSES}{foreign.pk}/", {"coefficient": "2"}),
        ("post", f"{COURSES}{foreign.pk}/deactivate/", None),
        ("post", COURSES, body(w, school_class=str(klass.pk))),
        ("post", COURSES, body(w, subject=str(subject.pk))),
        ("post", COURSES, body(w, teacher=str(teacher.pk))),
        ("get", f"{COURSES}eligible-teachers/?school_class={klass.pk}&subject={w.maths.pk}", None),
    ):
        assert getattr(admin, method)(url, payload, format="json").status_code == 404, (method, url)
    # The services refuse it too (not only the school-scoped lookups).
    with pytest.raises(ValidationError) as exc:
        gb.create_course(w.klass_c, w.maths, teacher, actor=w.admin)
    assert exc.value.code == "teacher_other_school"
    with pytest.raises(ValidationError) as exc:
        gb.create_course(w.klass_c, subject, w.tm, actor=w.admin)
    assert exc.value.code == "subject_other_school"
    with pytest.raises(PermissionDenied):
        gb.create_course(w.klass_c, w.maths, w.tm, actor=other_admin)


def test_permissions(w):
    teacher = as_(w.tm_member)
    assert error(teacher.post(COURSES, body(w), format="json"), 403)
    assert error(teacher.patch(f"{COURSES}{w.course_maths.pk}/", {"coefficient": "1"}, format="json"), 403)
    assert error(teacher.post(f"{COURSES}{w.course_maths.pk}/deactivate/"), 403)
    with pytest.raises(PermissionDenied):
        gb.update_course(w.course_maths, actor=w.tm_member, coefficient=Decimal("1"))
    with pytest.raises(PermissionDenied):
        gb.set_course_active(w.course_maths, False, actor=w.tm_member)
    assert Course.objects.get(pk=w.course_maths.pk).active is True
