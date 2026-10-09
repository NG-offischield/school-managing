"""Teacher -> parent: GET /teacher/contacts/ lists only the verified parents
of the pupils the teacher teaches now (never a search over the school), and
the parent-teacher conversation accepts exactly those pairs."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import MembershipStatus
from apps.communication.models import Conversation
from apps.gradebook import services as gb
from apps.people import services as people

from .communication_world import make_communication_world, verified_parent
from .conftest import DB
from .factories import SchoolClassFactory, SchoolFactory, StudentFactory

pytestmark = DB

URL = "/api/v1/teacher/contacts/"


@pytest.fixture
def w(school):
    w = make_communication_world(school)
    # Another class of the same school (4e C), taught in french by tf only.
    w.klass_c = SchoolClassFactory(school=school, name="4e C", academic_year=w.year, level=w.klass.level)
    w.pupil_b = StudentFactory(school=school, last_name="ÉlèveB")
    people.enroll_student(w.pupil_b, w.klass_c)
    w.parent_b = verified_parent(w, w.pupil_b)
    w.course_c_french = gb.create_course(w.klass_c, w.french, w.tf, actor=w.admin)
    return w


def as_(member):
    client = APIClient()
    client.force_authenticate(member.user)
    return client


def contacts(member, **params):
    response = as_(member).get(URL, params)
    assert response.status_code == 200, response.json()
    return {row["student"]: {p["member"] for p in row["parents"]} for row in response.json()["data"]}


def test_a_teacher_sees_the_verified_parents_of_the_pupils_taught_only(w):
    s0, s1 = (str(s.pk) for s in w.students[:2])
    found = contacts(w.tm_member)
    assert found[s0] == {str(w.parent.pk)}  # the declared (unverified) father is not offered
    assert found[s1] == {str(w.other_parent.pk)}
    assert str(w.pupil_b.pk) not in found  # 4e C: tm does not teach there
    assert str(w.parent_b.pk) not in {m for parents in found.values() for m in parents}
    row = as_(w.tm_member).get(URL).json()["data"][0]
    assert set(row) == {"student", "name", "parents"}
    assert set(row["parents"][0]) == {"member", "name", "relationship"}  # no e-mail, no phone


def test_the_scope_follows_the_courses_and_enrollments(w):
    assert str(w.pupil_b.pk) in contacts(w.tf_member)  # tf teaches both classes
    assert contacts(w.outsider_teacher) == {}  # no course: nobody
    w.course_maths.active = False
    w.course_maths.save(update_fields=["active"])
    assert contacts(w.tm_member) == {}  # course ended: the class is out of reach


def test_inactive_links_or_suspended_parents_are_not_offered(w):
    link = w.parent.parent_profile.children_links.get()
    link.active = False
    link.save(update_fields=["active"])
    w.other_parent.status = MembershipStatus.SUSPENDED
    w.other_parent.save(update_fields=["status"])
    found = contacts(w.tm_member)
    assert all(not parents for parents in found.values())


def test_filter_by_pupil_and_never_another_schools_pupil(w):
    other = make_communication_world(SchoolFactory())
    assert set(contacts(w.tm_member, student=w.students[1].pk)) == {str(w.students[1].pk)}
    assert contacts(w.tm_member, student=other.students[0].pk) == {}
    assert contacts(w.tm_member, student=w.pupil_b.pk) == {}
    assert as_(w.tm_member).get(URL, {"student": "nope"}).status_code == 400
    # The other school's teacher sees only its own parents.
    theirs = {m for parents in contacts(other.tm_member).values() for m in parents}
    assert theirs and str(w.parent.pk) not in theirs and str(other.parent.pk) in theirs


@pytest.mark.parametrize("who", ["parent", "staff_member", "guardian", "admin"])
def test_reserved_to_teachers(w, who):
    response = as_(getattr(w, who)).get(URL)
    assert response.status_code == 403


def test_anonymous_is_refused(w):
    assert APIClient().get(URL).status_code == 401


def test_a_teacher_can_write_to_a_listed_parent_only(w):
    client = as_(w.tm_member)
    ok = client.post(
        "/api/v1/conversations/",
        {
            "conversation_type": "PARENT_TEACHER",
            "participants": [str(w.parent.pk)],
            "student": str(w.students[0].pk),
            "body": "Bonjour, un point sur le dernier devoir.",
        },
        format="json",
    )
    assert ok.status_code == 201, ok.json()
    refused = [
        (w.parent_b, w.pupil_b),  # parent of a class tm does not teach (4e C)
        (w.other_parent, w.students[0]),  # parent of another pupil than the one named
        (w.unverified, w.students[0]),  # declared, not verified
    ]
    for parent, pupil in refused:
        response = client.post(
            "/api/v1/conversations/",
            {"conversation_type": "PARENT_TEACHER", "participants": [str(parent.pk)], "student": str(pupil.pk)},
            format="json",
        )
        assert response.status_code == 403, (parent, response.json())
    other = make_communication_world(SchoolFactory())
    response = client.post(
        "/api/v1/conversations/",
        {
            "conversation_type": "PARENT_TEACHER",
            "participants": [str(other.parent.pk)],
            "student": str(other.students[0].pk),
        },
        format="json",
    )
    assert response.status_code == 404  # another school: does not exist here
    assert Conversation.objects.filter(conversation_type="PARENT_TEACHER").count() == 1
