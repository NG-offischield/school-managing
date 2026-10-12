"""Default rooms (SchoolClass.main_room) and explicit timetable regimes.

A default room is optional. It is held by ONE class per school year — unless
the classes sharing it each follow an explicit regime and the regimes do not
overlap (a day class and an evening class). Their slots and sessions then
stay inside the regime. Changing a default room never moves what is already
planned. Guaranteed by the service under the room's row lock, and by
PostgreSQL (unique per year / room / regime, regime of the same school and
year, ordered hours) — checked here on the real database."""

import importlib
import threading
from datetime import date, time

import pytest
from django.apps import apps as django_apps
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, transaction
from rest_framework.test import APIClient

from apps.academics import services as academics
from apps.academics.models import SchoolClass, TimetableRegime
from apps.scheduling import services as planning
from apps.scheduling.models import ScheduleSlot

from .conftest import DB
from .factories import SchoolClassFactory, SchoolFactory, admin_of
from .planning_world import MONDAY, at, generate, make_planning_world, slot

pytestmark = DB


@pytest.fixture
def w(school):
    w = make_planning_world(school)
    w.day = academics.create_regime(
        school, actor=w.admin, academic_year=w.year, name="Cours du jour", start_time=time(7), end_time=time(14)
    )
    w.evening = academics.create_regime(
        school, actor=w.admin, academic_year=w.year, name="Cours du soir", start_time=time(17), end_time=time(21)
    )
    return w


def rule(excinfo):
    return excinfo.value.code


def place(w, school_class, **values):
    return planning.set_class_room_and_regime(school_class, actor=w.admin, **values)


# --- optional default room ---------------------------------------------------------------


def test_a_class_needs_no_default_room(w):
    created = academics.create_class(w.school, actor=w.admin, name="CM1", level=w.klass.level, academic_year=w.year)
    assert created.main_room is None and created.regime is None


def test_set_change_and_clear_the_default_room(w):
    room = planning.create_room(w.school, actor=w.admin, code="R20", name="Salle 20", capacity=40)
    place(w, w.klass_b, room=room)
    assert SchoolClass.objects.get(pk=w.klass_b.pk).main_room == room
    other = planning.create_room(w.school, actor=w.admin, code="R21", name="Salle 21", capacity=40)
    place(w, w.klass_b, room=other)
    place(w, w.klass_b, room=None)
    assert SchoolClass.objects.get(pk=w.klass_b.pk).main_room is None


def test_room_rules_still_apply(w):
    other_school = SchoolFactory()
    foreign = planning.create_room(other_school, actor=admin_of(other_school), code="X1", name="X", capacity=40)
    with pytest.raises(PermissionDenied):
        place(w, w.klass_b, room=foreign)
    inactive = planning.create_room(w.school, actor=w.admin, code="R30", name="Salle 30", capacity=40)
    planning.set_room_active(inactive, False, actor=w.admin)
    with pytest.raises(ValidationError) as off:
        place(w, w.klass_b, room=inactive)
    assert rule(off) == "room_inactive"
    small = planning.create_room(w.school, actor=w.admin, code="R31", name="Cagibi", capacity=2)
    with pytest.raises(ValidationError) as cramped:
        place(w, w.klass, room=small)  # 3 pupils > 2 seats
    assert rule(cramped) == "room_capacity_exceeded"


# --- exclusivity and the day / evening exception ------------------------------------------------


def test_two_ordinary_classes_cannot_share_a_default_room(w):
    with pytest.raises(ValidationError) as taken:
        place(w, w.klass_b, room=w.r12)  # R12 is 3e A's
    assert rule(taken) == "room_default_taken" and taken.value.params["class"] == "3e A"


def test_same_regime_cannot_share(w):
    place(w, w.klass, regime=w.day)
    with pytest.raises(ValidationError) as same:
        place(w, w.klass_b, room=w.r12, regime=w.day)
    assert rule(same) == "room_default_regimes_overlap"


def test_day_and_evening_classes_share_a_room(w):
    place(w, w.klass, regime=w.day)
    shared = place(w, w.klass_b, room=w.r12, regime=w.evening)
    assert (shared.main_room, shared.regime) == (w.r12, w.evening)
    assert SchoolClass.objects.filter(main_room=w.r12).count() == 2


def test_overlapping_regimes_cannot_share(w):
    late_day = academics.create_regime(
        w.school, actor=w.admin, academic_year=w.year, name="Après-midi", start_time=time(13), end_time=time(18)
    )
    place(w, w.klass, regime=w.day)
    with pytest.raises(ValidationError) as overlap:
        place(w, w.klass_b, room=w.r12, regime=late_day)  # 13:00-14:00 in common
    assert rule(overlap) == "room_default_regimes_overlap"


