"""Planning API: admin desktop flows, teacher and parent visibility,
isolation, conflict answers. ADR 0012."""

import pytest
from rest_framework.test import APIClient

from apps.people import services as people
from apps.people.models import VerificationMethod
from apps.scheduling import services as planning
from apps.scheduling.models import TeachingSession

from .conftest import DB
from .factories import ParentFactory, SchoolFactory, member_with_role
from .planning_world import MONDAY, at, generate, make_planning_world, slot

pytestmark = DB


@pytest.fixture
def w(school):
    return make_planning_world(school)


def as_(membership):
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


def data(response, expected=200):
    assert response.status_code == expected, response.json()
    return response.json()["data"]


def verified_parent(w, student):
    parent = ParentFactory(school=w.school)
    link = people.link_parent(parent, student, relationship_type="MOTHER")
    people.verify_parent_link(link, actor=w.admin, method=VerificationMethod.ADMIN_IN_PERSON)
    return parent.membership


# --- Admin desktop flows ------------------------------------------------------------


def test_admin_builds_a_timetable_through_the_api(w):
    admin = as_(w.admin)
    room = data(
        admin.post("/api/v1/admin/rooms/", {"code": "r20", "name": "Salle 20", "capacity": 35}, format="json"), 201
    )
    body = {
        "course": str(w.course_maths.id),
        "weekday": 1,
        "start_time": "08:00",
        "end_time": "10:00",
        "room": room["id"],
    }
    check = data(admin.post("/api/v1/admin/schedules/check/", body, format="json"))
    assert check["conflicts"] == []
    created = data(admin.post("/api/v1/admin/schedules/", body, format="json"), 201)
    assert (created["room"]["code"], created["teacher"]["id"]) == ("R20", str(w.tm.id))
    summary = data(
        admin.post(
            "/api/v1/admin/sessions/generate/", {"date_from": str(MONDAY), "date_to": str(MONDAY)}, format="json"
        )
    )
    assert summary["created"] == 1


def test_conflict_is_409_with_context(w):
    slot(w)
    body = {
        "course": str(w.course_french.id),
        "weekday": 1,
        "start_time": "09:00",
        "end_time": "11:00",
        "room": str(w.lab.id),
    }
    response = as_(w.admin).post("/api/v1/admin/schedules/", body, format="json")
    assert response.status_code == 409
    error = response.json()["error"]
    assert (error["code"], error["details"]["rule"]) == ("CONFLICT", "planning_conflict")
    assert error["details"]["context"]["conflicts"][0]["kinds"] == ["CLASS"]


def test_admin_session_actions_via_api(w):
    slot(w)
    generate(w)
    session = TeachingSession.objects.get()
    admin = as_(w.admin)
    moved = data(
        admin.post(
            f"/api/v1/admin/sessions/{session.id}/move/",
            {"new_start": at(14).isoformat(), "new_end": at(16).isoformat(), "reason": "Sortie"},
            format="json",
        )
    )
    assert moved["is_moved"] is True
    cancelled = data(admin.post(f"/api/v1/admin/sessions/{session.id}/cancel/", {"reason": "Grève"}, format="json"))
    assert cancelled["status"] == "CANCELLED"
    feed = data(admin.get("/api/v1/admin/planning/changes/?notification_status=PENDING"))
    assert {c["change_type"] for c in feed} >= {"SESSION_MOVED", "SESSION_CANCELLED"}


def test_courses_admin_endpoints(w):
    admin = as_(w.admin)
    body = {"school_class": str(w.klass_b.id), "subject": str(w.french.id), "teacher": str(w.tf.id), "coefficient": "3"}
    course = data(admin.post("/api/v1/admin/courses/", body, format="json"), 201)
    assert course["coefficient"] == "3.00"
    slot(w)
    response = admin.post(f"/api/v1/admin/courses/{w.course_maths.id}/deactivate/")
    assert (response.status_code, response.json()["error"]["details"]["rule"]) == (409, "course_scheduled")
    assert data(admin.post(f"/api/v1/admin/courses/{course['id']}/deactivate/"))["active"] is False


