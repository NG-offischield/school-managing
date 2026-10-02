"""Read API of School + Academic + People: authentication, permissions,
school isolation (spec §8)."""

import uuid

import pytest
from rest_framework.test import APIClient

from apps.people import services
from apps.people.models import EmployeeType, VerificationMethod

from .conftest import DB
from .factories import (
    AcademicYearFactory,
    EmployeeFactory,
    LevelFactory,
    ParentFactory,
    SchoolClassFactory,
    SchoolFactory,
    StaffFunctionFactory,
    StudentFactory,
    SubjectFactory,
    admin_of,
    make_teacher,
    member_with_role,
)

pytestmark = DB

ENDPOINTS = [
    "/api/v1/school/",
    "/api/v1/academic-years/",
    "/api/v1/academic-periods/",
    "/api/v1/levels/",
    "/api/v1/pedagogical-categories/",
    "/api/v1/subjects/",
    "/api/v1/classes/",
    "/api/v1/students/",
    "/api/v1/parents/children/",
    "/api/v1/teachers/",
    "/api/v1/staff/",
]


def client_for(membership):
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


def ids(response):
    assert response.status_code == 200, response.json()
    return {row["id"] for row in response.json()["data"]}


@pytest.mark.parametrize("url", ENDPOINTS)
def test_every_endpoint_requires_authentication(api, url):
    response = api.get(url)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "NOT_AUTHENTICATED"


@pytest.mark.parametrize("url", ENDPOINTS)
def test_every_endpoint_requires_an_active_membership(url):
    from .factories import UserFactory

    client = APIClient()
    client.force_authenticate(UserFactory())
    assert client.get(url).json()["error"]["code"] == "NO_ACTIVE_MEMBERSHIP"


@pytest.fixture
def two_schools():
    """School A and school B with the same kind of data in each."""
    data = {}
    for key in ("a", "b"):
        school = SchoolFactory()
        year = AcademicYearFactory(school=school)
        data[key] = {
            "school": school,
            "admin": admin_of(school),
            "year": year,
            "level": LevelFactory(school=school),
            "subject": SubjectFactory(school=school),
            "class": SchoolClassFactory(school=school, academic_year=year),
            "student": StudentFactory(school=school),
            "teacher": make_teacher(school),
        }
    return data


def test_current_school_endpoint(two_schools):
    a = two_schools["a"]
    data = client_for(a["admin"]).get("/api/v1/school/").json()["data"]
    assert data["code"] == a["school"].code
    assert data["configuration"]["default_late_threshold_minutes"] == 15
    assert data["branding"]["primary_color"] == "#173B73"


@pytest.mark.parametrize(
    "url,key",
    [
        ("/api/v1/academic-years/", "year"),
        ("/api/v1/levels/", "level"),
        ("/api/v1/subjects/", "subject"),
        ("/api/v1/classes/", "class"),
        ("/api/v1/students/", "student"),
        ("/api/v1/teachers/", "teacher"),
    ],
)
def test_lists_only_contain_current_school_rows(two_schools, url, key):
    a, b = two_schools["a"], two_schools["b"]
    seen = ids(client_for(a["admin"]).get(url))
    assert str(a[key].id) in seen
    assert str(b[key].id) not in seen


@pytest.mark.parametrize(
    "url_template,key",
    [
        ("/api/v1/academic-years/{id}/", "year"),
        ("/api/v1/students/{id}/", "student"),
        ("/api/v1/students/{id}/enrollments/", "student"),
        ("/api/v1/teachers/{id}/", "teacher"),
        ("/api/v1/teachers/{id}/qualifications/", "teacher"),
    ],
)
def test_school_b_ids_are_unreachable_from_school_a(two_schools, url_template, key):
    """Changing the id in the URL to one of school B gives nothing."""
    a, b = two_schools["a"], two_schools["b"]
    client = client_for(a["admin"])
    own = client.get(url_template.format(id=a[key].id))
    foreign = client.get(url_template.format(id=b[key].id))
    assert own.status_code == 200
    if foreign.status_code == 200:  # list endpoints answer an empty list
        assert foreign.json()["data"] == []
    else:
        assert foreign.status_code == 404
        assert foreign.json() == client.get(url_template.format(id=uuid.uuid4())).json()


def test_period_filter_rejects_malformed_uuid(two_schools):
    response = client_for(two_schools["a"]["admin"]).get("/api/v1/academic-periods/?academic_year=nope")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_enrollment_history_endpoint(two_schools):
    a = two_schools["a"]
    services.enroll_student(a["student"], a["class"])
    rows = client_for(a["admin"]).get(f"/api/v1/students/{a['student'].id}/enrollments/").json()["data"]
    assert [(r["class_name"], r["promotion_status"]) for r in rows] == [(a["class"].name, "PENDING")]


# --- Role-based visibility ------------------------------------------------------------


def test_parent_sees_only_verified_children(school):
    parent = ParentFactory(school=school)
    verified_child, declared_child, stranger = (StudentFactory(school=school) for _ in range(3))
    link = services.link_parent(parent, verified_child, relationship_type="MOTHER")
    services.verify_parent_link(link, actor=admin_of(school), method=VerificationMethod.ADMIN_IN_PERSON)
    services.link_parent(parent, declared_child, relationship_type="MOTHER")  # declared only

    client = client_for(parent.membership)
    assert ids(client.get("/api/v1/students/")) == {str(verified_child.id)}
    children = client.get("/api/v1/parents/children/").json()["data"]
    assert [c["student"]["id"] for c in children] == [str(verified_child.id)]
    for hidden in (declared_child, stranger):
        assert client.get(f"/api/v1/students/{hidden.id}/").status_code == 404


def test_teacher_sees_only_their_own_profile_and_no_students_yet(school):
    me, colleague = make_teacher(school), make_teacher(school)
    StudentFactory(school=school)
    client = client_for(me.employee.membership)
    assert ids(client.get("/api/v1/teachers/")) == {str(me.id)}
    assert client.get(f"/api/v1/teachers/{colleague.id}/").status_code == 404
    assert client.get(f"/api/v1/teachers/{colleague.id}/qualifications/").json()["data"] == []
    assert ids(client.get("/api/v1/students/")) == set()  # scope needs courses (next phase)


def test_staff_sees_self_admin_sees_all(school):
    admin = admin_of(school)
    staff = [
        services.create_staff(EmployeeFactory(school=school, employee_type=EmployeeType.STAFF), staff_number=f"P{i}")
        for i in range(2)
    ]
    services.assign_staff_function(staff[0], StaffFunctionFactory(school=school, code="BURSAR"), actor=admin)
    assert ids(client_for(admin).get("/api/v1/staff/")) == {str(s.id) for s in staff}
    mine = client_for(staff[0].employee.membership).get("/api/v1/staff/").json()["data"]
    assert [(m["id"], m["functions"]) for m in mine] == [(str(staff[0].id), ["BURSAR"])]


def test_guardian_and_content_manager_see_no_people(school):
    StudentFactory(school=school)
    make_teacher(school)
    for role in ("GUARDIAN", "CONTENT_MANAGER"):
        client = client_for(member_with_role(school, role))
        assert ids(client.get("/api/v1/students/")) == set()
        assert ids(client.get("/api/v1/teachers/")) == set()
        assert ids(client.get("/api/v1/staff/")) == set()


def test_catalogues_readable_by_every_member(school):
    year = AcademicYearFactory(school=school)
    client = client_for(member_with_role(school, "PARENT"))
    assert str(year.id) in ids(client.get("/api/v1/academic-years/"))