def test_sharing_needs_a_regime_on_both_sides(w):
    with pytest.raises(ValidationError) as one_side:
        place(w, w.klass_b, room=w.r12, regime=w.evening)  # 3e A has no regime
    assert rule(one_side) == "room_default_taken"
    place(w, w.klass, regime=w.day)
    with pytest.raises(ValidationError) as other_side:
        place(w, w.klass_b, room=w.r12)  # 3e B has no regime
    assert rule(other_side) == "room_default_taken"


def test_names_mean_nothing_only_regimes_count(w):
    jour = SchoolClassFactory(school=w.school, name="6e Jour", academic_year=w.year, level=w.klass.level)
    soir = SchoolClassFactory(school=w.school, name="6e Soir", academic_year=w.year, level=w.klass.level)
    room = planning.create_room(w.school, actor=w.admin, code="R40", name="Salle 40", capacity=40)
    place(w, jour, room=room)
    with pytest.raises(ValidationError):
        place(w, soir, room=room)


# --- slots and sessions stay inside the regime ---------------------------------------------------


def test_slots_outside_the_regime_are_refused(w):
    place(w, w.klass_b, regime=w.evening)
    with pytest.raises(ValidationError) as early:
        slot(w, w.course_b_maths, start=(8, 0), end=(10, 0))
    assert rule(early) == "outside_regime"
    inside = slot(w, w.course_b_maths, start=(17, 0), end=(19, 0))
    assert inside.school_class == w.klass_b
    with pytest.raises(ValidationError) as check:
        planning.check_slot(w.course_b_maths, weekday=2, start_time=time(20), end_time=time(22))
    assert rule(check) == "outside_regime"


def test_a_class_cannot_join_a_regime_its_slots_do_not_fit(w):
    slot(w, start=(8, 0), end=(10, 0))  # 3e A, morning
    with pytest.raises(ValidationError) as misfit:
        place(w, w.klass, regime=w.evening)
    assert rule(misfit) == "slots_outside_regime"
    assert place(w, w.klass, regime=w.day).regime == w.day


def test_sessions_cannot_leave_the_regime(w):
    place(w, w.klass, regime=w.day)
    slot(w, start=(8, 0), end=(10, 0))
    generate(w, days=0, school_class=w.klass)
    session = w.klass.sessions.order_by("scheduled_start").first()
    assert session is not None
    with pytest.raises(ValidationError) as moved:
        planning.move_session(session, actor=w.admin, new_start=at(18), new_end=at(19), reason="Test")
    assert rule(moved) == "outside_regime"
    with pytest.raises(ValidationError) as extra:
        planning.create_exceptional_session(
            w.course_maths, actor=w.admin, start=at(15, day=MONDAY), end=at(16, day=MONDAY), reason="Rattrapage"
        )
    assert rule(extra) == "outside_regime"


def test_changing_the_default_room_moves_nothing(w):
    planned = slot(w, start=(8, 0), end=(10, 0))
    generate(w, days=0, school_class=w.klass)
    session_rooms = set(w.klass.sessions.values_list("room_id", flat=True))
    assert planned.room == w.r12 and session_rooms == {w.r12.pk}
    new_room = planning.create_room(w.school, actor=w.admin, code="R50", name="Salle 50", capacity=40)
    place(w, w.klass, room=new_room)
    assert ScheduleSlot.objects.get(pk=planned.pk).room == w.r12
    assert set(w.klass.sessions.values_list("room_id", flat=True)) == {w.r12.pk}
    assert slot(w, weekday=3, start=(8, 0), end=(10, 0)).room == new_room  # only NEW slots get it


# --- regimes themselves -----------------------------------------------------------------------


def test_regime_hours_are_validated_and_rechecked(w):
    with pytest.raises(ValidationError) as midnight:
        academics.create_regime(
            w.school, actor=w.admin, academic_year=w.year, name="Nuit", start_time=time(22), end_time=time(2)
        )
    assert rule(midnight) == "invalid_times"  # first version: no window across midnight
    place(w, w.klass, regime=w.day)
    place(w, w.klass_b, room=w.r12, regime=w.evening)
    with pytest.raises(ValidationError) as overlap:
        academics.update_regime(w.evening, actor=w.admin, start_time=time(12))  # would overlap the day
    assert rule(overlap) == "room_default_regimes_overlap"
    with pytest.raises(ValidationError) as in_use:
        academics.update_regime(w.day, actor=w.admin, active=False)
    assert rule(in_use) == "regime_in_use"


# --- PostgreSQL guarantees (bypassing the service on purpose) ---------------------------------------


def test_database_refuses_two_regime_less_classes_on_one_room(w):
    with pytest.raises(IntegrityError), transaction.atomic():
        SchoolClass.objects.filter(pk=w.klass_b.pk).update(main_room=w.r12)
    with pytest.raises(IntegrityError), transaction.atomic():
        SchoolClass.objects.filter(pk=w.klass.pk).update(regime=w.day)
        SchoolClass.objects.filter(pk=w.klass_b.pk).update(main_room=w.r12, regime=w.day)


