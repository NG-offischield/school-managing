"""Planning services (ADR 0012).

Every write:
- is done by an ADMIN / SUPER_ADMIN of the school of the data (teachers only
  declare their own availability / unavailability requests);
- checks school, year and "active" consistency of everything it touches;
- detects conflicts (class / teacher / room overlap) and answers 409
  `planning_conflict` with the conflicting rows in `details.context`;
- leaves a trace: ScheduleChange (planning history + notification outbox)
  and, for administrative decisions, an AuditLog row.

PostgreSQL is the safety net: exclusion constraints forbid overlaps even if a
code path forgets a check. They are DEFERRABLE (a swap needs a transient
overlap); `_check_now()` forces them before a service returns, so a
violation surfaces inside the service, never at the final commit.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import Q
from django.utils import timezone

from apps.academics.models import AcademicPeriod, AcademicYearStatus, Room, RoomType, SchoolClass, TimetableRegime
from apps.audit.models import AuditLayer
from apps.audit.services import record_audit, snapshot
from apps.people.compatibility import evaluate
from apps.people.models import (
    CompatibilityResult,
    EmploymentStatus,
    EnrollmentStatus,
    ProfessionalStatus,
    StudentEnrollment,
)
from common.permissions import ADMIN_ROLES, require_role

from .models import (
    CONFLICT_CONSTRAINTS,
    BreakType,
    ChangeType,
    ExceptionStatus,
    NotificationStatus,
    ScheduleChange,
    ScheduleSlot,
    SchoolBreak,
    SessionStatus,
    SlotStatus,
    TeacherAvailability,
    TeacherAvailabilityException,
    TeachingSession,
)

MAX_GENERATION_DAYS = 120

# =============================================================================
# Helpers
# =============================================================================


def _tz(school):
    return ZoneInfo(school.timezone)


def _at(school, day, clock):
    return datetime.combine(day, clock, tzinfo=_tz(school))


def _local_date(school, moment):
    return moment.astimezone(_tz(school)).date()


def _check_now():
    """Force the deferrable exclusion constraints now (inside the service)."""
    with connection.cursor() as cursor:
        cursor.execute(f"SET CONSTRAINTS {', '.join(CONFLICT_CONSTRAINTS)} IMMEDIATE")


def _defer():
    with connection.cursor() as cursor:
        cursor.execute(f"SET CONSTRAINTS {', '.join(CONFLICT_CONSTRAINTS)} DEFERRED")


def _jsonable(data):
    out = {}
    for key, value in data.items():
        if isinstance(value, (datetime, date, time)):
            value = value.isoformat()
        elif isinstance(value, (UUID, Decimal)):
            value = str(value)
        out[key] = value
    return out


def _session_view(session):
    return _jsonable(
        {
            "date": session.date,
            "scheduled_start": session.scheduled_start,
            "scheduled_end": session.scheduled_end,
            "teacher": session.teacher_id,
            "room": session.room_id,
            "status": session.status,
        }
    )


def _slot_view(slot):
    return _jsonable(
        {
            "weekday": slot.weekday,
            "start_time": slot.start_time,
            "end_time": slot.end_time,
            "room": slot.room_id,
            "effective_from": slot.effective_from,
            "effective_to": slot.effective_to,
            "status": slot.status,
        }
    )


def record_change(
    change_type, *, actor, school, slot=None, session=None, old=None, new=None, reason=None, notify=False
):
    """History row + notification outbox entry (PENDING when `notify`)."""
    school_class = (session or slot).school_class if (session or slot) else None
    teachers = set()
    if session is not None:
        teachers |= {str(session.teacher_id), str(session.planned_teacher_id)}
    if slot is not None:
        teachers.add(str(slot.teacher_id))
    for data in (old or {}, new or {}):
        if data.get("teacher"):
            teachers.add(str(data["teacher"]))
    return ScheduleChange.objects.create(
        school=school,
        change_type=change_type,
        schedule_slot=slot,
        session=session,
        school_class=school_class,
        teacher_ids=sorted(teachers),
        old_data=old or {},
        new_data=new or {},
        reason=reason,
        changed_by=actor,
        notification_status=NotificationStatus.PENDING if notify else NotificationStatus.NOT_REQUIRED,
    )


def _require_reason(reason):
    if not reason or not str(reason).strip():
        raise ValidationError("A reason is required.", code="reason_required")
    return str(reason).strip()


def _conflict(conflicts):
    raise ValidationError(
        "This planning conflicts with existing slots or sessions.",
        code="planning_conflict",
        params={"conflicts": conflicts},
    )


# =============================================================================
# Rooms
# =============================================================================

ROOM_FIELDS = ["code", "name", "room_type", "capacity", "bench_count", "active"]


def _enrolled_count(school_class):
    return (
        StudentEnrollment.objects.filter(school_class=school_class).exclude(status=EnrollmentStatus.WITHDRAWN).count()
    )


def _check_room(room, school, school_class=None):
    if room is None:
        return
    # Re-read: the caller's instance may be stale (deactivated meanwhile).
    room = Room.objects.get(pk=room.pk)
    if room.school_id != school.pk:
        raise PermissionDenied("This room belongs to another school.")
    if not room.active:
        raise ValidationError("This room is inactive.", code="room_inactive")
    if school_class is not None and room.capacity:
        enrolled = _enrolled_count(school_class)
        if enrolled > room.capacity:
            raise ValidationError(
                f"Room capacity {room.capacity} is below the {enrolled} students of the class.",
                code="room_capacity_exceeded",
                params={"room": str(room.pk), "capacity": room.capacity, "students": enrolled},
            )


@transaction.atomic
def create_room(school, *, actor, code, name, room_type=RoomType.CLASSROOM, capacity=None, bench_count=None):
    require_role(actor, ADMIN_ROLES, school=school)
    code = (code or "").strip().upper()
    if not code:
        raise ValidationError("A code is required.", code="code_required")
    if Room.objects.filter(school=school, code=code).exists():
        raise ValidationError(f"A room with code {code} already exists.", code="duplicate_code")
    room = Room.objects.create(
        school=school, code=code, name=name.strip(), room_type=room_type, capacity=capacity, bench_count=bench_count
    )
    record_audit(
        "ROOM_CREATED", actor=actor, entity=room, new=snapshot(room, ROOM_FIELDS), layer=AuditLayer.ADMINISTRATIVE
    )
    return room


@transaction.atomic
def update_room(room, *, actor, **changes):
    """Editable: name, room_type, capacity, bench_count (code is immutable)."""
    require_role(actor, ADMIN_ROLES, school=room.school)
    room = Room.objects.select_for_update().get(pk=room.pk)
    if "code" in changes and changes["code"].strip().upper() != room.code:
        raise ValidationError("The code of a room cannot be changed.", code="code_immutable")
    old = snapshot(room, ROOM_FIELDS)
    for field in ("name", "room_type", "capacity", "bench_count"):
        if field in changes:
            setattr(room, field, changes[field])
    room.save()
    record_audit(
        "ROOM_UPDATED",
        actor=actor,
        entity=room,
        old=old,
        new=snapshot(room, ROOM_FIELDS),
        layer=AuditLayer.ADMINISTRATIVE,
    )
    return room


OPEN_YEARS = [AcademicYearStatus.PLANNED, AcademicYearStatus.ACTIVE]


def _room_in_future_use(room):
    """Used by the published timetable or the scheduled sessions of a year
    that is still planned / active (decided by the year's status, never by
    the wall clock)."""
    return (
        room.schedule_slots.filter(status=SlotStatus.PUBLISHED, academic_year__status__in=OPEN_YEARS).exists()
        or room.sessions.filter(status=SessionStatus.SCHEDULED, academic_year__status__in=OPEN_YEARS).exists()
    )


@transaction.atomic
def set_room_active(room, active, *, actor):
    require_role(actor, ADMIN_ROLES, school=room.school)
    room = Room.objects.select_for_update().get(pk=room.pk)
    if not active and _room_in_future_use(room):
        raise ValidationError("This room is still used by the timetable.", code="room_in_use")
    if room.active != active:
        old = snapshot(room, ROOM_FIELDS)
        room.active = active
        room.save(update_fields=["active", "updated_at"])
        record_audit(
            "ROOM_ACTIVATED" if active else "ROOM_DEACTIVATED",
            actor=actor,
            entity=room,
            old=old,
            new=snapshot(room, ROOM_FIELDS),
            layer=AuditLayer.ADMINISTRATIVE,
        )
    return room


@transaction.atomic
def set_class_main_room(school_class, room, *, actor):
    """The default room of the class's theoretical courses (None to clear)."""
    return set_class_room_and_regime(school_class, actor=actor, room=room)