def test_admin_endpoints_are_admin_only(w):
    body = {"course": str(w.course_maths.id), "weekday": 1, "start_time": "08:00", "end_time": "10:00"}
    for member in (w.tm_member, member_with_role(w.school, "STAFF"), member_with_role(w.school, "PARENT")):
        assert as_(member).post("/api/v1/admin/schedules/", body, format="json").status_code == 403
        assert as_(member).get("/api/v1/admin/planning/changes/").status_code == 403


def test_cross_school_ids_are_404(w):
    other = make_planning_world(SchoolFactory())
    admin = as_(w.admin)
    body = {"course": str(other.course_maths.id), "weekday": 1, "start_time": "08:00", "end_time": "10:00"}
    assert admin.post("/api/v1/admin/schedules/", body, format="json").status_code == 404
    body = {
        "course": str(w.course_maths.id),
        "weekday": 1,
        "start_time": "08:00",
        "end_time": "10:00",
        "room": str(other.r12.id),
    }
    assert admin.post("/api/v1/admin/schedules/", body, format="json").status_code == 404
    slot(other)
    generate(other)
    foreign = TeachingSession.objects.get(school=other.school)
    assert admin.post(f"/api/v1/admin/sessions/{foreign.id}/cancel/", {"reason": "x"}, format="json").status_code == 404
    assert admin.get(f"/api/v1/sessions/{foreign.id}/").status_code == 404


# --- Teacher -----------------------------------------------------------------------


def test_teacher_sees_own_timetable_and_sessions(w):
    slot(w)
    slot(w, course=w.course_french, start=(10, 0), end=(12, 0))
    generate(w)
    teacher = as_(w.tm_member)
    assert {s["subject"]["code"] for s in data(teacher.get("/api/v1/schedules/"))} == {"MATH"}
    assert {s["subject"]["code"] for s in data(teacher.get("/api/v1/teacher/sessions/"))} == {"MATH"}
    french = TeachingSession.objects.get(course=w.course_french)
    assert teacher.get(f"/api/v1/sessions/{french.id}/").status_code == 404


def test_substituting_teacher_sees_the_session_and_its_change(w):
    from .factories import make_teacher

    slot(w)
    generate(w)
    session = TeachingSession.objects.get()
    sub = make_teacher(w.school, category=w.maths.category, primary_subject=w.maths)
    planning.substitute_teacher(session, sub, actor=w.admin, reason="Remplacement")
    client = as_(sub.employee.membership)
    sessions = data(client.get("/api/v1/teacher/sessions/"))
    assert [s["id"] for s in sessions] == [str(session.id)] and sessions[0]["is_substituted"] is True
    assert {c["change_type"] for c in data(client.get("/api/v1/planning/changes/"))} == {"TEACHER_SUBSTITUTED"}
    # the planned teacher still sees it (planned) and is informed
    assert [s["id"] for s in data(as_(w.tm_member).get("/api/v1/teacher/sessions/"))] == [str(session.id)]


def test_teacher_availability_self_service(w):
    teacher = as_(w.tm_member)
    url = f"/api/v1/teachers/{w.tm.id}/availability/exceptions/"
    created = data(
        teacher.post(
            url,
            {"date": str(MONDAY), "start_time": "08:00", "end_time": "12:00", "reason": "Rendez-vous médical"},
            format="json",
        ),
        201,
    )
    assert created["status"] == "PENDING"
    assert [r["id"] for r in data(teacher.get(url))] == [created["id"]]
    # another teacher can neither see nor submit for them
    other = as_(w.tf_member)
    assert data(other.get(url)) == []
    response = other.post(
        url, {"date": str(MONDAY), "start_time": "08:00", "end_time": "09:00", "reason": "x"}, format="json"
    )
    assert response.status_code == 403
    # a teacher cannot decide; the admin can
    decide = f"/api/v1/admin/unavailability/{created['id']}/decide/"
    assert teacher.post(decide, {"decision": "APPROVED"}, format="json").status_code == 403
    pending = data(as_(w.admin).get("/api/v1/admin/unavailability/"))
    assert [p["id"] for p in pending] == [created["id"]]
    result = data(as_(w.admin).post(decide, {"decision": "REJECTED", "comment": "Examen ce jour-là"}, format="json"))
    assert result["request"]["status"] == "REJECTED"


