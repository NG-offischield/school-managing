"""Teachers administration (admin desktop "Gestion académique → Enseignants",
ADR 0019): transactional creation (User → Membership → Employee → Teacher),
account without password, update, (de)activation vs courses / sessions,
qualifications through the compatibility engine, overrides, isolation,
permissions, history protection."""

from datetime import timedelta
from unittest import mock

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.academics.models import SubjectCompatibilityRule
from apps.accounts.models import SchoolMembership, User
from apps.audit.models import AuditLog
from apps.people import services as people
from apps.people.models import (
    EmployeeProfile,
    ProfessionalStatus,
    QualificationStatus,
    TeacherProfile,
    TeacherSubjectQualification,
)

from .conftest import DB
from .factories import CategoryFactory, SchoolFactory, SubjectFactory, member_with_role
from .planning_world import MONDAY, generate, make_planning_world, slot
from .test_classes_api import as_, data, error

pytestmark = DB

TEACHERS = "/api/v1/teachers/"


@pytest.fixture
def w(school):
    w = make_planning_world(school)  # maths (SCI) teacher tm with courses, french (LIT) teacher tf
    w.sci, w.lit = w.maths.category, w.french.category
    w.physics = SubjectFactory(school=school, code="PHY", name="Physique", category=w.sci)
    w.music = SubjectFactory(
        school=school, code="MUS", name="Musique", category=CategoryFactory(school=school, code="ART")
    )
    return w


def payload(w, **extra):
    return {
        "first_name": "Jean",
        "last_name": "Mbarga",
        "email": "jean.mbarga@ecole.test",
        "phone": "+237 600 00 00 00",
        "employee_number": "ENS-100",
        "hire_date": "2024-09-01",
        "pedagogical_category": str(w.sci.pk),
        "primary_subject": str(w.physics.pk),
        **extra,
    }


# =============================================================================
# Creation
# =============================================================================


def test_create_builds_the_whole_chain_without_password(w):
    body = data(as_(w.admin).post(TEACHERS, payload(w), format="json"), 201)
    assert (body["teacher_number"], body["first_name"], body["email"], body["active"]) == (
        "ENS-100",
        "Jean",
        "jean.mbarga@ecole.test",
        True,
    )
    assert body["subjects"] == ["PHY"] and body["account_activated"] is False
    teacher = TeacherProfile.objects.get(pk=body["id"])
    membership = teacher.employee.membership
    user = membership.user
    assert (membership.school, membership.status, membership.role_codes()) == (w.school, "ACTIVE", {"TEACHER"})
    assert not user.has_usable_password()  # no password typed, generated or shown
    assert teacher.employee.employee_type == "TEACHER"
    qualification = teacher.qualifications.get()
    assert (qualification.subject, qualification.status) == (w.physics, QualificationStatus.DECLARED)
    assert AuditLog.objects.filter(action="TEACHER_CREATED", entity_id=teacher.pk).exists()


def test_creation_is_all_or_nothing(w):
    admin = as_(w.admin)
    users, members, employees = User.objects.count(), SchoolMembership.objects.count(), EmployeeProfile.objects.count()
    # Incompatible primary subject (rule says no): refused AFTER user/membership/employee were built -> rolled back.
    SubjectCompatibilityRule.objects.create(
        school=w.school, pedagogical_category=w.sci, subject=w.music, compatible=False
    )
    err = error(admin.post(TEACHERS, payload(w, primary_subject=str(w.music.pk)), format="json"), 400)
    assert err["details"]["rule"] == "incompatible_subject"
    assert (User.objects.count(), SchoolMembership.objects.count(), EmployeeProfile.objects.count()) == (
        users,
        members,
        employees,
    )
    data(admin.post(TEACHERS, payload(w), format="json"), 201)
    err = error(
        admin.post(TEACHERS, payload(w, email="autre@ecole.test", employee_number="ens-100"), format="json"), 409
    )
    assert err["details"]["rule"] == "duplicate_employee_number"
    err = error(admin.post(TEACHERS, payload(w, employee_number="ENS-101"), format="json"), 409)
    assert err["details"]["rule"] == "already_employee"
    with pytest.raises(IntegrityError), transaction.atomic():  # PostgreSQL agrees on the number
        EmployeeProfile.objects.create(
            school=w.school,
            membership=member_with_role(w.school, "TEACHER"),
            employee_number="ENS-100",
            employee_type="TEACHER",
        )


