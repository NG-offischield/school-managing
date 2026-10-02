"""Academic core API: authentication, role scopes, school isolation, writes."""

import uuid
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.gradebook import services as gb
from apps.gradebook.models import GradeChangeLog
from apps.people import services as people
from apps.people.models import VerificationMethod

from .conftest import DB
from .factories import ParentFactory, SchoolFactory, StudentFactory, member_with_role
from .gradebook_world import make_world

pytestmark = DB


@pytest.fixture
def w(school):
    return make_world(school)


def as_(membership):
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


def data(response, expected=200):
    assert response.status_code == expected, response.json()
    return response.json()["data"]


def ids(response):
    return {row["id"] for row in data(response)}


@pytest.mark.parametrize(
    "url",
    ["/api/v1/courses/", "/api/v1/assessments/", "/api/v1/grades/", "/api/v1/report-cards/", "/api/v1/grading-scales/"],
)
def test_endpoints_require_authentication(api, url):
    assert api.get(url).status_code == 401


def test_grading_scales_listed_for_members(w):
    rows = data(as_(member_with_role(w.school, "PARENT")).get("/api/v1/grading-scales/"))
    assert {r["code"] for r in rows} == {"SUR20", "SUR100", "SUR60"}


# --- Teacher scope -------------------------------------------------------------------


def test_teacher_sees_only_own_courses_assessments_and_grades(w):
    a_maths, a_french = w.assess(), w.assess(course=w.course_french)
    g_maths, g_french = w.grade(a_maths, w.students[0], 10), w.grade(a_french, w.students[0], 12)
    client = as_(w.tm_member)
    assert ids(client.get("/api/v1/courses/")) == {str(w.course_maths.id)}
    assert ids(client.get("/api/v1/assessments/")) == {str(a_maths.id)}
    assert ids(client.get("/api/v1/grades/")) == {str(g_maths.id)}
    assert str(g_french.id) not in ids(client.get(f"/api/v1/grades/?assessment={a_french.id}"))


def test_teacher_now_sees_students_of_their_classes_only(w):
    outsider = StudentFactory(school=w.school)
    seen = ids(as_(w.tm_member).get("/api/v1/students/"))
    assert seen == {str(s.id) for s in w.students}
    assert str(outsider.id) not in seen


def test_teacher_creates_assessment_for_own_course_only(w):
    client = as_(w.tm_member)
    body = {
        "course": str(w.course_maths.id),
        "academic_period": str(w.s1.id),
        "name": "Interro",
        "assessment_type": "TEST",
        "max_score": "10",
    }
    created = data(client.post("/api/v1/assessments/", body, format="json"), 201)
    assert created["max_score"] == "10.00" and created["status"] == "OPEN"
    body["course"] = str(w.course_french.id)
    response = client.post("/api/v1/assessments/", body, format="json")
    assert (response.status_code, response.json()["error"]["code"]) == (403, "PERMISSION_DENIED")


def test_business_rule_errors_carry_the_rule_code(w):
    body = {
        "course": str(w.course_maths.id),
        "academic_period": str(w.t1.id),
        "name": "x",
        "assessment_type": "EXAM",
        "max_score": "20",
    }
    response = as_(w.tm_member).post("/api/v1/assessments/", body, format="json")
    assert response.status_code == 400
    error = response.json()["error"]
    assert (error["code"], error["details"]["rule"]) == ("BUSINESS_RULE_VIOLATION", "period_not_leaf")


def test_bulk_grades_then_correction_with_history(w):
    a = w.assess(max_score=20)
    client = as_(w.tm_member)
    body = {"assessment": str(a.id), "grades": [{"student": str(s.id), "score": "12.5"} for s in w.students]}
    grades = data(client.post("/api/v1/grades/bulk/", body, format="json"), 201)
    assert len(grades) == 3
    grade_id = grades[0]["id"]

    no_reason = client.put(f"/api/v1/grades/{grade_id}/", {"score": "14"}, format="json")
    assert no_reason.json()["error"]["code"] == "VALIDATION_ERROR"
    updated = data(
        client.put(
            f"/api/v1/grades/{grade_id}/",
            {"score": "14", "reason": "Erreur de report", "expected_score": "12.5"},
            format="json",
        )
    )
    assert updated["score"] == "14.00"
    assert GradeChangeLog.objects.get(grade_id=grade_id).reason == "Erreur de report"

    stale = client.put(
        f"/api/v1/grades/{grade_id}/", {"score": "15", "reason": "x", "expected_score": "12.5"}, format="json"
    )
    assert (stale.status_code, stale.json()["error"]["code"]) == (409, "CONFLICT")


