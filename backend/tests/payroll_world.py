"""Payroll test world, built on the planning world (year 2025-2026, class
3e A, maths by tm, french by tf).

- periods "Octobre 2025" (10-01..10-31) and "Novembre 2025";
- tm's vacation rate 5 000 XAF per 120-minute vacation from 2025-09-01;
- four 2-hour maths sessions of tm in October (Mon 6 .. Thu 9), the
  Thursday one cancelled;
- a staff member (salary 150 000 / month);
- treasury credited with 1 000 000 XAF.
"""

from datetime import date, timedelta

from apps.finance import services as fin
from apps.payroll import services as pay
from apps.people import services as people
from apps.people.models import EmployeeType
from apps.scheduling import services as planning

from .factories import EmployeeFactory
from .planning_world import MONDAY, at, make_planning_world


def session(w, day, start=(8, 0), end=(10, 0), course=None):
    return planning.create_exceptional_session(
        course or w.course_maths, actor=w.admin, start=at(*start, day=day), end=at(*end, day=day), reason="test"
    )


def make_staff(w, number="ST-01"):
    employee = EmployeeFactory(school=w.school, employee_type=EmployeeType.STAFF)
    return people.create_staff(employee, staff_number=number)


def make_payroll_world(school):
    w = make_planning_world(school)
    w.october = pay.create_period(
        w.year, actor=w.admin, name="Octobre 2025", start_date=date(2025, 10, 1), end_date=date(2025, 10, 31)
    )
    w.november = pay.create_period(
        w.year, actor=w.admin, name="Novembre 2025", start_date=date(2025, 11, 1), end_date=date(2025, 11, 30)
    )
    w.rate = pay.set_teacher_rate(
        w.tm, actor=w.admin, academic_year=w.year, vacation_rate="5000", effective_from=date(2025, 9, 1)
    )
    w.sessions = [session(w, MONDAY + timedelta(days=i)) for i in range(4)]
    planning.cancel_session(w.sessions[3], actor=w.admin, reason="grève")
    w.staff = make_staff(w)
    w.salary = pay.set_staff_salary(w.staff, actor=w.admin, monthly_salary="150000", effective_from=date(2025, 9, 1))
    fin.credit_treasury(school, "1000000", actor=w.admin)
    return w
