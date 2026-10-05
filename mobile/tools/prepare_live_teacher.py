"""Prepare a REAL teacher journey on a TEST backend (never the dev database).

Run with the desktop's virtualenv; the administrator of the test backend is
given through the environment (as for the desktop E2E):

    SCHOOL_ADMIN_E2E_URL=http://127.0.0.1:8001/api/v1/ SCHOOL_ADMIN_E2E_USER=... SCHOOL_ADMIN_E2E_PASSWORD=...
    desktop/.venv/Scripts/python mobile/tools/prepare_live_teacher.py

Through the EXISTING admin API only (desktop services), it creates:
- the school year containing today (made current if needed);
- a level, two classes, a subject shared by two NEW teachers A and B
  (accounts without password), one course each;
- weekly slots for this week + generated sessions, an exceptional session of
  A that started one hour ago (self check-in possible), and a substitution of
  B's session by A (-> SUBSTITUTION notification to A);
- an activation code for A (B stays inactive: A's isolation is checked
  against B's data).

Prints ONE line of JSON for the live Flutter test (activation code, login,
ids). The code is single-use and expires; nothing is written to disk.
"""

import json
import os
import sys
import uuid
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "desktop"))

from school_admin.api import ApiClient  # noqa: E402
from school_admin.services.accounts import AccountService  # noqa: E402
from school_admin.services.catalog import CategoryService, SubjectService  # noqa: E402
from school_admin.services.classes import ClassService  # noqa: E402
from school_admin.services.courses import CourseService  # noqa: E402
from school_admin.services.planning import PlanningService  # noqa: E402
from school_admin.services.structure import LevelService, YearService  # noqa: E402
from school_admin.services.teachers import TeacherService  # noqa: E402

DEVICE = {"identifier": "live-prep", "device_name": "Préparation E2E", "device_type": "DESKTOP", "platform": "WINDOWS"}


def main():
    url, user, password = (
        os.environ[k] for k in ("SCHOOL_ADMIN_E2E_URL", "SCHOOL_ADMIN_E2E_USER", "SCHOOL_ADMIN_E2E_PASSWORD")
    )
    api = ApiClient(url)
    tokens = api.request(
        "POST", "auth/login/", json={"identifier": user, "password": password, "device": DEVICE}, auth=False
    )[0]
    api.access_token = tokens["access_token"]
    suffix = uuid.uuid4().hex[:5].upper()
    today = date.today()
    monday = today - timedelta(days=today.weekday())

    years = YearService(api)
    start = date(today.year if today.month >= 9 else today.year - 1, 9, 1)
    name = f"{start.year}-{start.year + 1}"
    year = next((y for y in years.list() if y.name == name), None)
    if year is None:
        year = years.create(name=name, start_date=start, end_date=date(start.year + 1, 7, 31))
    if not year.is_current:
        years.set_current(year.id)

    level = LevelService(api).create(code=f"M{suffix}", name=f"Niveau mobile {suffix}", cycle="MOB", order_index=90)
    classes = ClassService(api)
    class_a = classes.create(name=f"MOB-A {suffix}", level_id=level.id, academic_year_id=year.id)
    class_b = classes.create(name=f"MOB-B {suffix}", level_id=level.id, academic_year_id=year.id)
    category = CategoryService(api).create(code=f"MC{suffix}", name=f"Catégorie mobile {suffix}")
    subject = SubjectService(api).create(code=f"MS{suffix}", name=f"Matière mobile {suffix}", category_id=category.id)

    teachers = TeacherService(api)

    def teacher(letter):
        return teachers.create(
            last_name=f"Mobile{letter}{suffix}",
            first_name=f"Prof{letter}",
            email=f"prof.{letter.lower()}.{suffix.lower()}@mobile.test",
            employee_number=f"MOB-{letter}-{suffix}",
            category_id=category.id,
            primary_subject_id=subject.id,
        )

    a, b = teacher("A"), teacher("B")
    courses = CourseService(api)
    course_a = courses.create(class_id=class_a.id, subject_id=subject.id, teacher_id=a.id, coefficient="2")
    course_b = courses.create(class_id=class_b.id, subject_id=subject.id, teacher_id=b.id, coefficient="2")

    planning = PlanningService(api)
    tomorrow = today + timedelta(days=1)
    # A's weekly slot today must not overlap the exceptional session below (one hour ago -> +30 min),
    # whatever the time the script runs: 7-9 h in the afternoon, 18-20 h in the morning.
    hour_now = datetime.now(timezone(timedelta(hours=1))).hour
    for course, day, hour in (
        (course_a, today, 7 if hour_now >= 11 else 18),
        (course_a, tomorrow, 8),
        (course_b, tomorrow, 10),
        (course_b, today, 16),
    ):
        planning.create_slot(
            course_id=course.id, weekday=day.isoweekday(), start_time=time(hour), end_time=time(hour + 2)
        )
    planning.generate(date_from=monday, date_to=monday + timedelta(days=6))

    # The school's time zone (Africa/Douala, UTC+1 all year): an aware datetime, whatever the PC's zone.
    now = datetime.now(timezone(timedelta(hours=1))).replace(second=0, microsecond=0)
    started = api.post(
        "admin/sessions/",
        {
            "course": course_a.id,
            "start": max(now - timedelta(hours=1), now.replace(hour=0, minute=1)).isoformat(),
            "end": (now + timedelta(minutes=30)).isoformat(),
            "reason": "Séance de rattrapage (test mobile)",
        },
    )
    b_sessions = planning.week(monday, teacher_id=b.id)
    b_tomorrow = next(s for s in b_sessions if s.date == tomorrow)
    b_today = next(s for s in b_sessions if s.date == today)
    planning.substitute(b_tomorrow.id, a.id, "Absence de l'enseignant B (test mobile)")

    issued = AccountService(api).issue_code(TeacherService(api).get(a.id).membership_id)
    print(
        json.dumps(
            {
                "code": issued.code,
                "login": issued.account.login,
                "started_session": started["id"],
                "substituted_session": b_tomorrow.id,
                "b_only_session": b_today.id,
                "course_a_class": class_a.name,
                "course_b_class": class_b.name,
            }
        )
    )


if __name__ == "__main__":
    main()