def test_recurring_availability_declaration(w):
    teacher = as_(w.tm_member)
    url = f"/api/v1/teachers/{w.tm.id}/availability/"
    created = data(
        teacher.post(
            url,
            {
                "weekday": 3,
                "start_time": "13:00",
                "end_time": "17:00",
                "available": False,
                "reason": "Cours à l'université",
            },
            format="json",
        ),
        201,
    )
    withdrawn = data(teacher.post(f"{url}{created['id']}/withdraw/"))
    assert withdrawn["active"] is False


# --- Parent ------------------------------------------------------------------------


def test_parent_sees_child_class_planning_without_internal_data(w):
    slot(w)
    slot(w, course=w.course_b_maths, weekday=2, room=w.lab)  # another class
    generate(w, days=1)
    session = TeachingSession.objects.get(school_class=w.klass)
    planning.cancel_session(session, actor=w.admin, reason="Enseignant malade (confidentiel)")
    parent = as_(verified_parent(w, w.students[0]))

    timetable = data(parent.get(f"/api/v1/students/{w.students[0].id}/timetable/"))
    assert [s["school_class"]["name"] for s in timetable] == ["3e A"]
    sessions = data(parent.get("/api/v1/sessions/"))
    assert [s["id"] for s in sessions] == [str(session.id)]
    assert "planned_teacher" not in sessions[0] and "course" not in sessions[0]
    changes = data(parent.get("/api/v1/planning/changes/"))
    assert [c["change_type"] for c in changes] == ["SESSION_CANCELLED"]
    assert "reason" not in changes[0] and "changed_by" not in changes[0]  # internal data hidden
    assert parent.get("/api/v1/rooms/").json()["data"] == []


def test_unverified_parent_sees_nothing(w):
    slot(w)
    generate(w)
    parent = ParentFactory(school=w.school)
    people.link_parent(parent, w.students[0], relationship_type="FATHER")  # declared only
    client = as_(parent.membership)
    assert data(client.get("/api/v1/schedules/")) == []
    assert data(client.get("/api/v1/sessions/")) == []
    assert client.get(f"/api/v1/students/{w.students[0].id}/timetable/").status_code == 404


# --- Staff -------------------------------------------------------------------------


def test_staff_reads_the_planning(w):
    slot(w)
    generate(w)
    staff = as_(member_with_role(w.school, "STAFF"))
    assert len(data(staff.get("/api/v1/schedules/"))) == 1
    assert len(data(staff.get(f"/api/v1/sessions/?date_from={MONDAY}&date_to={MONDAY}"))) == 1
    assert {r["code"] for r in data(staff.get("/api/v1/rooms/"))} == {"R12", "LAB"}


def test_session_filters(w):
    slot(w)
    slot(w, course=w.course_french, start=(10, 0), end=(12, 0))
    generate(w, days=7)
    admin = as_(w.admin)
    by_teacher = data(admin.get(f"/api/v1/sessions/?teacher={w.tf.id}"))
    assert {s["subject"]["code"] for s in by_teacher} == {"FR"}
    by_day = data(admin.get(f"/api/v1/sessions/?date_from={MONDAY}&date_to={MONDAY}&school_class={w.klass.id}"))
    assert len(by_day) == 2
    assert admin.get("/api/v1/sessions/?date_from=not-a-date").json()["error"]["code"] == "VALIDATION_ERROR"
