"""E2E fixture for the report-card document (TEST database only).

The opt-in desktop E2E (desktop/tests/test_live.py) generates a report-card
PDF. Academic periods have no API (they are set up with the school), so this
script prepares, idempotently, in the E2E user's school:

    year "2199-2200" (ACTIVE, never current; the E2E's own years start in 2200)
    level "E2EDOC", class "E2E-DOCS", one pupil "E2E Bulletin" enrolled,
    period "T1 E2E" (TRIMESTER) inside that year.

The desktop then computes the report cards through the EXISTING gradebook
API and generates the document through the EXISTING Document registry.

    docker exec -e E2E_USER=e2eadmin <test container> python manage.py shell \
        -c "exec(open('tools/e2e_documents_fixture.py').read())"

Refuses to run outside config.settings.test.
"""

import os
from datetime import date

from django.conf import settings

from apps.academics import services as academics
from apps.academics.models import AcademicPeriod, AcademicYear, AcademicYearStatus, Level, SchoolClass
from apps.accounts.models import SchoolMembership
from apps.people import services as people
from apps.people.models import Student, StudentEnrollment

if settings.SETTINGS_MODULE != "config.settings.test":
    raise SystemExit("The E2E fixture only runs against the TEST settings / database.")

admin = SchoolMembership.objects.select_related("school").get(user__username=os.environ.get("E2E_USER", "e2eadmin"))
school = admin.school
year = AcademicYear.objects.filter(school=school, name="2199-2200").first() or academics.create_academic_year(
    school, name="2199-2200", start_date=date(2199, 9, 1), end_date=date(2200, 7, 31), status=AcademicYearStatus.ACTIVE
)
level = Level.objects.filter(school=school, code="E2EDOC").first() or academics.create_level(
    school, actor=admin, code="E2EDOC", name="Niveau E2E documents", cycle="E2E", order_index=99
)
klass = SchoolClass.objects.filter(school=school, academic_year=year, name="E2E-DOCS").first()
if klass is None:
    klass = academics.create_class(school, actor=admin, name="E2E-DOCS", level=level, academic_year=year)
student = Student.objects.filter(school=school, student_number="E2E-BULL").first() or people.create_student(
    school,
    student_number="E2E-BULL",
    registration_number="E2E-BULL",
    first_name="Bulletin",
    last_name="E2E",
    date_of_birth=date(2012, 5, 4),
    sex="F",
)
if not StudentEnrollment.objects.filter(student=student, academic_year=year).exists():
    people.enroll_student(student, klass, enrollment_date=date(2199, 9, 2))
period = AcademicPeriod.objects.filter(school=school, academic_year=year, name="T1 E2E").first()
if period is None:
    period = academics.create_period(
        year,
        name="T1 E2E",
        period_type="TRIMESTER",
        order_index=1,
        start_date=date(2199, 9, 1),
        end_date=date(2199, 12, 20),
    )
print("e2e-documents-fixture", klass.pk, period.pk, student.pk)
