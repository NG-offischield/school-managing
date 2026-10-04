"""Planning: rooms, recurring slots, conflicts, sessions, substitutions,
swaps, availability, history (services + PostgreSQL). ADR 0012."""

from datetime import date, time, timedelta

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

from apps.academics.models import AcademicYear
from apps.attendance.models import GuardianScan, ScanResult
from apps.audit.models import AuditLog
from apps.communication.models import Notification
from apps.people import services as people
from apps.scheduling import services as planning
from apps.scheduling.models import (
    ChangeType,
    ExceptionStatus,
    NotificationStatus,
    ScheduleChange,
    ScheduleSlot,
    SessionStatus,
    SlotStatus,
    TeachingSession,
)

from .conftest import DB
from .factories import SchoolFactory, grant_role, make_teacher, member_with_role
from .planning_world import MONDAY, at, generate, make_planning_world, slot

pytestmark = DB


@pytest.fixture
def w(school):
    return make_planning_world(school)


def code_of(exc_info):
    return exc_info.value.code


# =============================================================================
# Rooms
# =============================================================================


def test_room_creation_and_rules(w):
    assert (w.r12.code, w.r12.capacity) == ("R12", 40)
    assert AuditLog.objects.filter(action="ROOM_CREATED", entity_id=w.r12.pk).exists()
    with pytest.raises(ValidationError) as exc:
        planning.create_room(w.school, actor=w.admin, code="r12", name="Doublon")
    assert code_of(exc) == "duplicate_code"
    with pytest.raises(PermissionDenied):
        planning.create_room(w.school, actor=w.tm_member, code="X", name="X")


def test_room_capacity_conflict(w):
    small = planning.create_room(w.school, actor=w.admin, code="BOX", name="Box", capacity=2)
    with pytest.raises(ValidationError) as exc:
        planning.set_class_main_room(w.klass, small, actor=w.admin)  # 3 students > 2 seats
    assert code_of(exc) == "room_capacity_exceeded"
    with pytest.raises(ValidationError) as exc:
        slot(w, room=small)
    assert code_of(exc) == "room_capacity_exceeded"


def test_room_in_use_cannot_be_deactivated_and_foreign_room_refused(w):
    slot(w)  # uses the class main room R12
    with pytest.raises(ValidationError) as exc:
        planning.set_room_active(w.r12, False, actor=w.admin)
    assert code_of(exc) == "room_in_use"
    planning.set_room_active(w.lab, False, actor=w.admin)
    with pytest.raises(ValidationError) as exc:
        slot(w, course=w.course_french, room=w.lab)
    assert code_of(exc) == "room_inactive"
    foreign = planning.create_room(other := SchoolFactory(), actor=member_with_role(other, "ADMIN"), code="X", name="X")
    with pytest.raises(PermissionDenied):
        slot(w, room=foreign)


# =============================================================================
# Recurring slots & conflicts
# =============================================================================


def test_create_slot_defaults_to_class_main_room_and_year(w):
    s = slot(w)
    assert (s.room, s.teacher, s.school_class, s.effective_from, s.effective_to) == (
        w.r12,
        w.tm,
        w.klass,
        w.year.start_date,
        w.year.end_date,
    )
    assert ScheduleChange.objects.filter(schedule_slot=s, change_type=ChangeType.SLOT_CREATED).exists()


def test_practical_subject_can_use_a_dedicated_room(w):
    s = slot(w, course=w.course_french, weekday=2, room=w.lab)
    assert s.room == w.lab


def test_class_conflict(w):
    slot(w)  # 3e A maths Mon 08-10
    with pytest.raises(ValidationError) as exc:
        slot(w, course=w.course_french, start=(9, 0), end=(11, 0), room=w.lab)
    assert code_of(exc) == "planning_conflict"
    assert exc.value.params["conflicts"][0]["kinds"] == ["CLASS"]