_UNSET = object()


def _check_regime(regime, school_class):
    if regime is None:
        return None
    regime = TimetableRegime.objects.get(pk=regime.pk)  # fresh: hours / status may have changed
    if regime.school_id != school_class.school_id or regime.academic_year_id != school_class.academic_year_id:
        raise ValidationError("The regime belongs to another school year.", code="regime_other_year")
    if not regime.active:
        raise ValidationError("This timetable regime is inactive.", code="regime_inactive")
    return regime


def _check_default_room_sharing(school_class, room, regime):
    """A default room belongs to ONE class per year — unless every class sharing
    it has an explicit regime and the windows do not overlap. The caller holds
    the room's row lock: two concurrent assignments of the same room are
    serialised and the second one sees the first."""
    if room is None:
        return
    others = (
        SchoolClass.objects.filter(academic_year_id=school_class.academic_year_id, main_room=room)
        .exclude(pk=school_class.pk)
        .select_related("regime")
    )
    for other in others:
        params = {"room": str(room.pk), "class": other.name}
        if regime is None or other.regime is None:
            raise ValidationError(
                f"This room is already the default room of {other.name}.", code="room_default_taken", params=params
            )
        if other.regime_id == regime.pk or regime.overlaps(other.regime):
            raise ValidationError(
                f"{other.name} uses this room in an overlapping timetable regime ({other.regime}).",
                code="room_default_regimes_overlap",
                params={**params, "regime": other.regime.name},
            )


def _check_slots_in_regime(school_class, regime):
    """A class put in a regime must already plan its published slots inside it."""
    if regime is None:
        return
    outside = [
        slot
        for slot in ScheduleSlot.objects.filter(school_class=school_class, status=SlotStatus.PUBLISHED)
        if not regime.contains(slot.start_time, slot.end_time)
    ]
    if outside:
        raise ValidationError(
            f"{len(outside)} published slot(s) of the class lie outside {regime}.",
            code="slots_outside_regime",
            params={"slots": [str(s.pk) for s in outside]},
        )


