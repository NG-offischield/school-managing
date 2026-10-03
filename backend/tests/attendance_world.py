"""Attendance test world: gradebook world (year 2025-2026, class 3e A with
3 enrolled students) + a guardian, a Monday policy and QR codes."""

from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from apps.attendance import services as att
from apps.people import services as people

from .factories import member_with_role
from .gradebook_world import make_world

DOUALA = ZoneInfo("Africa/Douala")
MONDAY = datetime(2025, 10, 6, tzinfo=DOUALA).date()  # a Monday inside the year


def at(hour, minute=0, day=MONDAY):
    return datetime.combine(day, time(hour, minute), tzinfo=DOUALA)


def make_attendance_world(school):
    w = make_world(school)
    w.guardian_member = member_with_role(school, "GUARDIAN")
    w.guardian = people.create_guardian(w.guardian_member, guardian_number="G-01")
    att.set_policy(
        school,
        1,
        actor=w.admin,
        late_after_time=time(7, 30),
        morning_absence_cutoff=time(10, 0),
        absence_hours=Decimal("8.00"),
    )
    w.qr = {s.pk: att.issue_qr_code(s, actor=w.admin) for s in w.students}
    return w