def test_bulk_with_one_bad_score_creates_nothing(w):
    a = w.assess(max_score=20)
    body = {
        "assessment": str(a.id),
        "grades": [
            {"student": str(w.students[0].id), "score": "10"},
            {"student": str(w.students[1].id), "score": "21"},
        ],
    }
    response = as_(w.tm_member).post("/api/v1/grades/bulk/", body, format="json")
    assert response.json()["error"]["details"]["rule"] == "score_out_of_range"
    assert data(as_(w.admin).get(f"/api/v1/grades/?assessment={a.id}")) == []


def test_grades_frozen_after_period_close(w):
    g = w.grade(w.assess(), w.students[0], 10)
    gb.close_period(w.t1, actor=w.admin)
    response = as_(w.tm_member).put(f"/api/v1/grades/{g.id}/", {"score": "11", "reason": "x"}, format="json")
    assert response.json()["error"]["details"]["rule"] == "assessment_closed"


# --- Isolation -------------------------------------------------------------------------


def test_ids_of_another_school_are_404(w):
    other = make_world(SchoolFactory())
    a_other = other.assess()
    g_other = other.grade(a_other, other.students[0], 10)
    client = as_(w.admin)
    assert client.put(f"/api/v1/grades/{g_other.id}/", {"score": "1", "reason": "x"}, format="json").status_code == 404
    body = {"assessment": str(a_other.id), "grades": [{"student": str(w.students[0].id), "score": "1"}]}
    assert client.post("/api/v1/grades/bulk/", body, format="json").status_code == 404
    body = {
        "course": str(other.course_maths.id),
        "academic_period": str(w.s1.id),
        "name": "x",
        "assessment_type": "EXAM",
        "max_score": "20",
    }
    assert client.post("/api/v1/assessments/", body, format="json").status_code == 404
    assert str(g_other.id) not in ids(client.get("/api/v1/grades/"))
    assert client.get(f"/api/v1/students/{other.students[0].id}/evolution/").status_code == 404
    assert client.get(f"/api/v1/report-cards/{uuid.uuid4()}/").status_code == 404


# --- Parents, report cards, evolution --------------------------------------------------


def verified_parent_of(w, student):
    parent = ParentFactory(school=w.school)
    link = people.link_parent(parent, student, relationship_type="MOTHER")
    people.verify_parent_link(link, actor=w.admin, method=VerificationMethod.ADMIN_IN_PERSON)
    return parent.membership


def test_parent_sees_only_their_childs_grades_and_validated_cards(w):
    a = w.assess()
    mine, other = w.grade(a, w.students[0], 15), w.grade(a, w.students[1], 9)
    parent = verified_parent_of(w, w.students[0])
    client = as_(parent)
    assert ids(client.get("/api/v1/grades/")) == {str(mine.id)}
    assert str(other.id) not in ids(client.get(f"/api/v1/grades/?student={w.students[1].id}"))

    gb.generate_report_cards(w.klass, w.t1, actor=w.admin)
    assert data(client.get("/api/v1/report-cards/")) == []  # drafts are not official
    gb.close_period(w.t1, actor=w.admin)
    card = data(
        as_(w.admin).post(
            "/api/v1/report-cards/generate/",
            {"school_class": str(w.klass.id), "academic_period": str(w.t1.id)},
            format="json",
        ),
        201,
    )
    child_card = next(c for c in card if c["student"] == str(w.students[0].id))
    data(as_(w.admin).post(f"/api/v1/report-cards/{child_card['id']}/validate/"))
    visible = data(client.get("/api/v1/report-cards/"))
    assert [c["id"] for c in visible] == [child_card["id"]]
    assert visible[0]["lines"][0]["subject_code"] == "MATH"


def test_only_admins_generate_and_validate(w):
    body = {"school_class": str(w.klass.id), "academic_period": str(w.t1.id)}
    assert as_(w.tm_member).post("/api/v1/report-cards/generate/", body, format="json").status_code == 403


def test_evolution_endpoint(w):
    w.grade(w.assess(period=w.s1), w.students[0], 16)
    rows = data(as_(w.admin).get(f"/api/v1/students/{w.students[0].id}/evolution/"))
    by_period = {p["period"]: p for p in rows["periods"]}
    assert Decimal(by_period["Séquence 1"]["general_average"]) == Decimal("16.00")
    assert by_period["Séquence 2"]["general_average"] is None
    assert rows["academic_year"] == str(w.year.id)