@transaction.atomic
def set_class_room_and_regime(school_class, *, actor, room=_UNSET, regime=_UNSET):
    """Default room and/or timetable regime of a class, checked TOGETHER.

    The default room only pre-fills NEW slots: existing slots and sessions keep
    the room they were planned with (changing them is an explicit planning
    operation: reschedule a slot, change a session's room)."""
    require_role(actor, ADMIN_ROLES, school=school_class.school)
    school_class = SchoolClass.objects.select_for_update().get(pk=school_class.pk)
    new_room = school_class.main_room if room is _UNSET else room
    new_regime = school_class.regime if regime is _UNSET else regime
    if new_room is not None:
        Room.objects.select_for_update().get(pk=new_room.pk)  # serialise the room's assignments
    _check_room(new_room, school_class.school, school_class)
    new_regime = _check_regime(new_regime, school_class)
    if regime is not _UNSET:
        _check_slots_in_regime(school_class, new_regime)
    _check_default_room_sharing(school_class, new_room, new_regime)
    old = {
        "main_room": str(school_class.main_room_id) if school_class.main_room_id else None,
        "regime": str(school_class.regime_id) if school_class.regime_id else None,
    }
    school_class.main_room, school_class.regime = new_room, new_regime
    school_class.save(update_fields=["main_room", "regime", "updated_at"])
    new = {
        "main_room": str(new_room.pk) if new_room else None,
        "regime": str(new_regime.pk) if new_regime else None,
    }
    if new != old:
        record_audit(
            "CLASS_MAIN_ROOM_SET", actor=actor, entity=school_class, old=old, new=new, layer=AuditLayer.ADMINISTRATIVE
        )
    return school_class


def recheck_regime(regime):
    """After a regime's hours changed: its classes' slots must still fit, and the
    rooms they share with other regimes must still not overlap."""
    for school_class in regime.classes.select_related("main_room"):
        _check_slots_in_regime(school_class, regime)
        if school_class.main_room_id:
            Room.objects.select_for_update().get(pk=school_class.main_room_id)
            _check_default_room_sharing(school_class, school_class.main_room, regime)


def _check_session_in_regime(school_class, start, end):
    """A session of a class in a regime: same local day, inside the window."""
    if school_class.regime_id is None:
        return
    tz = _tz(school_class.school)
    local_start, local_end = start.astimezone(tz), end.astimezone(tz)
    if local_start.date() != local_end.date():  # a regime window never crosses midnight
        regime = school_class.regime
        raise ValidationError(
            f"{school_class.name} follows the regime {regime}: a session cannot run past midnight.",
            code="outside_regime",
            params={"regime": regime.name, "start": f"{regime.start_time:%H:%M}", "end": f"{regime.end_time:%H:%M}"},
        )
    _check_in_regime(school_class, local_start.time(), local_end.time())


def _check_in_regime(school_class, start_time, end_time):
    regime = school_class.regime
    if regime is not None and not regime.contains(start_time, end_time):
        raise ValidationError(
            f"{school_class.name} follows the regime {regime}: plan inside it.",
            code="outside_regime",
            params={"regime": regime.name, "start": f"{regime.start_time:%H:%M}", "end": f"{regime.end_time:%H:%M}"},
        )


# =============================================================================
# Recurring slots
# =============================================================================


def _check_course_usable(course):
    """Refuse planning anything that is inactive or closed."""
    course = (
        type(course)
        .objects.select_related("subject__category", "teacher__employee", "school_class", "academic_year")
        .get(pk=course.pk)
    )
    if not course.active:
        raise ValidationError("This course is inactive.", code="course_inactive")
    if not (course.subject.active and course.subject.category.active):
        raise ValidationError("The subject (or its category) is inactive.", code="subject_inactive")
    teacher = course.teacher
    if (
        teacher.professional_status != ProfessionalStatus.ACTIVE
        or teacher.employee.employment_status != EmploymentStatus.ACTIVE
    ):
        raise ValidationError("The teacher is not active.", code="teacher_inactive")
    if not course.school_class.active:
        raise ValidationError("The class is inactive.", code="class_inactive")
    if course.academic_year.status in (AcademicYearStatus.CLOSED, AcademicYearStatus.ARCHIVED):
        raise ValidationError("The academic year is closed.", code="year_closed")
    return course


def find_slot_conflicts(
    *, school_class, teacher, room, weekday, start_time, end_time, effective_from, effective_to=None, exclude=()
):
    """Published slots overlapping in time AND dates, for the same class,
    teacher or room."""
    overlap = ScheduleSlot.objects.filter(
        status=SlotStatus.PUBLISHED, weekday=weekday, start_time__lt=end_time, end_time__gt=start_time
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gte=effective_from))
    if effective_to is not None:
        overlap = overlap.filter(effective_from__lte=effective_to)
    overlap = overlap.exclude(pk__in=[s.pk for s in exclude])
    who = Q(school_class=school_class) | Q(teacher=teacher)
    if room is not None:
        who |= Q(room=room)
    conflicts = []
    for slot in overlap.filter(who):
        kinds = [
            k
            for k, same in (
                ("CLASS", slot.school_class_id == school_class.pk),
                ("TEACHER", slot.teacher_id == teacher.pk),
                ("ROOM", room is not None and slot.room_id == room.pk),
            )
            if same
        ]
        conflicts.append(
            {
                "slot": str(slot.pk),
                "kinds": kinds,
                "weekday": slot.weekday,
                "start_time": slot.start_time.isoformat(),
                "end_time": slot.end_time.isoformat(),
            }
        )
    return conflicts


def _declared_unavailable(teacher, weekday, start_time, end_time):
    return TeacherAvailability.objects.filter(
        teacher=teacher,
        active=True,
        available=False,
        weekday=weekday,
        start_time__lt=end_time,
        end_time__gt=start_time,
    ).exists()