def test_teacher_conflict(w):
    slot(w)  # tm teaches 3e A Mon 08-10
    with pytest.raises(ValidationError) as exc:
        slot(w, course=w.course_b_maths, start=(9, 0), end=(11, 0), room=w.lab)
    assert "TEACHER" in exc.value.params["conflicts"][0]["kinds"]


def test_room_conflict(w):
    slot(w)  # R12 Mon 08-10
    other_teacher = make_teacher(w.school, category=w.french.category, primary_subject=w.french)
    from apps.gradebook import services as gb

    course = gb.create_course(w.klass_b, w.french, other_teacher, actor=w.admin)
    with pytest.raises(ValidationError) as exc:
        slot(w, course=course, room=w.r12)
    assert exc.value.params["conflicts"][0]["kinds"] == ["ROOM"]


def test_adjacent_slots_and_disjoint_date_ranges_do_not_conflict(w):
    slot(w)  # 08-10
    slot(w, course=w.course_french, start=(10, 0), end=(12, 0))  # half-open: no overlap
    slot(w, course=w.course_b_maths, weekday=3, effective_to=date(2025, 10, 31), room=w.lab)
    slot(w, course=w.course_b_maths, weekday=3, effective_from=date(2025, 11, 1), room=w.lab)


def test_postgresql_forbids_overlap_even_without_the_service(w):
    s = slot(w)
    with pytest.raises(IntegrityError), transaction.atomic():
        ScheduleSlot.objects.create(
            school=w.school,
            course=w.course_french,
            teacher=w.tf,
            school_class=w.klass,
            academic_year=w.year,
            weekday=1,
            start_time=time(9),
            end_time=time(11),
            effective_from=s.effective_from,
        )
        planning._check_now()


def test_slot_copies_must_match_the_course_postgresql(w):
    with pytest.raises(IntegrityError), transaction.atomic():  # teacher != course teacher
        ScheduleSlot.objects.create(
            school=w.school,
            course=w.course_maths,
            teacher=w.tf,
            school_class=w.klass,
            academic_year=w.year,
            weekday=5,
            start_time=time(8),
            end_time=time(9),
            effective_from=w.year.start_date,
        )


@pytest.mark.parametrize(
    "breakage,code",
    [
        ("course", "course_inactive"),
        ("subject", "subject_inactive"),
        ("year", "year_closed"),
    ],
)
def test_cannot_schedule_inactive_or_closed_elements(w, breakage, code):
    if breakage == "course":
        w.course_maths.active = False
        w.course_maths.save()
    elif breakage == "subject":
        type(w.maths).objects.filter(pk=w.maths.pk).update(active=False)
    else:
        AcademicYear.objects.filter(pk=w.year.pk).update(status="CLOSED", is_current=False)
    with pytest.raises(ValidationError) as exc:
        slot(w)
    assert code_of(exc) == code


def test_slot_outside_the_year_and_wrong_actor(w):
    with pytest.raises(ValidationError) as exc:
        slot(w, effective_from=date(2025, 8, 1))
    assert code_of(exc) == "outside_year"
    with pytest.raises(PermissionDenied):
        planning.create_slot(w.course_maths, actor=w.tm_member, weekday=1, start_time=time(8), end_time=time(9))
    with pytest.raises(PermissionDenied):
        planning.create_slot(
            w.course_maths,
            actor=member_with_role(SchoolFactory(), "ADMIN"),
            weekday=1,
            start_time=time(8),
            end_time=time(9),
        )


def test_declared_unavailability_blocks_unless_forced_with_reason(w):
    planning.declare_availability(
        w.tm,
        actor=w.tm_member,
        weekday=1,
        start_time=time(8),
        end_time=time(12),
        available=False,
        reason="Formation continue",
    )
    with pytest.raises(ValidationError) as exc:
        slot(w)
    assert code_of(exc) == "teacher_unavailable"
    with pytest.raises(ValidationError):
        slot(w, force_availability=True)  # reason missing
    slot(w, force_availability=True, reason="Aucun autre créneau possible")
    assert AuditLog.objects.filter(action="SLOT_FORCED_OVER_UNAVAILABILITY").exists()


