"""E2E fixture of the cross-app integration run (TEST database only).

e2e/cross_app.mjs plays the 11 cross-application scenarios over the REAL
network (REST + WebSocket, the LAN address of the PC) against a TEST backend
where the DEMO dataset was seeded (`seed_demo`). What the scenarios need on
top of DEMO is prepared here with the domain services:

    a teacher (TEACHER) with a course in DEMO's "6e A", a weekly slot TOMORROW
    and the generated session (a planning change will concern the 6e A
    parents A, B, C, D — not 3e B's S4);
    a guardian (GUARDIAN) and a staff member (STAFF) of DEMO;
    a second school "TEST01" (created if absent) with its own administrator,
    to check that nothing leaks between DEMO and TEST01.

The new accounts receive the password given in DEMO_PASSWORD (environment
only: never stored in the repository, never printed):

    docker exec -e DEMO_PASSWORD <test container> python manage.py shell \
        -c "exec(open('tools/e2e_cross_app_fixture.py').read())"

Prints ONE line of JSON (logins and ids, no secret). Refuses to run outside
config.settings.test.
"""

import json
import os
import uuid
from datetime import time, timedelta
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from apps.academics import services as academics
from apps.academics.models import AcademicYear, SchoolClass
from apps.accounts.models import MembershipRole, Role, SchoolMembership, User
from apps.core.models import School
from apps.core.services import FirstAdmin, SchoolProvisioningService
from apps.gradebook import services as gradebook
from apps.people import services as people
from apps.people.models import Student
from apps.scheduling import services as scheduling
from apps.scheduling.models import TeachingSession

if settings.SETTINGS_MODULE != "config.settings.test":
    raise SystemExit("The E2E fixture only runs against the TEST settings / database.")
PASSWORD = os.environ.get("DEMO_PASSWORD") or ""
if not PASSWORD:
    raise SystemExit("DEMO_PASSWORD is required (environment only).")

admin = SchoolMembership.objects.select_related("school").get(user__username=os.environ.get("E2E_USER", "demo.admin"))
school = admin.school
year = AcademicYear.objects.get(school=school, is_current=True)
klass = SchoolClass.objects.get(school=school, academic_year=year, name="6e A")
other_class = SchoolClass.objects.get(school=school, academic_year=year, name="3e B")
tomorrow = timezone.localdate() + timedelta(days=1)
suffix = uuid.uuid4().hex[:5].upper()


def member(target_school, role, first, last):
    login = f"{first}.{last}.{suffix}@e2e.test".lower()
    user = User.objects.create_user(username=login, email=login, first_name=first, last_name=f"{last}{suffix}")
    user.set_password(PASSWORD)
    user.save(update_fields=["password"])
    membership = SchoolMembership.objects.create(
        school=target_school, user=user, status="ACTIVE", joined_at=timezone.now()
    )
    MembershipRole.objects.create(membership=membership, role=Role.objects.get(code=role))
    return membership


# --- teacher of 6e A, a session tomorrow ------------------------------------------------
category = academics.create_category(school, actor=admin, code=f"XC{suffix}", name=f"Catégorie E2E {suffix}")
subject = academics.create_subject(
    school, actor=admin, code=f"XS{suffix}", name=f"Éveil E2E {suffix}", category=category
)
teacher_member = member(school, "TEACHER", "Prof", "Integration")
employee = people.create_employee(teacher_member, employee_number=f"EX-{suffix}", employee_type="TEACHER")
teacher = people.create_teacher(employee, pedagogical_category=category, primary_subject=subject)
course = gradebook.create_course(klass, subject, teacher, actor=admin, coefficient=Decimal("1"))
scheduling.create_slot(
    course,
    actor=admin,
    weekday=tomorrow.isoweekday(),
    start_time=time(17),
    end_time=time(18),
    effective_from=tomorrow,
)
scheduling.generate_sessions(school, actor=admin, date_from=tomorrow, date_to=tomorrow, school_class=klass)
session = TeachingSession.objects.filter(course=course).order_by("scheduled_start").first()
if session is None:
    raise SystemExit("No session generated tomorrow (school break?): rerun on another day.")

# --- guardian and staff of DEMO -----------------------------------------------------------
guardian = member(school, "GUARDIAN", "Gardien", "Integration")
people.create_guardian(guardian, guardian_number=f"GX-{suffix}")
staff_member = member(school, "STAFF", "Agent", "Integration")
staff_employee = people.create_employee(staff_member, employee_number=f"ESX-{suffix}", employee_type="STAFF")
people.create_staff(staff_employee, staff_number=f"PSX-{suffix}")

# --- TEST01: the other school (created once, its E2E administrator reset each run) -------
other_login = "test01.e2e.admin"
other = School.objects.filter(code="TEST01").first()
if other is None:
    other = (
        SchoolProvisioningService()
        .provision(
            code="TEST01",
            name="École de test 01",
            city="Yaoundé",
            address="E2E",
            admin=FirstAdmin(other_login, f"{other_login}@e2e.test", "Admin", "Test01", PASSWORD),
        )
        .school
    )
other_admin = SchoolMembership.objects.filter(school=other, user__username=other_login).first()
if other_admin is None:
    other_admin = member(other, "SUPER_ADMIN", "Admin", "Test01")
    other_admin.user.username = other_login
    other_admin.user.save(update_fields=["username"])
else:
    other_admin.user.set_password(PASSWORD)
    other_admin.user.save(update_fields=["password"])

students = {s.student_number: str(s.pk) for s in Student.objects.filter(school=school)}
print(
    json.dumps(
        {
            "school": school.code,
            "class_6a": str(klass.pk),
            "class_3b": str(other_class.pk),
            "s1": students["DEMO-2026-001"],
            "s4": students["DEMO-2026-004"],
            "teacher_login": teacher_member.user.email,
            "teacher_member": str(teacher_member.pk),
            "session": str(session.pk),
            "guardian_login": guardian.user.email,
            "staff_login": staff_member.user.email,
            "other_school": other.code,
            "other_admin_login": other_login,
        }
    )
)
