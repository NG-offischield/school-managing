"""E2E fixture of the parent journey (TEST database only).

The opt-in live test of the parent app (mobile/apps/parent/test/live_test.dart)
plays the whole journey through the API: registration, approval, link
request, identity check, pupil's designation, approval, then the child's
attendance, planning, finance, report card, notification and messages. What
has no API (academic periods and their closing, the school's own setup) is
prepared here, in the E2E user's school, with the domain services:

    current year (the one containing today: reused, or created and made current)
    level, class "E2E-PAR-<suffix>" with a room, a subject, a teacher (no password),
    a course with two weekly slots TODAY and the generated sessions of the week,
    the child "Enfant E2E" (+ a second pupil of the same class: isolation), both enrolled,
    an invoice for the child (fee type E2E-PAR-<suffix>),
    a CLOSED period of the year (report cards can be validated).

    docker exec -e E2E_USER=e2eadmin <test container> python manage.py shell \
        -c "exec(open('tools/e2e_parent_fixture.py').read())"

Prints ONE line of JSON for the live test. Refuses to run outside
config.settings.test.
"""

import json
import os
import uuid
from datetime import date, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from apps.academics import services as academics
from apps.academics.models import AcademicPeriod, AcademicYear, AcademicYearStatus
from apps.accounts.models import MembershipRole, Role, RoleCode, SchoolMembership, User
from apps.finance import services as finance
from apps.gradebook import services as gradebook
from apps.people import services as people
from apps.scheduling import services as scheduling

if settings.SETTINGS_MODULE != "config.settings.test":
    raise SystemExit("The E2E fixture only runs against the TEST settings / database.")

admin = SchoolMembership.objects.select_related("school").get(user__username=os.environ.get("E2E_USER", "e2eadmin"))
school = admin.school
today = timezone.localdate()
suffix = uuid.uuid4().hex[:5].upper()

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

level = academics.create_level(school, actor=admin, code=f"P{suffix}", name=f"Niveau parent {suffix}", order_index=95)
room = scheduling.create_room(school, actor=admin, code=f"RP{suffix}", name=f"Salle parent {suffix}")
klass = academics.create_class(
    school, actor=admin, name=f"E2E-PAR-{suffix}", level=level, academic_year=year, main_room=room
)
category = academics.create_category(school, actor=admin, code=f"PC{suffix}", name=f"Catégorie parent {suffix}")
subject = academics.create_subject(
    school, actor=admin, code=f"PS{suffix}", name=f"Mathématiques {suffix}", category=category
)

user = User.objects.create_user(
    username=f"prof.parent.{suffix.lower()}@e2e.test",
    email=f"prof.parent.{suffix.lower()}@e2e.test",
    first_name="Prof",
    last_name=f"Parent{suffix}",
)
user.set_unusable_password()
user.save(update_fields=["password"])
member = SchoolMembership.objects.create(school=school, user=user, status="ACTIVE", joined_at=timezone.now())
MembershipRole.objects.create(membership=member, role=Role.objects.get(code=RoleCode.TEACHER))
employee = people.create_employee(member, employee_number=f"EP-{suffix}", employee_type="TEACHER")
teacher = people.create_teacher(employee, pedagogical_category=category, primary_subject=subject)
course = gradebook.create_course(klass, subject, teacher, actor=admin, coefficient=Decimal("4"))

for start_hour in (7, 15):
    scheduling.create_slot(
        course,
        actor=admin,
        weekday=today.isoweekday(),
        start_time=time(start_hour),
        end_time=time(start_hour + 2),
        effective_from=today,
    )
scheduling.generate_sessions(
    school, actor=admin, date_from=today, date_to=today + timedelta(days=6), school_class=klass
)

child_dob = date(2014, 4, 2)
child = people.create_student(
    school,
    student_number=f"E2E-PAR-{suffix}",
    registration_number=f"E2E-PAR-{suffix}",
    first_name="Enfant",
    last_name=f"E2E{suffix}",
    date_of_birth=child_dob,
    sex="F",
)
other = people.create_student(
    school,
    student_number=f"E2E-OTH-{suffix}",
    registration_number=f"E2E-OTH-{suffix}",
    first_name="Autre",
    last_name=f"Eleve{suffix}",
    date_of_birth=date(2014, 6, 9),
    sex="M",
)
for pupil in (child, other):
    people.enroll_student(pupil, klass, enrollment_date=max(year.start_date, today - timedelta(days=1)))

fee = finance.create_fee_type(school, actor=admin, code=f"E2E-PAR-{suffix}", name="Scolarité (E2E parent)")
finance.issue_invoice(
    child, actor=admin, due_date=today + timedelta(days=30), lines=[{"fee_type": fee, "unit_price": "75000"}]
)

# A closed period of the year: report cards of a closed period can be validated.
period = (
    AcademicPeriod.objects.filter(school=school, academic_year=year, parent_period__isnull=True)
    .order_by("start_date")
    .first()
)
if period is None:
    period = academics.create_period(
        year,
        name="Trimestre E2E",
        period_type="TRIMESTER",
        order_index=1,
        start_date=year.start_date,
        end_date=min(year.end_date, year.start_date + timedelta(days=100)),
    )
gradebook.close_period(period, actor=admin)

print(
    json.dumps(
        {
            "student_number": child.student_number,
            "date_of_birth": child_dob.isoformat(),
            "child_id": str(child.pk),
            "other_student_id": str(other.pk),
            "class_id": str(klass.pk),
            "class_name": klass.name,
            "period_id": str(period.pk),
            "teacher_member": str(member.pk),
            "school_code": school.code,
        }
    )
)