def test_dry_run_check_reports_conflicts_without_writing(w):
    slot(w)
    result = planning.check_slot(w.course_french, weekday=1, start_time=time(9), end_time=time(10))
    assert result["conflicts"][0]["kinds"] == ["CLASS", "ROOM"]
    assert ScheduleSlot.objects.count() == 1


def test_reschedule_keeps_history_and_cancels_later_sessions(w):
    s = slot(w)
    generate(w, days=14)
    new = planning.reschedule_slot(
        s,
        actor=w.admin,
        from_date=MONDAY + timedelta(days=7),
        weekday=2,
        start_time=time(8),
        end_time=time(10),
        reason="Réorganisation",
    )
    s.refresh_from_db()
    assert s.effective_to == MONDAY + timedelta(days=6) and s.status == SlotStatus.PUBLISHED
    assert (new.weekday, new.effective_from) == (2, MONDAY + timedelta(days=7))
    statuses = dict(s.sessions.values_list("date", "status"))
    assert statuses[MONDAY] == SessionStatus.SCHEDULED
    assert statuses[MONDAY + timedelta(days=7)] == SessionStatus.CANCELLED
    assert ScheduleChange.objects.filter(schedule_slot=s, change_type=ChangeType.SLOT_ENDED).exists()


# =============================================================================
# Sessions
# =============================================================================


def test_generation_is_idempotent_assigns_period_and_skips_breaks(w):
    slot(w)
    summary = generate(w, days=13)  # two Mondays
    assert summary["created"] == 2
    session = TeachingSession.objects.get(date=MONDAY)
    assert (session.academic_period, session.planned_teacher, session.teacher, session.room) == (
        w.s1,
        w.tm,
        w.tm,
        w.r12,
    )
    assert generate(w, days=13)["existing"] == 2
    planning.create_school_break(
        w.year,
        actor=w.admin,
        name="Toussaint",
        start_datetime=at(0, day=MONDAY + timedelta(days=14)),
        end_datetime=at(23, day=MONDAY + timedelta(days=20)),
    )
    assert generate(w, days=20)["in_break"] == 1


def test_cancel_records_a_notifiable_change(w):
    slot(w)
    generate(w)
    session = TeachingSession.objects.get()
    planning.cancel_session(session, actor=w.admin, reason="Enseignant malade")
    change = ScheduleChange.objects.get(session=session, change_type=ChangeType.SESSION_CANCELLED)
    assert (change.school_class, change.reason) == (w.klass, "Enseignant malade")
    assert str(w.tm.pk) in change.teacher_ids
    # Notifiable change: queued PENDING by planning, then consumed after commit
    # by the communication dispatcher (ADR 0015), which marks it SENT and
    # notifies the teacher concerned.
    assert change.notification_status in (NotificationStatus.PENDING, NotificationStatus.SENT)
    if change.notification_status == NotificationStatus.SENT:
        assert change.notified_at is not None
        assert Notification.objects.filter(
            recipient=w.tm.employee.membership, event_key=f"schedule_change:{change.pk}"
        ).exists()
    with pytest.raises(ValidationError) as exc:
        planning.cancel_session(session, actor=w.admin, reason="x")
    assert code_of(exc) == "session_not_scheduled"