def test_accounts_of_other_schools_are_never_attached(w):
    other = SchoolFactory(code="OTHERT")
    outsider = member_with_role(other, "PARENT")
    err = error(as_(w.admin).post(TEACHERS, payload(w, email=outsider.user.email), format="json"), 409)
    assert err["details"]["rule"] == "email_in_use"
    assert not SchoolMembership.objects.filter(school=w.school, user=outsider.user).exists()
    # A member of THIS school without employee profile (e.g. a parent) becomes a teacher: same account.
    parent = member_with_role(w.school, "PARENT")
    body = data(as_(w.admin).post(TEACHERS, payload(w, email=parent.user.email), format="json"), 201)
    teacher = TeacherProfile.objects.get(pk=body["id"])
    assert teacher.employee.membership == parent
    assert parent.role_codes() == {"PARENT", "TEACHER"}  # the role comes from the catalogue


def test_input_validation(w):
    admin = as_(w.admin)
    assert (
        error(admin.post(TEACHERS, payload(w, email="pas-un-email"), format="json"), 400)["code"] == "VALIDATION_ERROR"
    )
    assert error(admin.post(TEACHERS, payload(w, first_name=""), format="json"), 400)
    w.physics.active = False
    w.physics.save()
    assert error(admin.post(TEACHERS, payload(w), format="json"), 400)["details"]["rule"] == "subject_inactive"


# =============================================================================
# Read, update, activation
# =============================================================================


def test_list_filters_search_and_detail(w):
    admin = as_(w.admin)
    created = data(admin.post(TEACHERS, payload(w), format="json"), 201)
    rows = data(admin.get(TEACHERS))
    assert len(rows) == 3 and {"subjects", "email", "active"} <= set(rows[0])
    assert [r["id"] for r in data(admin.get(f"{TEACHERS}?search=mbarg"))] == [created["id"]]
    assert [r["id"] for r in data(admin.get(f"{TEACHERS}?search=ens-100"))] == [created["id"]]
    assert {r["id"] for r in data(admin.get(f"{TEACHERS}?category={w.lit.pk}"))} == {str(w.tf.pk)}
    assert {r["id"] for r in data(admin.get(f"{TEACHERS}?subject={w.maths.pk}"))} == {str(w.tm.pk)}
    assert len(data(admin.get(f"{TEACHERS}?status=inactive"))) == 0
    page = admin.get(f"{TEACHERS}?page_size=2").json()
    assert page["meta"]["count"] == 3 and len(page["data"]) == 2
    detail = data(admin.get(f"{TEACHERS}{w.tm.pk}/"))
    assert detail["active_course_count"] == 2 and detail["upcoming_session_count"] == 0


def test_update_identity_hr_and_profile(w):
    admin = as_(w.admin)
    url = f"{TEACHERS}{w.tm.pk}/"
    body = data(
        admin.patch(url, {"first_name": "Paul", "phone": "+237 699", "address": "Akwa", "bio": "Agrégé"}, format="json")
    )
    assert (body["first_name"], body["phone"], body["address"], body["bio"]) == ("Paul", "+237 699", "Akwa", "Agrégé")
    err = error(admin.patch(url, {"employee_number": w.tf.employee.employee_number}, format="json"), 409)
    assert err["details"]["rule"] == "duplicate_employee_number"
    err = error(admin.patch(url, {"email": w.tf.employee.membership.user.email.upper()}, format="json"), 409)
    assert err["details"]["rule"] == "email_in_use"
    body = data(admin.patch(url, {"primary_subject": str(w.physics.pk)}, format="json"))
    assert body["primary_subject"]["code"] == "PHY" and "PHY" in body["subjects"]  # judged by the engine
    assert AuditLog.objects.filter(action="TEACHER_UPDATED", entity_id=w.tm.pk).count() == 2


