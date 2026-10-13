"""Planning (backend scheduling/api.py, ADR 0012 / 0021). Thin client of the
EXISTING planning engine: slots, sessions, rooms, availability requests and
school breaks. Conflicts, compatibility, availability and breaks are decided
by the server; this module sends the request and relays its answer (a 409
planning_conflict carries the conflicting slots / sessions, explained by
messages.explain_conflicts). Nothing is recomputed here.
"""

from datetime import date, datetime, timedelta

from ..api.errors import ValidationFailed
from ..i18n import tr
from ..models import Room, SchoolBreak, Session, Slot, UnavailabilityRequest


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _require(**fields):
    missing = {name: [tr("Obligatoire.")] for name, value in fields.items() if value in (None, "")}
    if missing:
        raise ValidationFailed("Formulaire incomplet.", details=missing)


def monday_of(day):
    return day - timedelta(days=day.weekday())


class PlanningService:
    def __init__(self, api):
        self.api = api

    # --- rooms -----------------------------------------------------------------------
    def rooms(self, *, search=None, active=None):
        rows = self.api.list_all(
            "rooms/", search=(search or "").strip() or None, active=None if active is None else str(active).lower()
        )
        return [Room.from_api(r) for r in rows]

    def create_room(self, *, code, name, room_type="CLASSROOM", capacity=None, bench_count=None):
        _require(code=(code or "").strip(), name=(name or "").strip())
        payload = {"code": code.strip(), "name": name.strip(), "room_type": room_type}
        payload |= {k: v for k, v in (("capacity", capacity), ("bench_count", bench_count)) if v is not None}
        return Room.from_api(self.api.post("admin/rooms/", payload))

    def update_room(self, room_id, **fields):
        return Room.from_api(self.api.patch(f"admin/rooms/{room_id}/", fields))

    def deactivate(self, room_id):
        return Room.from_api(self.api.post(f"admin/rooms/{room_id}/deactivate/"))

    def reactivate(self, room_id):
        return Room.from_api(self.api.post(f"admin/rooms/{room_id}/reactivate/"))

    def set_main_room(self, class_id, room_id):
        _require(school_class=class_id)
        return self.api.post(f"admin/classes/{class_id}/main-room/", {"room": room_id or None})

    # --- slots -----------------------------------------------------------------------
    def slots(self, *, status="PUBLISHED", class_id=None, teacher_id=None, room_id=None, subject_id=None):
        rows = self.api.list_all(
            "schedules/",
            status=status or None,
            school_class=class_id or None,
            teacher=teacher_id or None,
            room=room_id or None,
            subject=subject_id or None,
        )
        return [Slot.from_api(r) for r in rows]

    @staticmethod
    def _slot_payload(course_id, weekday, start_time, end_time, room_id, effective_from, effective_to):
        _require(course=course_id, weekday=weekday, start_time=start_time, end_time=end_time)
        payload = {
            "course": course_id,
            "weekday": weekday,
            "start_time": _iso(start_time),
            "end_time": _iso(end_time),
            "room": room_id or None,
        }
        if effective_from:
            payload["effective_from"] = _iso(effective_from)
        if effective_to:
            payload["effective_to"] = _iso(effective_to)
        return payload

    def check_slot(
        self, *, course_id, weekday, start_time, end_time, room_id=None, effective_from=None, effective_to=None
    ):
        """Dry run: {"room", "conflicts": [...], "teacher_declared_unavailable"} as computed by the server."""
        payload = self._slot_payload(course_id, weekday, start_time, end_time, room_id, effective_from, effective_to)
        return self.api.post("admin/schedules/check/", payload)

    def create_slot(
        self,
        *,
        course_id,
        weekday,
        start_time,
        end_time,
        room_id=None,
        effective_from=None,
        effective_to=None,
        force_availability=False,
        reason=None,
    ):
        payload = self._slot_payload(course_id, weekday, start_time, end_time, room_id, effective_from, effective_to)
        if force_availability:
            payload |= {"force_availability": True, "reason": reason}
        return Slot.from_api(self.api.post("admin/schedules/", payload))

    def end_slot(self, slot_id, *, last_date, reason):
        _require(last_date=last_date, reason=(reason or "").strip())
        return Slot.from_api(
            self.api.post(f"admin/schedules/{slot_id}/end/", {"last_date": _iso(last_date), "reason": reason})
        )

    def reschedule_slot(self, slot_id, *, from_date, weekday, start_time, end_time, room_id=None, reason):
        _require(from_date=from_date, weekday=weekday, reason=(reason or "").strip())
        payload = {
            "from_date": _iso(from_date),
            "weekday": weekday,
            "start_time": _iso(start_time),
            "end_time": _iso(end_time),
            "room": room_id or None,
            "reason": reason,
        }
        return Slot.from_api(self.api.post(f"admin/schedules/{slot_id}/reschedule/", payload))

    # --- sessions --------------------------------------------------------------------
    def week(self, monday, *, class_id=None, teacher_id=None, room_id=None, subject_id=None):
        """Sessions of the week starting on `monday` (server filters)."""
        rows = self.api.list_all(
            "sessions/",
            date_from=monday.isoformat(),
            date_to=(monday + timedelta(days=6)).isoformat(),
            school_class=class_id or None,
            teacher=teacher_id or None,
            room=room_id or None,
            subject=subject_id or None,
        )
        return [Session.from_api(r) for r in rows]

    def session(self, session_id):
        return Session.from_api(self.api.get(f"sessions/{session_id}/"))

    def generate(self, *, date_from, date_to, class_id=None):
        """{"created", "existing", "in_break", "conflicts"} as reported by the server."""
        _require(date_from=date_from, date_to=date_to)
        return self.api.post(
            "admin/sessions/generate/",
            {"date_from": _iso(date_from), "date_to": _iso(date_to), "school_class": class_id or None},
        )

    def _action(self, session_id, name, payload):
        if not (payload.get("reason") or "").strip():
            raise ValidationFailed("Formulaire incomplet.", details={"reason": [tr("Indiquez le motif.")]})
        return Session.from_api(self.api.post(f"admin/sessions/{session_id}/{name}/", payload))

    def cancel(self, session_id, reason):
        return self._action(session_id, "cancel", {"reason": reason})

    def move(self, session_id, *, new_start: datetime, new_end: datetime, reason):
        return self._action(
            session_id, "move", {"new_start": _iso(new_start), "new_end": _iso(new_end), "reason": reason}
        )

    def change_room(self, session_id, room_id, reason):
        return self._action(session_id, "room", {"room": room_id or None, "reason": reason})

    def substitute(self, session_id, teacher_id, reason):
        _require(teacher=teacher_id)
        return self._action(session_id, "substitute", {"teacher": teacher_id, "reason": reason})

    def restore_teacher(self, session_id, reason):
        return self._action(session_id, "restore-teacher", {"reason": reason})

    # --- teacher presence (backend payroll/api.py: spec §15, self-reported then verified) ---
    def validate_presence(self, session_id, reason=""):
        """The session was really taught: COMPLETED and payable (the server
        refuses a cancelled, unfinished, already validated or paid session)."""
        comment = (reason or "").strip()
        return self.api.post(f"admin/sessions/{session_id}/validate/", {"reason": comment} if comment else {})

    def reject_presence(self, session_id, reason):
        """Not taught: never payable (a paid session gets a negative adjustment, server side)."""
        if not (reason or "").strip():
            raise ValidationFailed("Formulaire incomplet.", details={"reason": [tr("Indiquez le motif.")]})
        return self.api.post(f"admin/sessions/{session_id}/reject/", {"reason": reason.strip()})

    def changes(self, *, since: date):
        return self.api.list_all("planning/changes/", date_from=since.isoformat())

    # --- availability ----------------------------------------------------------------
    def requests(self, *, status="PENDING", teacher_id=None):
        rows = self.api.list_all("admin/unavailability/", status=status or None, teacher=teacher_id or None)
        return [UnavailabilityRequest.from_api(r) for r in rows]

    def impacted(self, request_id):
        return [Session.from_api(r) for r in self.api.get(f"admin/unavailability/{request_id}/impacted-sessions/")]

    def decide(self, request_id, decision, comment=None):
        answer = self.api.post(f"admin/unavailability/{request_id}/decide/", {"decision": decision, "comment": comment})
        return (
            UnavailabilityRequest.from_api(answer["request"]),
            [Session.from_api(r) for r in answer.get("impacted_sessions", [])],
        )

    def availability(self, teacher_id):
        return self.api.list_all(f"teachers/{teacher_id}/availability/")

    # --- breaks ------------------------------------------------------------------------
    def breaks(self):
        return [SchoolBreak.from_api(r) for r in self.api.list_all("school-breaks/")]

    def create_break(self, *, year_id, name, start, end, break_type="HOLIDAY", affects_scheduling=True):
        _require(academic_year=year_id, name=(name or "").strip(), start=start, end=end)
        payload = {
            "academic_year": year_id,
            "name": name.strip(),
            "start_datetime": _iso(start),
            "end_datetime": _iso(end),
            "break_type": break_type,
            "affects_scheduling": affects_scheduling,
        }
        return SchoolBreak.from_api(self.api.post("admin/school-breaks/", payload))

    def update_break(self, break_id, *, name, start, end, break_type, affects_scheduling):
        _require(name=(name or "").strip(), start=start, end=end)
        payload = {
            "name": name.strip(),
            "start_datetime": _iso(start),
            "end_datetime": _iso(end),
            "break_type": break_type,
            "affects_scheduling": affects_scheduling,
        }
        return SchoolBreak.from_api(self.api.patch(f"admin/school-breaks/{break_id}/", payload))