def test_move_keeps_original_times_and_detects_conflicts(w):
    slot(w)
    slot(w, course=w.course_french, start=(10, 0), end=(12, 0))
    generate(w)
    maths = TeachingSession.objects.get(course=w.course_maths)
    planning.move_session(maths, actor=w.admin, new_start=at(14), new_end=at(15, 30), reason="Sortie pédagogique")
    maths.refresh_from_db()
    assert (maths.original_start, maths.scheduled_start, maths.is_moved) == (at(8), at(14), True)
    with pytest.raises(ValidationError) as exc:  # onto french 10-12
        planning.move_session(maths, actor=w.admin, new_start=at(11), new_end=at(12), reason="x")
    assert code_of(exc) == "planning_conflict"
    planning.move_session(maths, actor=w.admin, new_start=at(14), new_end=at(15), reason="Fin exceptionnelle")
    maths.refresh_from_db()
    assert maths.original_start == at(8)  # the FIRST original time is kept
    assert ScheduleChange.objects.filter(session=maths, change_type=ChangeType.SESSION_MOVED).count() == 2


def test_compatible_substitution_keeps_the_planned_teacher(w):
    slot(w)
    generate(w)
    session = TeachingSession.objects.get()
    sub = make_teacher(w.school, category=w.maths.category, primary_subject=w.maths)
    planning.substitute_teacher(session, sub, actor=w.admin, reason="Congé maladie")
    session.refresh_from_db()
    assert (session.planned_teacher, session.teacher, session.is_substituted) == (w.tm, sub, True)
    change = ScheduleChange.objects.get(change_type=ChangeType.TEACHER_SUBSTITUTED)
    assert change.new_data["compatibility"] == "COMPATIBLE"
    assert set(change.teacher_ids) == {str(w.tm.pk), str(sub.pk)}
    planning.restore_teacher(session, actor=w.admin, reason="Retour")
    session.refresh_from_db()
    assert session.teacher == w.tm


def test_incompatible_substitute_refused_unless_override_exists(w):
    slot(w)
    generate(w)
    session = TeachingSession.objects.get()
    from apps.academics.models import SubjectCompatibilityRule

    SubjectCompatibilityRule.objects.create(
        school=w.school, pedagogical_category=w.tf.pedagogical_category, subject=w.maths, compatible=False
    )
    with pytest.raises(ValidationError) as exc:
        planning.substitute_teacher(session, w.tf, actor=w.admin, reason="x")
    assert (code_of(exc), exc.value.params["compatibility"]) == ("teacher_incompatible", "INCOMPATIBLE")
    people.grant_compatibility_override(w.tf, w.maths, actor=w.admin, reason="Pénurie temporaire")
    planning.substitute_teacher(session, w.tf, actor=w.admin, reason="Avec dérogation")
    session.refresh_from_db()
    assert session.teacher == w.tf


def test_busy_substitute_is_a_conflict(w):
    slot(w)
    sub = make_teacher(w.school, category=w.maths.category, primary_subject=w.maths)
    from apps.gradebook import services as gb

    slot(w, course=gb.create_course(w.klass_b, w.maths, sub, actor=w.admin), room=w.lab)  # sub busy Mon 08-10
    generate(w)
    session = TeachingSession.objects.get(course=w.course_maths)
    with pytest.raises(ValidationError) as exc:
        planning.substitute_teacher(session, sub, actor=w.admin, reason="x")
    assert code_of(exc) == "planning_conflict"


def test_swap_two_sessions(w):
    slot(w)  # maths 08-10
    slot(w, course=w.course_french, start=(10, 0), end=(12, 0))  # french 10-12
    generate(w)
    maths = TeachingSession.objects.get(course=w.course_maths)
    french = TeachingSession.objects.get(course=w.course_french)
    planning.swap_sessions(maths, french, actor=w.admin, reason="Permutation demandée")
    maths.refresh_from_db()
    french.refresh_from_db()
    assert (maths.scheduled_start, french.scheduled_start) == (at(10), at(8))
    assert (maths.original_start, french.original_start) == (at(8), at(10))
    assert ScheduleChange.objects.filter(change_type=ChangeType.SESSIONS_SWAPPED).count() == 2