def _slot_plan(course, weekday, start_time, end_time, room, effective_from, effective_to):
    year = course.academic_year
    effective_from = effective_from or year.start_date
    effective_to = effective_to or year.end_date
    if not (1 <= weekday <= 7):
        raise ValidationError("Weekday must be between 1 (Monday) and 7 (Sunday).", code="invalid_weekday")
    if end_time <= start_time:
        raise ValidationError("The slot must end after it starts.", code="invalid_times")
    _check_in_regime(course.school_class, start_time, end_time)
    if effective_from < year.start_date or effective_to > year.end_date or effective_to < effective_from:
        raise ValidationError("The slot must lie within the academic year.", code="outside_year")
    if room is None:
        room = course.school_class.main_room  # theoretical default: the class's room
    return room, effective_from, effective_to


def check_slot(course, *, weekday, start_time, end_time, room=None, effective_from=None, effective_to=None):
    """Dry run used by the admin desktop ("Conflits"): returns what creating
    this slot would hit, without writing anything."""
    course = _check_course_usable(course)
    room, effective_from, effective_to = _slot_plan(
        course, weekday, start_time, end_time, room, effective_from, effective_to
    )
    return {
        "room": str(room.pk) if room else None,
        "conflicts": find_slot_conflicts(
            school_class=course.school_class,
            teacher=course.teacher,
            room=room,
            weekday=weekday,
            start_time=start_time,
            end_time=end_time,
            effective_from=effective_from,
            effective_to=effective_to,
        ),
        "teacher_declared_unavailable": _declared_unavailable(course.teacher, weekday, start_time, end_time),
    }


@transaction.atomic
def create_slot(
    course,
    *,
    actor,
    weekday,
    start_time,
    end_time,
    room=None,
    effective_from=None,
    effective_to=None,
    force_availability=False,
    reason=None,
):
    """Schedule a course weekly. Room: given (practical subjects: laboratory,
    workshop...) or the class's main room. `force_availability` lets an
    administrator plan over a teacher's declared unavailability, with a
    mandatory reason (audited)."""
    require_role(actor, ADMIN_ROLES, school=course.school)
    course = _check_course_usable(course)
    room, effective_from, effective_to = _slot_plan(
        course, weekday, start_time, end_time, room, effective_from, effective_to
    )
    _check_room(room, course.school, course.school_class)
    if _declared_unavailable(course.teacher, weekday, start_time, end_time):
        if not force_availability:
            raise ValidationError("The teacher declared being unavailable at this time.", code="teacher_unavailable")
        reason = _require_reason(reason)
    conflicts = find_slot_conflicts(
        school_class=course.school_class,
        teacher=course.teacher,
        room=room,
        weekday=weekday,
        start_time=start_time,
        end_time=end_time,
        effective_from=effective_from,
        effective_to=effective_to,
    )
    if conflicts:
        _conflict(conflicts)
    slot = ScheduleSlot.objects.create(
        school=course.school,
        course=course,
        teacher=course.teacher,
        school_class=course.school_class,
        academic_year=course.academic_year,
        room=room,
        weekday=weekday,
        start_time=start_time,
        end_time=end_time,
        effective_from=effective_from,
        effective_to=effective_to,
        created_by=actor,
    )
    _check_now()
    record_change(
        ChangeType.SLOT_CREATED, actor=actor, school=course.school, slot=slot, new=_slot_view(slot), reason=reason
    )
    if force_availability and reason:
        record_audit(
            "SLOT_FORCED_OVER_UNAVAILABILITY",
            actor=actor,
            entity=slot,
            new={"reason": reason},
            layer=AuditLayer.ADMINISTRATIVE,
        )
    return slot


def _cancel_future_sessions(slot, from_date, actor, reason):
    for session in slot.sessions.filter(status=SessionStatus.SCHEDULED, date__gte=from_date):
        old = _session_view(session)
        session.status = SessionStatus.CANCELLED
        session.save(update_fields=["status", "updated_at"])
        record_change(
            ChangeType.SESSION_CANCELLED,
            actor=actor,
            school=slot.school,
            session=session,
            old=old,
            new=_session_view(session),
            reason=reason,
            notify=True,
        )


@transaction.atomic
def end_slot(slot, *, actor, last_date, reason):
    """The slot stops after `last_date` (history kept); its later sessions are
    cancelled (families notified)."""
    require_role(actor, ADMIN_ROLES, school=slot.school)
    reason = _require_reason(reason)
    slot = ScheduleSlot.objects.select_for_update().get(pk=slot.pk)
    if slot.status != SlotStatus.PUBLISHED:
        raise ValidationError("This slot is not published.", code="slot_not_published")
    old = _slot_view(slot)
    if last_date < slot.effective_from:
        slot.status = SlotStatus.ARCHIVED
        change = ChangeType.SLOT_ARCHIVED
    else:
        slot.effective_to = min(last_date, slot.effective_to) if slot.effective_to else last_date
        change = ChangeType.SLOT_ENDED
    slot.save()
    _cancel_future_sessions(slot, last_date + timedelta(days=1), actor, reason)
    record_change(
        change, actor=actor, school=slot.school, slot=slot, old=old, new=_slot_view(slot), reason=reason, notify=True
    )
    return slot


@transaction.atomic
def reschedule_slot(slot, *, actor, from_date, weekday, start_time, end_time, room=None, reason):
    """Change day / time / room from `from_date`: the old slot ends the day
    before, a new slot starts — never an in-place edit."""
    require_role(actor, ADMIN_ROLES, school=slot.school)
    reason = _require_reason(reason)
    old_end = slot.effective_to
    end_slot(slot, actor=actor, last_date=from_date - timedelta(days=1), reason=reason)
    return create_slot(
        slot.course,
        actor=actor,
        weekday=weekday,
        start_time=start_time,
        end_time=end_time,
        room=room if room is not None else slot.room,
        effective_from=from_date,
        effective_to=old_end,
        reason=reason,
    )


