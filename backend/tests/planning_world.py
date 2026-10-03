"""Planning test world, built on the gradebook world (year 2025-2026, class
3e A: maths coef 4 by tm, french by tf, 3 students).

Adds rooms R12 (classroom, 40) and LAB (laboratory, 30), class 3e B with its
own maths course taught by the SAME teacher tm (teacher conflicts), and
helpers to build local datetimes on Monday 2025-10-06.
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from apps.gradebook import services as gb
from apps.scheduling import services as planning

from .factories import SchoolClassFactory
from .gradebook_world import make_world

DOUALA = ZoneInfo("Africa/Douala")
MONDAY = datetime(2025, 10, 6, tzinfo=DOUALA).date()


def at(hour, minute=0, day=MONDAY):
    return datetime.combine(day, time(hour, minute), tzinfo=DOUALA)


def make_planning_world(school):
    w = make_world(school)
    w.r12 = planning.create_room(school, actor=w.admin, code="R12", name="Salle 12", capacity=40)
    w.lab = planning.create_room(
        school, actor=w.admin, code="LAB", name="Laboratoire", room_type="LABORATORY", capacity=30
    )
    planning.set_class_main_room(w.klass, w.r12, actor=w.admin)
    w.klass.refresh_from_db()
    w.klass_b = SchoolClassFactory(school=school, name="3e B", academic_year=w.year, level=w.klass.level)
    w.course_b_maths = gb.create_course(w.klass_b, w.maths, w.tm, actor=w.admin)
    return w


def slot(w, course=None, weekday=1, start=(8, 0), end=(10, 0), **kw):
    return planning.create_slot(
        course or w.course_maths, actor=w.admin, weekday=weekday, start_time=time(*start), end_time=time(*end), **kw
    )


def generate(w, days=0, start=MONDAY, school_class=None):
    return planning.generate_sessions(
        w.school, actor=w.admin, date_from=start, date_to=start + timedelta(days=days), school_class=school_class
    )