def test_swap_refused_when_a_teacher_is_busy_at_the_new_time(w):
    slot(w)  # tm 3e A 08-10
    slot(w, course=w.course_french, start=(10, 0), end=(12, 0))  # tf 3e A 10-12
    slot(w, course=w.course_b_maths, start=(10, 0), end=(12, 0), room=w.lab)  # tm 3e B 10-12
    generate(w)
    maths = TeachingSession.objects.get(course=w.course_maths)
    french = TeachingSession.objects.get(course=w.course_french)
    with pytest.raises(ValidationError) as exc:  # tm would teach 3e A and 3e B at 10-12
        planning.swap_sessions(maths, french, actor=w.admin, reason="x")
    assert code_of(exc) == "planning_conflict"
    maths.refresh_from_db()
    assert maths.scheduled_start == at(8)


def test_exceptional_session(w):
    session = planning.create_exceptional_session(
        w.course_maths, actor=w.admin, start=at(16), end=at(17), reason="Rattrapage"
    )
    assert session.schedule_slot is None and session.room == w.r12
    assert ScheduleChange.objects.get(session=session).change_type == ChangeType.SESSION_CREATED


# =============================================================================
# History, isolation
# =============================================================================


def test_history_is_immutable_except_notification_fields(w):
    s = slot(w)
    change = ScheduleChange.objects.get(schedule_slot=s)
    with pytest.raises(IntegrityError), transaction.atomic():
        ScheduleChange.objects.filter(pk=change.pk).update(reason="réécrit")
    with pytest.raises(IntegrityError), transaction.atomic():
        ScheduleChange.objects.filter(pk=change.pk).delete()
    from django.utils import timezone

    ScheduleChange.objects.filter(pk=change.pk).update(notification_status="SENT", notified_at=timezone.now())


def test_session_must_stay_consistent_with_its_course_and_year_postgresql(w):
    s = slot(w)
    generate(w)
    session = TeachingSession.objects.get()
    other_year = AcademicYear.objects.create(
        school=w.school, name="2027-2028", start_date=date(2027, 9, 1), end_date=date(2028, 7, 1)
    )
    for field, value in (
        ("academic_year", other_year),
        ("planned_teacher", w.tf),
        ("school_class", w.klass_b),
        ("subject", w.french),
    ):
        with pytest.raises(IntegrityError), transaction.atomic():
            TeachingSession.objects.filter(pk=session.pk).update(**{field: value})
    assert s.sessions.count() == 1


def test_cross_school_session_reference_refused_postgresql(w):
    other = make_planning_world(SchoolFactory())
    slot(w)
    generate(w)
    with pytest.raises(IntegrityError), transaction.atomic():
        TeachingSession.objects.filter(school=w.school).update(room=other.r12)