# =============================================================================
# Dated sessions
# =============================================================================


def leaf_period_for(year, day):
    """The leaf academic period (Séquence, Semestre...) containing `day`."""
    for period in AcademicPeriod.objects.filter(academic_year=year, start_date__lte=day, end_date__gte=day):
        if not period.children.exists():
            return period
    return None


def _in_break(school, year, start, end):
    return SchoolBreak.objects.filter(
        school=school, academic_year=year, affects_scheduling=True, start_datetime__lt=end, end_datetime__gt=start
    ).exists()


def find_session_conflicts(*, school_class, teacher, room, start, end, exclude=()):
    overlap = TeachingSession.objects.filter(
        status=SessionStatus.SCHEDULED, scheduled_start__lt=end, scheduled_end__gt=start
    ).exclude(pk__in=[s.pk for s in exclude])
    who = Q(school_class=school_class) | Q(teacher=teacher)
    if room is not None:
        who |= Q(room=room)
    return [
        {
            "session": str(s.pk),
            "kinds": [
                k
                for k, same in (
                    ("CLASS", s.school_class_id == school_class.pk),
                    ("TEACHER", s.teacher_id == teacher.pk),
                    ("ROOM", room is not None and s.room_id == room.pk),
                )
                if same
            ],
            "scheduled_start": s.scheduled_start.isoformat(),
            "scheduled_end": s.scheduled_end.isoformat(),
        }
        for s in overlap.filter(who)
    ]


def _approved_unavailability(teacher, start, end):
    local_start, local_end = start.astimezone(_tz(teacher.school)), end.astimezone(_tz(teacher.school))
    return TeacherAvailabilityException.objects.filter(
        teacher=teacher,
        status=ExceptionStatus.APPROVED,
        date=local_start.date(),
        start_time__lt=local_end.time(),
        end_time__gt=local_start.time(),
    ).exists()


@transaction.atomic
def generate_sessions(school, *, actor, date_from, date_to, school_class=None):
    """Create the dated sessions of the published slots between two dates.
    Idempotent (one session per slot and date); skips school breaks; a session
    that would conflict (e.g. its teacher is substituting elsewhere) is
    reported, not created."""
    require_role(actor, ADMIN_ROLES, school=school)
    if date_to < date_from or (date_to - date_from).days > MAX_GENERATION_DAYS:
        raise ValidationError(f"Generate at most {MAX_GENERATION_DAYS} days at a time.", code="invalid_range")
    _check_now()
    slots = ScheduleSlot.objects.filter(school=school, status=SlotStatus.PUBLISHED).select_related(
        "course", "academic_year", "school_class"
    )
    if school_class is not None:
        slots = slots.filter(school_class=school_class)
    summary = {"created": 0, "existing": 0, "in_break": 0, "conflicts": []}
    for slot in slots:
        day = max(date_from, slot.effective_from)
        last = min(date_to, slot.effective_to or date_to)
        while day <= last:
            if day.isoweekday() == slot.weekday:
                start, end = _at(school, day, slot.start_time), _at(school, day, slot.end_time)
                if TeachingSession.objects.filter(schedule_slot=slot, date=day).exists():
                    summary["existing"] += 1
                elif _in_break(school, slot.academic_year, start, end):
                    summary["in_break"] += 1
                else:
                    try:
                        with transaction.atomic():
                            TeachingSession.objects.create(
                                school=school,
                                schedule_slot=slot,
                                course=slot.course,
                                school_class=slot.school_class,
                                subject_id=slot.course.subject_id,
                                academic_year=slot.academic_year,
                                academic_period=leaf_period_for(slot.academic_year, day),
                                planned_teacher=slot.teacher,
                                teacher=slot.teacher,
                                room=slot.room,
                                date=day,
                                scheduled_start=start,
                                scheduled_end=end,
                                created_by=actor,
                            )
                        summary["created"] += 1
                    except IntegrityError:
                        summary["conflicts"].append({"slot": str(slot.pk), "date": day.isoformat()})
            day += timedelta(days=1)
    record_audit(
        "SESSIONS_GENERATED",
        actor=actor,
        entity=school,
        school=school,
        new={
            **_jsonable({"date_from": date_from, "date_to": date_to}),
            "created": summary["created"],
            "conflicts": len(summary["conflicts"]),
        },
        layer=AuditLayer.ADMINISTRATIVE,
    )
    return summary


def _schedulable_session(session):
    session = (
        TeachingSession.objects.select_for_update()
        .select_related("school_class__level", "subject", "academic_year")
        .get(pk=session.pk)
    )
    if session.status != SessionStatus.SCHEDULED:
        raise ValidationError("Only a scheduled session can be changed.", code="session_not_scheduled")
    return session


@transaction.atomic
def create_exceptional_session(course, *, actor, start, end, room=None, reason):
    """A one-off session not generated from a slot (catch-up lesson...)."""
    require_role(actor, ADMIN_ROLES, school=course.school)
    reason = _require_reason(reason)
    course = _check_course_usable(course)
    if end <= start:
        raise ValidationError("The session must end after it starts.", code="invalid_times")
    day = _local_date(course.school, start)
    year = course.academic_year
    if not (year.start_date <= day <= year.end_date):
        raise ValidationError("The session must lie within the academic year.", code="outside_year")
    _check_session_in_regime(course.school_class, start, end)
    room = room if room is not None else course.school_class.main_room
    _check_room(room, course.school, course.school_class)
    conflicts = find_session_conflicts(
        school_class=course.school_class, teacher=course.teacher, room=room, start=start, end=end
    )
    if conflicts:
        _conflict(conflicts)
    session = TeachingSession.objects.create(
        school=course.school,
        course=course,
        school_class=course.school_class,
        subject=course.subject,
        academic_year=year,
        academic_period=leaf_period_for(year, day),
        planned_teacher=course.teacher,
        teacher=course.teacher,
        room=room,
        date=day,
        scheduled_start=start,
        scheduled_end=end,
        created_by=actor,
    )
    _check_now()
    record_change(
        ChangeType.SESSION_CREATED,
        actor=actor,
        school=course.school,
        session=session,
        new=_session_view(session),
        reason=reason,
        notify=True,
    )
    return session