def test_database_keeps_the_regime_in_the_class_school_and_year(w):
    next_year = academics.create_academic_year(
        w.school, name="2099-2100", start_date=date(2099, 9, 1), end_date=date(2100, 7, 31)
    )
    elsewhere = TimetableRegime.objects.create(
        school=w.school, academic_year=next_year, name="Jour 26", start_time=time(7), end_time=time(12)
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        SchoolClass.objects.filter(pk=w.klass.pk).update(regime=elsewhere)
    with pytest.raises(IntegrityError), transaction.atomic():
        TimetableRegime.objects.create(
            school=w.school, academic_year=w.year, name="Inversé", start_time=time(12), end_time=time(8)
        )


# --- API, school isolation ---------------------------------------------------------------------------


def test_api_regimes_and_class_regime(w):
    admin = APIClient()
    admin.force_authenticate(w.admin.user)
    listed = admin.get("/api/v1/timetable-regimes/", {"academic_year": str(w.year.pk)}).json()["data"]
    assert {r["name"] for r in listed} == {"Cours du jour", "Cours du soir"}
    patched = admin.patch(f"/api/v1/classes/{w.klass.pk}/", {"regime": str(w.day.pk)}, format="json")
    assert patched.status_code == 200 and patched.json()["data"]["regime_name"].startswith("Cours du jour")
    refused = admin.patch(f"/api/v1/classes/{w.klass_b.pk}/", {"main_room": str(w.r12.pk)}, format="json")
    assert refused.status_code == 409 and refused.json()["error"]["details"]["rule"] == "room_default_taken"
    created = admin.post(
        "/api/v1/timetable-regimes/",
        {"academic_year": str(w.year.pk), "name": "Samedi", "start_time": "08:00", "end_time": "12:00"},
        format="json",
    )
    assert created.status_code == 201
    teacher = APIClient()
    teacher.force_authenticate(w.tm.employee.membership.user)
    assert (
        teacher.post(
            "/api/v1/timetable-regimes/",
            {"academic_year": str(w.year.pk), "name": "X", "start_time": "08:00", "end_time": "09:00"},
            format="json",
        ).status_code
        == 403
    )


def test_another_schools_regime_is_out_of_reach(w):
    other = SchoolFactory()
    other_admin = admin_of(other)
    client = APIClient()
    client.force_authenticate(other_admin.user)
    assert client.get(f"/api/v1/timetable-regimes/{w.day.pk}/").status_code == 404
    assert client.get("/api/v1/timetable-regimes/").json()["data"] == []


# --- concurrency ------------------------------------------------------------------------------------


def test_concurrent_assignments_of_one_room_are_serialised(w):
    """3e A (day) holds R12. Two evening-ish classes try to take it AT THE SAME
    TIME with regimes that overlap EACH OTHER (but not the day): without the
    room lock both would pass; with it, exactly one wins."""
    place(w, w.klass, regime=w.day)
    late = academics.create_regime(
        w.school, actor=w.admin, academic_year=w.year, name="Soir tardif", start_time=time(18), end_time=time(22)
    )
    other = SchoolClassFactory(school=w.school, name="3e C", academic_year=w.year, level=w.klass.level)
    barrier, outcomes = threading.Barrier(2), []

    def assign(school_class, regime):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            planning.set_class_room_and_regime(
                SchoolClass.objects.get(pk=school_class.pk), actor=w.admin, room=w.r12, regime=regime
            )
            outcomes.append("ok")
        except (ValidationError, IntegrityError) as error:
            outcomes.append(getattr(error, "code", "integrity"))
        finally:
            close_old_connections()

    threads = [
        threading.Thread(target=assign, args=(w.klass_b, w.evening)),
        threading.Thread(target=assign, args=(other, late)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert sorted(outcomes) == ["ok", "room_default_regimes_overlap"]
    assert SchoolClass.objects.filter(main_room=w.r12).count() == 2  # 3e A + the winner


# --- migration pre-check ------------------------------------------------------------------------------


def test_migration_refuses_to_pick_a_winner_among_shared_rooms(w):
    migration = importlib.import_module("apps.academics.migrations.0008_timetable_regimes")
    place(w, w.klass, regime=w.day)
    place(w, w.klass_b, room=w.r12, regime=w.evening)  # a legitimate share TODAY...
    with pytest.raises(RuntimeError) as listed:
        migration.refuse_shared_default_rooms(django_apps, None)  # ...is what the pre-check reports
    assert "3e A" in str(listed.value) and "3e B" in str(listed.value)
    assert SchoolClass.objects.filter(main_room=w.r12).count() == 2  # nothing reassigned