def test_deactivation_respects_courses_and_sessions(w):
    admin = as_(w.admin)
    url = f"{TEACHERS}{w.tm.pk}/"
    err = error(admin.post(f"{url}deactivate/"), 409)
    assert err["details"]["rule"] == "teacher_in_use" and err["details"]["context"] == {"courses": 2, "sessions": 0}
    err = error(admin.patch(url, {"employment_status": "TERMINATED"}, format="json"), 409)
    assert err["details"]["rule"] == "teacher_in_use"  # same rule through the form
    # Sessions still to come block too (courses inactive, planning kept).
    slot(w)
    generate(w)
    w.tm.courses.update(active=False)
    with mock.patch("django.utils.timezone.localdate", return_value=MONDAY - timedelta(days=1)):
        err = error(admin.post(f"{url}deactivate/"), 409)
    assert err["details"]["context"] == {"courses": 0, "sessions": 1}
    body = data(admin.post(f"{url}deactivate/"))  # today: the session is past
    assert (body["professional_status"], body["active"]) == ("INACTIVE", False)
    assert w.tm.sessions.count() == 1 and w.tm.courses.count() == 2  # history kept
    assert [r["id"] for r in data(admin.get(f"{TEACHERS}?status=inactive"))] == [str(w.tm.pk)]
    body = data(admin.post(f"{url}reactivate/"))
    assert body["active"] is True
    data(admin.patch(url, {"employment_status": "TERMINATED", "professional_status": "INACTIVE"}, format="json"))
    assert error(admin.post(f"{url}reactivate/"), 400)["details"]["rule"] == "employment_not_active"
    with pytest.raises(Exception):  # noqa: B017 — PROTECT: a teacher with history cannot be deleted
        with transaction.atomic():
            TeacherProfile.objects.filter(pk=w.tm.pk).delete()


# =============================================================================
# Qualifications, compatibility, overrides
# =============================================================================


def test_qualifications_follow_the_engine(w):
    admin = as_(w.admin)
    url = f"{TEACHERS}{w.tm.pk}/qualifications/"
    # Same category, no rule: compatible -> DECLARED, then verified by the admin.
    body = data(admin.post(url, {"subject": str(w.physics.pk)}, format="json"), 201)
    assert (body["status"], body["computed_compatibility"], body["current_compatibility"]) == (
        "DECLARED",
        "COMPATIBLE",
        "COMPATIBLE",
    )
    assert error(admin.post(url, {"subject": str(w.physics.pk)}, format="json"), 409)["details"]["rule"] == (
        "already_qualified"
    )
    verified = data(admin.post(f"/api/v1/teacher-qualifications/{body['id']}/verify/"))
    assert verified["status"] == "VERIFIED" and verified["verified"] is True
    # Other category, no rule: review needed -> PENDING.
    body = data(admin.post(url, {"subject": str(w.french.pk)}, format="json"), 201)
    assert (body["status"], body["computed_compatibility"]) == ("PENDING", "REQUIRES_REVIEW")
    # A rule refuses music: incompatible, nothing stored, the reason is explained.
    SubjectCompatibilityRule.objects.create(
        school=w.school, pedagogical_category=w.sci, subject=w.music, compatible=False
    )
    err = error(admin.post(url, {"subject": str(w.music.pk)}, format="json"), 400)
    assert err["details"]["rule"] == "incompatible_subject"
    assert not TeacherSubjectQualification.objects.filter(teacher=w.tm, subject=w.music).exists()
    verdict = data(admin.get(f"{TEACHERS}{w.tm.pk}/compatibility/?subject={w.music.pk}"))
    assert (verdict["result"], verdict["reason"]) == ("INCOMPATIBLE", "rule_incompatible")
    assert verdict["rule"]["compatible"] is False and verdict["rule"]["subject"]["code"] == "MUS"
    assert data(admin.get(f"{TEACHERS}{w.tm.pk}/compatibility/?subject={w.maths.pk}"))["reason"] == "primary_subject"
    assert data(admin.get(f"{TEACHERS}{w.tm.pk}/compatibility/?subject={w.physics.pk}"))["reason"] == "same_category"
    rules = data(admin.get(f"{TEACHERS}{w.tm.pk}/compatibility-rules/"))
    assert [(r["subject"]["code"], r["compatible"]) for r in rules] == [("MUS", False)]