@transaction.atomic
def cancel_session(session, *, actor, reason):
    require_role(actor, ADMIN_ROLES, school=session.school)
    reason = _require_reason(reason)
    session = _schedulable_session(session)
    old = _session_view(session)
    session.status = SessionStatus.CANCELLED
    session.save(update_fields=["status", "updated_at"])
    record_change(
        ChangeType.SESSION_CANCELLED,
        actor=actor,
        school=session.school,
        session=session,
        old=old,
        new=_session_view(session),
        reason=reason,
        notify=True,
    )
    return session


@transaction.atomic
def move_session(session, *, actor, new_start, new_end, reason):
    """Move a session and/or give it an exceptional end time. The original
    times are kept on the row (first move) and in the history."""
    require_role(actor, ADMIN_ROLES, school=session.school)
    reason = _require_reason(reason)
    session = _schedulable_session(session)
    if new_end <= new_start:
        raise ValidationError("The session must end after it starts.", code="invalid_times")
    day = _local_date(session.school, new_start)
    year = session.academic_year
    if not (year.start_date <= day <= year.end_date):
        raise ValidationError("The session must lie within the academic year.", code="outside_year")
    _check_session_in_regime(session.school_class, new_start, new_end)
    if _approved_unavailability(session.teacher, new_start, new_end):
        raise ValidationError("The teacher is unavailable at this time.", code="teacher_unavailable")
    conflicts = find_session_conflicts(
        school_class=session.school_class,
        teacher=session.teacher,
        room=session.room,
        start=new_start,
        end=new_end,
        exclude=[session],
    )
    if conflicts:
        _conflict(conflicts)
    old = _session_view(session)
    if session.original_start is None:
        session.original_start, session.original_end = session.scheduled_start, session.scheduled_end
    session.scheduled_start, session.scheduled_end, session.date = new_start, new_end, day
    session.academic_period = leaf_period_for(year, day)
    session.save()
    _check_now()
    record_change(
        ChangeType.SESSION_MOVED,
        actor=actor,
        school=session.school,
        session=session,
        old=old,
        new=_session_view(session),
        reason=reason,
        notify=True,
    )
    return session


@transaction.atomic
def change_session_room(session, room, *, actor, reason):
    require_role(actor, ADMIN_ROLES, school=session.school)
    reason = _require_reason(reason)
    session = _schedulable_session(session)
    _check_room(room, session.school, session.school_class)
    conflicts = find_session_conflicts(
        school_class=session.school_class,
        teacher=session.teacher,
        room=room,
        start=session.scheduled_start,
        end=session.scheduled_end,
        exclude=[session],
    )
    if conflicts:
        _conflict(conflicts)
    old = _session_view(session)
    session.room = room
    session.save(update_fields=["room", "updated_at"])
    _check_now()
    record_change(
        ChangeType.SESSION_ROOM_CHANGED,
        actor=actor,
        school=session.school,
        session=session,
        old=old,
        new=_session_view(session),
        reason=reason,
        notify=True,
    )
    return session


def check_substitute(session, substitute):
    """Compatibility of a substitute, reusing the people-phase machinery:
    qualifications, category, SubjectCompatibilityRule, existing overrides.
    Only COMPATIBLE or OVERRIDDEN is accepted: when a derogation is needed it
    must already exist (CompatibilityOverride, audited)."""
    if substitute.school_id != session.school_id:
        raise PermissionDenied("This teacher belongs to another school.")
    substitute = type(substitute).objects.select_related("employee").get(pk=substitute.pk)  # fresh state
    if substitute.professional_status != ProfessionalStatus.ACTIVE or (
        substitute.employee.employment_status != EmploymentStatus.ACTIVE
    ):
        raise ValidationError("The substitute is not active.", code="teacher_inactive")
    result = evaluate(substitute, session.subject, level=session.school_class.level).result
    if result not in (CompatibilityResult.COMPATIBLE, CompatibilityResult.OVERRIDDEN):
        raise ValidationError(
            "This teacher is not compatible with the subject; an administrative override is required first.",
            code="teacher_incompatible",
            params={"compatibility": str(result)},
        )
    return result


@transaction.atomic
def substitute_teacher(session, substitute, *, actor, reason):
    """Replace the teacher of ONE session. The planned teacher stays recorded
    (planned_teacher); the actual one is `teacher`."""
    require_role(actor, ADMIN_ROLES, school=session.school)
    reason = _require_reason(reason)
    session = _schedulable_session(session)
    if substitute.pk == session.teacher_id:
        raise ValidationError("This teacher already teaches this session.", code="same_teacher")
    compatibility = check_substitute(session, substitute)
    if _approved_unavailability(substitute, session.scheduled_start, session.scheduled_end):
        raise ValidationError("The substitute is unavailable at this time.", code="teacher_unavailable")
    conflicts = [
        c
        for c in find_session_conflicts(
            school_class=session.school_class,
            teacher=substitute,
            room=session.room,
            start=session.scheduled_start,
            end=session.scheduled_end,
            exclude=[session],
        )
        if "TEACHER" in c["kinds"]
    ]
    if conflicts:
        _conflict(conflicts)
    old = _session_view(session)
    session.teacher = substitute
    session.save(update_fields=["teacher", "updated_at"])
    _check_now()
    record_change(
        ChangeType.TEACHER_SUBSTITUTED,
        actor=actor,
        school=session.school,
        session=session,
        old=old,
        new={**_session_view(session), "compatibility": str(compatibility)},
        reason=reason,
        notify=True,
    )
    return session


