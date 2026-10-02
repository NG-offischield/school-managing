"""Principal teacher (history, one active) and the read-only class dashboard."""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from apps.gradebook import services as gb
from apps.gradebook.models import ClassPrincipalAssignment

from .conftest import DB
from .factories import SchoolFactory, make_teacher, member_with_role
from .gradebook_world import make_world

pytestmark = DB


@pytest.fixture
def w(school):
    return make_world(school)


def as_(membership):
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


def test_one_active_principal_with_history(w):
    first = gb.assign_class_principal(w.klass, w.tm, actor=w.admin, start_date=date(2025, 9, 1))
    second = gb.assign_class_principal(w.klass, w.tf, actor=w.admin, start_date=date(2026, 1, 5))
    first.refresh_from_db()
    assert (first.active, first.end_date) == (False, date(2026, 1, 5))
    assert gb.current_principal(w.klass) == second
    assert ClassPrincipalAssignment.objects.filter(school_class=w.klass).count() == 2


def test_principal_constraints_postgresql(w):
    pa = gb.assign_class_principal(w.klass, w.tm, actor=w.admin)
    with pytest.raises(IntegrityError), transaction.atomic():  # second active principal
        ClassPrincipalAssignment.objects.create(
            school=w.school, school_class=w.klass, teacher=w.tf, start_date=date(2025, 9, 1)
        )
    with pytest.raises(IntegrityError), transaction.atomic():  # inactive without end date
        ClassPrincipalAssignment.objects.filter(pk=pa.pk).update(active=False)
    with pytest.raises(IntegrityError), transaction.atomic():  # teacher of another school
        ClassPrincipalAssignment.objects.filter(pk=pa.pk).update(teacher=make_teacher(SchoolFactory()))


def test_only_admins_assign_principals(w):
    with pytest.raises(PermissionDenied):
        gb.assign_class_principal(w.klass, w.tm, actor=w.tm_member)


def fill(w):
    """s0: maths 16, french 10 -> (64+20)/6 = 14.00 ; s1: maths 6 -> 6.00 ; s2: nothing."""
    a, f = w.assess(), w.assess(course=w.course_french)
    w.grade(a, w.students[0], 16)
    w.grade(f, w.students[0], 10)
    w.grade(a, w.students[1], 6)


def test_dashboard_numbers(w):
    fill(w)
    gb.assign_class_principal(w.klass, w.tm, actor=w.admin)
    board = gb.class_dashboard(w.klass, w.s1, actor=w.tm_member)
    subjects = {s["subject"]: s for s in board["subjects"]}
    assert (subjects["MATH"]["class_average"], subjects["MATH"]["graded_students"]) == (Decimal("11.00"), 2)
    assert subjects["FR"]["class_average"] == Decimal("10.00")
    students = {s["id"]: s for s in board["students"]}
    s0, s1, s2 = (students[str(s.id)] for s in w.students)
    assert (s0["general_average"], s0["rank"], s0["below_threshold"]) == (Decimal("14.00"), 1, False)
    assert (s1["general_average"], s1["rank"], s1["below_threshold"]) == (Decimal("6.00"), 2, True)  # < 8.00
    assert (s2["general_average"], s2["rank"]) == (None, None)
    assert board["class_general_average"] == Decimal("10.00")
    assert board["student_count"] == 3 and board["principal"]


def test_dashboard_matches_report_cards(w):
    """One computation, two outputs: the numbers can never diverge."""
    fill(w)
    cards = {c.student_id: c for c in gb.generate_report_cards(w.klass, w.s1, actor=w.admin)}
    board = gb.class_dashboard(w.klass, w.s1, actor=w.admin)
    for row in board["students"]:
        card = next(c for pk, c in cards.items() if str(pk) == row["id"])
        assert (row["general_average"], row["rank"]) == (card.general_average, card.rank)


def test_dashboard_visibility(w):
    gb.assign_class_principal(w.klass, w.tm, actor=w.admin)
    url = f"/api/v1/classes/{w.klass.id}/dashboard/?academic_period={w.s1.id}"
    assert as_(w.tm_member).get(url).status_code == 200  # principal
    assert as_(w.admin).get(url).status_code == 200
    for outsider in (w.tf_member, member_with_role(w.school, "PARENT"), member_with_role(w.school, "STAFF")):
        response = as_(outsider).get(url)
        assert (response.status_code, response.json()["error"]["code"]) == (403, "PERMISSION_DENIED")


def test_dashboard_requires_period_and_is_school_scoped(w):
    client = as_(w.admin)
    response = client.get(f"/api/v1/classes/{w.klass.id}/dashboard/")
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    other = make_world(SchoolFactory())
    assert client.get(f"/api/v1/classes/{other.klass.id}/dashboard/?academic_period={w.s1.id}").status_code == 404
    assert client.get(f"/api/v1/classes/{w.klass.id}/dashboard/?academic_period={other.s1.id}").status_code == 404