def test_override_then_qualification(w):
    admin = as_(w.admin)
    SubjectCompatibilityRule.objects.create(
        school=w.school, pedagogical_category=w.sci, subject=w.music, compatible=False
    )
    url = f"{TEACHERS}{w.tm.pk}/overrides/"
    assert error(admin.post(url, {"subject": str(w.music.pk), "reason": " "}, format="json"), 400)
    past = (timezone.now() - timedelta(days=1)).isoformat()
    assert (
        error(admin.post(url, {"subject": str(w.music.pk), "reason": "x", "expires_at": past}, format="json"), 400)[
            "details"
        ]["rule"]
        == "expiry_past"
    )
    body = data(admin.post(url, {"subject": str(w.music.pk), "reason": "Diplôme de conservatoire"}, format="json"), 201)
    assert body["active"] is True and body["approved_by"]
    verdict = data(admin.get(f"{TEACHERS}{w.tm.pk}/compatibility/?subject={w.music.pk}"))
    assert (verdict["result"], verdict["reason"], verdict["override"]["reason"]) == (
        "OVERRIDDEN",
        "override",
        "Diplôme de conservatoire",
    )
    body = data(admin.post(f"{TEACHERS}{w.tm.pk}/qualifications/", {"subject": str(w.music.pk)}, format="json"), 201)
    assert (body["status"], body["source"], body["computed_compatibility"]) == ("DECLARED", "OVERRIDE", "OVERRIDDEN")
    assert AuditLog.objects.filter(action="COMPATIBILITY_OVERRIDE_GRANTED").exists()
    assert [o["subject"]["code"] for o in data(admin.get(url))] == ["MUS"]


def test_withdraw_qualification_rules(w):
    admin = as_(w.admin)
    primary = w.tm.qualifications.get(subject=w.maths)
    err = error(admin.post(f"/api/v1/teacher-qualifications/{primary.pk}/reject/", {"reason": "x"}, format="json"), 409)
    assert err["details"]["rule"] == "primary_subject_qualification"
    physics = data(
        admin.post(f"{TEACHERS}{w.tm.pk}/qualifications/", {"subject": str(w.physics.pk)}, format="json"), 201
    )
    body = data(
        admin.post(
            f"/api/v1/teacher-qualifications/{physics['id']}/reject/", {"reason": "Pas de diplôme"}, format="json"
        )
    )
    assert (body["status"], body["notes"]) == ("REJECTED", "Pas de diplôme")
    assert "PHY" not in data(admin.get(f"{TEACHERS}{w.tm.pk}/"))["subjects"]
    again = data(admin.post(f"{TEACHERS}{w.tm.pk}/qualifications/", {"subject": str(w.physics.pk)}, format="json"), 201)
    assert again["id"] == physics["id"] and again["status"] == "DECLARED"  # judged again, same row
    # Used by an active course: cannot be withdrawn.
    french = data(admin.post(f"{TEACHERS}{w.tm.pk}/qualifications/", {"subject": str(w.french.pk)}, format="json"), 201)
    data(admin.post(f"/api/v1/teacher-qualifications/{french['id']}/verify/"))
    from apps.gradebook import services as gb

    gb.create_course(w.klass_b, w.french, w.tm, actor=w.admin)  # the qualification now prepares a Course
    err = error(
        admin.post(f"/api/v1/teacher-qualifications/{french['id']}/reject/", {"reason": "x"}, format="json"), 409
    )
    assert err["details"]["rule"] == "qualification_in_use"


# =============================================================================
# Isolation and permissions
# =============================================================================