def test_attendance_integration_point(w):
    """A scan may reference a session of its OWN school only; daily gate scans
    (teaching_session NULL) keep working unchanged."""
    slot(w)
    generate(w)
    session = TeachingSession.objects.get()
    other = make_planning_world(SchoolFactory())
    slot(other)
    generate(other)
    foreign = TeachingSession.objects.get(school=other.school)
    admin = w.admin
    GuardianScan.objects.create(
        school=w.school, scanned_by=admin, result=ScanResult.UNKNOWN_TOKEN, teaching_session=session
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        GuardianScan.objects.create(
            school=w.school, scanned_by=admin, result=ScanResult.UNKNOWN_TOKEN, teaching_session=foreign
        )


# =============================================================================
# Teacher availability
# =============================================================================


def test_unavailability_workflow(w):
    request = planning.request_unavailability(
        w.tm, actor=w.tm_member, date=MONDAY, start_time=time(7), end_time=time(12), reason="Rendez-vous médical"
    )
    assert request.status == ExceptionStatus.PENDING and request.requested_by == w.tm_member
    with pytest.raises(PermissionDenied):  # a teacher cannot decide
        planning.decide_unavailability(request, actor=w.tm_member, decision="APPROVED")
    with pytest.raises(ValidationError):  # rejection needs a justification
        planning.decide_unavailability(request, actor=w.admin, decision="REJECTED")
    slot(w)
    generate(w)
    decided, impacted = planning.decide_unavailability(request, actor=w.admin, decision="APPROVED")
    assert decided.decided_by == w.admin and decided.decided_at is not None
    assert [s.course for s in impacted] == [w.course_maths]  # nothing cancelled silently
    assert TeachingSession.objects.get().status == SessionStatus.SCHEDULED
    with pytest.raises(ValidationError) as exc:
        planning.decide_unavailability(request, actor=w.admin, decision="REJECTED", comment="x")
    assert code_of(exc) == "already_decided"
    assert AuditLog.objects.filter(action="UNAVAILABILITY_DECIDED").exists()


def test_no_self_approval_even_for_an_admin_teacher(w):
    grant_role(w.tm_member, "ADMIN")
    request = planning.request_unavailability(
        w.tm, actor=w.tm_member, date=MONDAY, start_time=time(7), end_time=time(9), reason="x"
    )
    with pytest.raises(PermissionDenied):
        planning.decide_unavailability(request, actor=w.tm_member, decision="APPROVED")


def test_only_the_teacher_or_an_admin_declares(w):
    for actor in (w.tf_member, member_with_role(w.school, "PARENT")):
        with pytest.raises(PermissionDenied):
            planning.request_unavailability(
                w.tm, actor=actor, date=MONDAY, start_time=time(7), end_time=time(9), reason="x"
            )
    planning.request_unavailability(
        w.tm, actor=w.admin, date=MONDAY, start_time=time(7), end_time=time(9), reason="Saisi par l'administration"
    )


def test_approved_unavailability_blocks_substitution_and_move(w):
    slot(w)
    generate(w)
    session = TeachingSession.objects.get()
    sub = make_teacher(w.school, category=w.maths.category, primary_subject=w.maths)
    req = planning.request_unavailability(
        sub, actor=sub.employee.membership, date=MONDAY, start_time=time(7), end_time=time(12), reason="Absent"
    )
    planning.decide_unavailability(req, actor=w.admin, decision="APPROVED")
    with pytest.raises(ValidationError) as exc:
        planning.substitute_teacher(session, sub, actor=w.admin, reason="x")
    assert code_of(exc) == "teacher_unavailable"


def test_teacher_withdraws_pending_request(w):
    request = planning.request_unavailability(
        w.tm, actor=w.tm_member, date=MONDAY, start_time=time(7), end_time=time(9), reason="x"
    )
    with pytest.raises(PermissionDenied):
        planning.cancel_unavailability(request, actor=w.admin)
    assert planning.cancel_unavailability(request, actor=w.tm_member).status == ExceptionStatus.CANCELLED


def test_course_scheduled_cannot_be_deactivated(w):
    from unittest import mock

    from apps.gradebook import services as gb

    slot(w)
    # During the school year (the world's year is 2025-2026): the slot is not over.
    with mock.patch("django.utils.timezone.localdate", return_value=MONDAY):
        with pytest.raises(ValidationError) as exc:
            gb.set_course_active(w.course_maths, False, actor=w.admin)
        assert code_of(exc) == "course_scheduled"
        gb.set_course_active(w.course_french, False, actor=w.admin)


def test_postgresql_forbids_a_teacher_in_two_sessions_at_once(w):
    """Safety net below the services: same teacher, two classes, same time."""
    common = dict(
        school=w.school,
        academic_year=w.year,
        subject=w.maths,
        planned_teacher=w.tm,
        teacher=w.tm,
        date=MONDAY,
        scheduled_start=at(8),
        scheduled_end=at(10),
    )
    TeachingSession.objects.create(course=w.course_maths, school_class=w.klass, **common)
    with pytest.raises(IntegrityError), transaction.atomic():
        TeachingSession.objects.create(course=w.course_b_maths, school_class=w.klass_b, **common)
        planning._check_now()
