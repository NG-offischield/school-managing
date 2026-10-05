"""E2E fixture of the guardian and staff journeys (TEST database only).

The opt-in live tests of the guardian and staff apps
(mobile/apps/{guardian,staff}/test/live_test.dart) play their journeys
through the API. What has no API (QR issuing for a given pupil is admin
API, but payroll periods, salaries and staff functions are set up with the
school) is prepared here, in the E2E user's school, with the domain services:

    current year (reused, or created and made current), a class with a room,
    a course and two sessions TODAY (the staff planning);
    two enrolled pupils with their year QR code;
    guardian A and guardian B (accounts WITHOUT password: the live test
    activates A through the activation API); B scans pupil 2 (A must never
    see it);
    a staff member (account without password, function "Économe E2E", a
    salary) and an APPROVED payroll on a one-day payroll period.

    docker exec -e E2E_USER=e2eadmin <test container> python manage.py shell \
        -c "exec(open('tools/e2e_field_fixture.py').read())"

Prints ONE line of JSON. Refuses to run outside config.settings.test.
"""

import json
import os
import uuid
from datetime import date, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from apps.academics import services as academics
from apps.academics.models import AcademicYear, AcademicYearStatus
from apps.accounts.models import MembershipRole, Role, SchoolMembership, User
from apps.attendance import services as attendance
from apps.gradebook import services as gradebook
from apps.payroll import services as payroll
from apps.payroll.models import PayrollPeriod, StaffPayroll
from apps.people import services as people
from apps.people.models import StaffFunction
from apps.scheduling import services as scheduling

if settings.SETTINGS_MODULE != "config.settings.test":
    raise SystemExit("The E2E fixture only runs against the TEST settings / database.")

admin = SchoolMembership.objects.select_related("school").get(user__username=os.environ.get("E2E_USER", "e2eadmin"))
school = admin.school
today = timezone.localdate()
suffix = uuid.uuid4().hex[:5].upper()


def member(role, first, last):
    """An account WITHOUT password (activated later by its owner)."""
    login = f"{first}.{last}.{suffix}@e2e.test".lower()
    user = User.objects.create_user(username=login, email=login, first_name=first, last_name=f"{last}{suffix}")
    user.set_unusable_password()
    user.save(update_fields=["password"])
    membership = SchoolMembership.objects.create(school=school, user=user, status="ACTIVE", joined_at=timezone.now())
    MembershipRole.objects.create(membership=membership, role=Role.objects.get(code=role))
    return membership


year = AcademicYear.objects.filter(school=school, start_date__lte=today, end_date__gte=today).first()
if year is None:
    start = date(today.year if today.month >= 9 else today.year - 1, 9, 1)
    year = academics.create_academic_year(
        school,
        name=f"{start.year}-{start.year + 1}",
        start_date=start,
        end_date=date(start.year + 1, 7, 31),
        status=AcademicYearStatus.ACTIVE,
    )
if not year.is_current:
    year = academics.set_current_year(year)

# --- planning of the day (what the staff app shows) ---------------------------
level = academics.create_level(school, actor=admin, code=f"F{suffix}", name=f"Niveau terrain {suffix}", order_index=96)
room = scheduling.create_room(school, actor=admin, code=f"RF{suffix}", name=f"Salle terrain {suffix}")
klass = academics.create_class(
    school, actor=admin, name=f"E2E-FLD-{suffix}", level=level, academic_year=year, main_room=room
)
category = academics.create_category(school, actor=admin, code=f"FC{suffix}", name=f"Catégorie terrain {suffix}")
subject = academics.create_subject(
    school, actor=admin, code=f"FS{suffix}", name=f"Sciences {suffix}", category=category
)
teacher_member = member("TEACHER", "Prof", "Terrain")
employee = people.create_employee(teacher_member, employee_number=f"EF-{suffix}", employee_type="TEACHER")
teacher = people.create_teacher(employee, pedagogical_category=category, primary_subject=subject)
course = gradebook.create_course(klass, subject, teacher, actor=admin, coefficient=Decimal("2"))
for start_hour in (7, 15):
    scheduling.create_slot(
        course,
        actor=admin,
        weekday=today.isoweekday(),
        start_time=time(start_hour),
        end_time=time(start_hour + 2),
        effective_from=today,
    )
scheduling.generate_sessions(school, actor=admin, date_from=today, date_to=today, school_class=klass)

# --- pupils and their QR codes -------------------------------------------------
pupils = []
for index, first in enumerate(("Lea", "Tom")):
    pupil = people.create_student(
        school,
        student_number=f"E2E-FLD-{index}-{suffix}",
        registration_number=f"E2E-FLD-{index}-{suffix}",
        first_name=first,
        last_name=f"Portail{suffix}",
        date_of_birth=date(2013, 3, 1 + index),
        sex="F" if index == 0 else "M",
    )
    people.enroll_student(pupil, klass, enrollment_date=max(year.start_date, today - timedelta(days=1)))
    pupils.append((pupil, attendance.issue_qr_code(pupil, actor=admin, academic_year=year)))

# --- guardians -----------------------------------------------------------------
guardian_a = member("GUARDIAN", "Gardien", "Alpha")
people.create_guardian(guardian_a, guardian_number=f"GA-{suffix}")
guardian_b = member("GUARDIAN", "Gardien", "Bravo")
people.create_guardian(guardian_b, guardian_number=f"GB-{suffix}")
other_scan = attendance.scan(pupils[1][1].token, actor=guardian_b).scan

# --- staff: function, salary, an approved payroll ------------------------------
staff_member = member("STAFF", "Agent", "Econome")
staff_employee = people.create_employee(staff_member, employee_number=f"ES-{suffix}", employee_type="STAFF")
staff = people.create_staff(staff_employee, staff_number=f"PS-{suffix}")
function = StaffFunction.objects.create(school=school, code=f"ECO{suffix}", name=f"Économe E2E {suffix}")
people.assign_staff_function(staff, function, actor=admin)

# A one-day payroll period on the first day of the year not covered yet.
day = year.start_date
while PayrollPeriod.objects.filter(school=school, start_date__lte=day, end_date__gte=day).exists():
    day += timedelta(days=1)
payroll.set_staff_salary(staff, actor=admin, monthly_salary="120000", effective_from=day)
period = payroll.create_period(year, actor=admin, name=f"Paie E2E {suffix}", start_date=day, end_date=day)
payroll.calculate_period(period, actor=admin)
staff_payroll = StaffPayroll.objects.get(staff=staff, payroll_period=period)
payroll.approve_payroll(staff_payroll, actor=admin)

print(
    json.dumps(
        {
            "school_code": school.code,
            "pupil_token": pupils[0][1].token,
            "pupil_name": pupils[0][0].full_name,
            "class_name": klass.name,
            "guardian_member": str(guardian_a.pk),
            "guardian_login": guardian_a.user.email,
            "other_guardian_scan": str(other_scan.pk),
            "staff_member": str(staff_member.pk),
            "staff_login": staff_member.user.email,
            "staff_function": function.name,
            "staff_payroll": str(staff_payroll.pk),
            "payroll_period": period.name,
        }
    )
)