def test_cross_school_isolation(w):
    other = SchoolFactory(code="OTHERU")
    other_admin = member_with_role(other, "ADMIN")
    foreign_category = CategoryFactory(school=other, code="FSCI")
    foreign_subject = SubjectFactory(school=other, code="FMATH", category=foreign_category)
    admin = as_(w.admin)
    from .factories import make_teacher

    foreign = make_teacher(other, category=foreign_category, primary_subject=foreign_subject)
    assert str(foreign.pk) not in {r["id"] for r in data(admin.get(TEACHERS))}
    for method, url, body in (
        ("get", f"{TEACHERS}{foreign.pk}/", None),
        ("patch", f"{TEACHERS}{foreign.pk}/", {"first_name": "x"}),
        ("post", f"{TEACHERS}{foreign.pk}/deactivate/", None),
        ("post", f"{TEACHERS}{foreign.pk}/qualifications/", {"subject": str(w.maths.pk)}),
        ("get", f"{TEACHERS}{foreign.pk}/compatibility/?subject={w.maths.pk}", None),
        ("post", f"{TEACHERS}{foreign.pk}/overrides/", {"subject": str(w.maths.pk), "reason": "x"}),
        ("post", f"/api/v1/teacher-qualifications/{foreign.qualifications.get().pk}/verify/", None),
        # our teacher, another school's subject / category: 404 as well
        ("post", f"{TEACHERS}{w.tm.pk}/qualifications/", {"subject": str(foreign_subject.pk)}),
        ("post", TEACHERS, payload(w, pedagogical_category=str(foreign_category.pk))),
    ):
        response = getattr(admin, method)(url, body, format="json")
        assert response.status_code == 404, (method, url, response.json())
    # The services refuse it too (not only the school-scoped lookups).
    with pytest.raises(PermissionDenied):
        people.admin_update_teacher(w.tm, actor=other_admin, first_name="x")
    with pytest.raises(ValidationError) as exc:
        people.admin_add_qualification(w.tm, foreign_subject, actor=w.admin)
    assert exc.value.code == "subject_other_school"
    with pytest.raises(ValidationError) as exc:
        people.admin_create_teacher(
            w.school,
            actor=w.admin,
            first_name="A",
            last_name="B",
            email="a.b@ecole.test",
            employee_number="E-9",
            pedagogical_category=foreign_category,
            primary_subject=w.physics,
        )
    assert exc.value.code == "category_other_school"


def test_permissions(w):
    teacher = as_(w.tm_member)
    # A teacher sees only themselves (unchanged), without the admin fields.
    rows = data(teacher.get(TEACHERS))
    assert [r["id"] for r in rows] == [str(w.tm.pk)] and "email" not in rows[0]
    assert error(teacher.post(TEACHERS, payload(w), format="json"), 403)
    assert error(teacher.patch(f"{TEACHERS}{w.tm.pk}/", {"first_name": "x"}, format="json"), 403)
    assert error(
        teacher.post(f"{TEACHERS}{w.tm.pk}/qualifications/", {"subject": str(w.physics.pk)}, format="json"), 403
    )
    assert error(
        teacher.post(f"{TEACHERS}{w.tm.pk}/overrides/", {"subject": str(w.music.pk), "reason": "moi"}, format="json"),
        403,
    )
    assert error(teacher.get(f"{TEACHERS}{w.tm.pk}/compatibility/?subject={w.music.pk}"), 403)
    assert error(teacher.post(f"{TEACHERS}{w.tm.pk}/deactivate/"), 403)
    assert as_(w.tm_member).get(f"{TEACHERS}{w.tf.pk}/").status_code == 404
    staff = member_with_role(w.school, "STAFF")
    assert data(as_(staff).get(TEACHERS)) == []
    with pytest.raises(PermissionDenied):
        people.admin_grant_override(w.tm, w.music, actor=w.tm_member, reason="moi")
    with pytest.raises(PermissionDenied):
        people.admin_add_qualification(w.tm, w.physics, actor=w.tm_member)
    assert TeacherProfile.objects.get(pk=w.tm.pk).professional_status == ProfessionalStatus.ACTIVE


def test_dashboard_teacher_stats(w):
    body = data(as_(w.admin).get("/api/v1/admin/dashboard/teachers/"))
    assert body["active"] == 2 and {(c["code"], c["count"]) for c in body["by_category"]} == {
        (w.sci.code, 1),
        (w.lit.code, 1),
    }
    assert error(as_(w.tm_member).get("/api/v1/admin/dashboard/teachers/"), 403)