@transaction.atomic
def restore_teacher(session, *, actor, reason):
    """Give the session back to its planned teacher."""
    require_role(actor, ADMIN_ROLES, school=session.school)
    reason = _require_reason(reason)
    session = _schedulable_session(session)
    if not session.is_substituted:
        raise ValidationError("This session is not substituted.", code="not_substituted")
    conflicts = [
        c
        for c in find_session_conflicts(
            school_class=session.school_class,
            teacher=session.planned_teacher,
            room=None,
            start=session.scheduled_start,
            end=session.scheduled_end,
            exclude=[session],
        )
        if "TEACHER" in c["kinds"]
    ]
    if conflicts:
        _conflict(conflicts)
    old = _session_view(session)
    session.teacher = session.planned_teacher
    session.save(update_fields=["teacher", "updated_at"])
    _check_now()
    record_change(
        ChangeType.TEACHER_RESTORED,
        actor=actor,
        school=session.school,
        session=session,
        old=old,
        new=_session_view(session),
        reason=reason,
        notify=True,
    )
    return session


@transaction.atomic
def swap_sessions(first, second, *, actor, reason):
    """Permutation: the two sessions exchange their times (each keeps its
    course, teacher and room). Done in one transaction with the conflict
    constraints deferred, then checked; both moves are recorded."""
    require_role(actor, ADMIN_ROLES, school=first.school)
    if second.school_id != first.school_id:
        raise PermissionDenied("Both sessions must belong to the same school.")
    if first.pk == second.pk:
        raise ValidationError("Choose two different sessions.", code="same_session")
    reason = _require_reason(reason)
    a, b = _schedulable_session(first), _schedulable_session(second)
    targets = {a.pk: (b.scheduled_start, b.scheduled_end), b.pk: (a.scheduled_start, a.scheduled_end)}
    for session in (a, b):
        start, end = targets[session.pk]
        _check_session_in_regime(session.school_class, start, end)
        if _approved_unavailability(session.teacher, start, end):
            raise ValidationError("A teacher is unavailable at the new time.", code="teacher_unavailable")
        conflicts = find_session_conflicts(
            school_class=session.school_class,
            teacher=session.teacher,
            room=session.room,
            start=start,
            end=end,
            exclude=[a, b],
        )
        if conflicts:
            _conflict(conflicts)
    olds = {a.pk: _session_view(a), b.pk: _session_view(b)}
    _defer()
    for session in (a, b):
        start, end = targets[session.pk]
        if session.original_start is None:
            session.original_start, session.original_end = session.scheduled_start, session.scheduled_end
        day = _local_date(session.school, start)
        session.scheduled_start, session.scheduled_end, session.date = start, end, day
        session.academic_period = leaf_period_for(session.academic_year, day)
        session.save()
    try:
        with transaction.atomic():
            _check_now()
    except IntegrityError:
        _conflict([{"session": str(a.pk)}, {"session": str(b.pk)}])
    for session, other in ((a, b), (b, a)):
        record_change(
            ChangeType.SESSIONS_SWAPPED,
            actor=actor,
            school=session.school,
            session=session,
            old=olds[session.pk],
            new={**_session_view(session), "swapped_with": str(other.pk)},
            reason=reason,
            notify=True,
        )
    return a, b


# =============================================================================
# Teacher availability
# =============================================================================


def _require_self_or_admin(actor, teacher):
    if actor is None or actor.school_id != teacher.school_id:
        raise PermissionDenied("Not allowed for this teacher.")
    is_self = teacher.employee.membership_id == actor.pk
    if not is_self:
        require_role(actor, ADMIN_ROLES, school=teacher.school)
    return is_self


@transaction.atomic
def declare_availability(teacher, *, actor, weekday, start_time, end_time, available, reason=None):
    _require_self_or_admin(actor, teacher)
    if not available:
        reason = _require_reason(reason)
    availability = TeacherAvailability.objects.create(
        school=teacher.school,
        teacher=teacher,
        weekday=weekday,
        start_time=start_time,
        end_time=end_time,
        available=available,
        reason=reason,
    )
    record_audit(
        "AVAILABILITY_DECLARED",
        actor=actor,
        entity=availability,
        new=_jsonable(
            {
                "weekday": weekday,
                "start_time": start_time,
                "end_time": end_time,
                "available": available,
                "reason": reason,
            }
        ),
    )
    return availability


@transaction.atomic
def withdraw_availability(availability, *, actor):
    _require_self_or_admin(actor, availability.teacher)
    availability.active = False
    availability.save(update_fields=["active", "updated_at"])
    record_audit("AVAILABILITY_WITHDRAWN", actor=actor, entity=availability)
    return availability


@transaction.atomic
def request_unavailability(teacher, *, actor, date, start_time, end_time, reason):
    """Submitted by the teacher (or recorded by an admin on their behalf):
    always PENDING — nobody approves at submission time."""
    _require_self_or_admin(actor, teacher)
    reason = _require_reason(reason)
    if end_time <= start_time:
        raise ValidationError("The period must end after it starts.", code="invalid_times")
    request = TeacherAvailabilityException.objects.create(
        school=teacher.school,
        teacher=teacher,
        date=date,
        start_time=start_time,
        end_time=end_time,
        reason=reason,
        requested_by=actor,
    )
    record_audit(
        "UNAVAILABILITY_REQUESTED",
        actor=actor,
        entity=request,
        new=_jsonable({"date": date, "start_time": start_time, "end_time": end_time, "reason": reason}),
    )
    return request


@transaction.atomic
def cancel_unavailability(request, *, actor):
    """The teacher withdraws a request that is not decided yet."""
    if request.teacher.employee.membership_id != actor.pk:
        raise PermissionDenied("Only the teacher can withdraw their request.")
    request = TeacherAvailabilityException.objects.select_for_update().get(pk=request.pk)
    if request.status not in (ExceptionStatus.PENDING, ExceptionStatus.CHANGES_REQUESTED):
        raise ValidationError("This request is already decided.", code="already_decided")
    request.status = ExceptionStatus.CANCELLED
    request.save(update_fields=["status", "updated_at"])
    record_audit("UNAVAILABILITY_CANCELLED", actor=actor, entity=request)
    return request


def impacted_sessions(request):
    """Scheduled sessions of the teacher overlapping an unavailability."""
    start = _at(request.school, request.date, request.start_time)
    end = _at(request.school, request.date, request.end_time)
    return TeachingSession.objects.filter(
        teacher=request.teacher, status=SessionStatus.SCHEDULED, scheduled_start__lt=end, scheduled_end__gt=start
    )


@transaction.atomic
def decide_unavailability(request, *, actor, decision, comment=None):
    """APPROVED / REJECTED / CHANGES_REQUESTED by an administrator who is NOT
    the teacher concerned (no self-approval). A comment is required unless
    approving. Approval changes no session by itself: the impacted sessions
    are returned for the administration to substitute, swap or cancel."""
    require_role(actor, ADMIN_ROLES, school=request.school)
    if request.teacher.employee.membership_id == actor.pk:
        raise PermissionDenied("A teacher cannot decide on their own request.")
    if decision not in (ExceptionStatus.APPROVED, ExceptionStatus.REJECTED, ExceptionStatus.CHANGES_REQUESTED):
        raise ValidationError("Invalid decision.", code="invalid_decision")
    if decision != ExceptionStatus.APPROVED:
        comment = _require_reason(comment)
    request = TeacherAvailabilityException.objects.select_for_update().get(pk=request.pk)
    if request.status != ExceptionStatus.PENDING:
        raise ValidationError("This request is not pending.", code="already_decided")
    old = {"status": request.status}
    request.status, request.decided_by, request.decided_at = decision, actor, timezone.now()
    request.decision_comment = comment
    request.save()
    record_audit(
        "UNAVAILABILITY_DECIDED",
        actor=actor,
        entity=request,
        old=old,
        new={"status": decision, "comment": comment},
        layer=AuditLayer.ADMINISTRATIVE,
    )
    return request, list(impacted_sessions(request)) if decision == ExceptionStatus.APPROVED else []


# =============================================================================
# Breaks
# =============================================================================


@transaction.atomic
def create_school_break(
    year, *, actor, name, start_datetime, end_datetime, break_type="HOLIDAY", affects_scheduling=True
):
    require_role(actor, ADMIN_ROLES, school=year.school)
    _check_break(start_datetime, end_datetime, break_type)
    school_break = SchoolBreak.objects.create(
        school=year.school,
        academic_year=year,
        name=name,
        start_datetime=start_datetime,
        end_datetime=end_datetime,
        break_type=break_type,
        affects_scheduling=affects_scheduling,
    )
    record_audit(
        "SCHOOL_BREAK_CREATED",
        actor=actor,
        entity=school_break,
        new=_jsonable({"name": name, "start": start_datetime, "end": end_datetime}),
        layer=AuditLayer.ADMINISTRATIVE,
    )
    return school_break


BREAK_FIELDS = ("name", "start_datetime", "end_datetime", "break_type", "affects_scheduling")


def _check_break(start_datetime, end_datetime, break_type):
    if end_datetime <= start_datetime:
        raise ValidationError("The end must be after the start.", code="invalid_dates")
    if break_type not in BreakType.values:
        raise ValidationError("Unknown break type.", code="break_type_invalid")


@transaction.atomic
def update_school_break(school_break, *, actor, **changes):
    """Edit a holiday / interruption (admin desktop "Vacances"). Sessions
    already generated are not touched: generation skips breaks from now on,
    and existing sessions are cancelled one by one by the administrator."""
    require_role(actor, ADMIN_ROLES, school=school_break.school)
    school_break = SchoolBreak.objects.select_for_update().get(pk=school_break.pk)
    old = _jsonable({f: getattr(school_break, f) for f in BREAK_FIELDS})
    for name in BREAK_FIELDS:
        if name in changes:
            value = changes[name]
            if name == "name":
                value = (value or "").strip()
                if not value:
                    raise ValidationError("A name is required.", code="name_required")
            setattr(school_break, name, value)
    _check_break(school_break.start_datetime, school_break.end_datetime, school_break.break_type)
    school_break.save()
    record_audit(
        "SCHOOL_BREAK_UPDATED",
        actor=actor,
        entity=school_break,
        old=old,
        new=_jsonable({f: getattr(school_break, f) for f in BREAK_FIELDS}),
        layer=AuditLayer.ADMINISTRATIVE,
    )
    return school_break
