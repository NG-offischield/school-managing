"""Employees, staff with several functions (and history), guardians."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.people import services
from apps.people.models import EmployeeProfile, EmployeeType, StaffFunctionAssignment

from .conftest import DB
from .factories import EmployeeFactory, SchoolFactory, StaffFunctionFactory, admin_of, member_with_role

pytestmark = DB


@pytest.fixture
def staff(school):
    return services.create_staff(EmployeeFactory(school=school, employee_type=EmployeeType.STAFF), staff_number="P-01")


@pytest.mark.parametrize(
    "field,value", [("employee_type", "VOLUNTEER"), ("employment_status", "FIRED"), ("base_salary", -1)]
)
def test_employee_check_constraints(school, field, value):
    employee = EmployeeFactory(school=school)
    with pytest.raises(IntegrityError), transaction.atomic():
        EmployeeProfile.objects.filter(pk=employee.pk).update(**{field: value})


def test_staff_requires_staff_employee(school):
    teacher_employee = EmployeeFactory(school=school, employee_type=EmployeeType.TEACHER)
    with pytest.raises(ValidationError):
        services.create_staff(teacher_employee, staff_number="P-02")


def test_staff_number_unique_per_school(school, staff):
    with pytest.raises(IntegrityError), transaction.atomic():
        services.create_staff(EmployeeFactory(school=school), staff_number="P-01")
    services.create_staff(EmployeeFactory(school=SchoolFactory()), staff_number="P-01")


def test_staff_holds_several_functions_at_once(school, staff):
    admin = admin_of(school)
    for code in ("SECRETARY", "LIBRARIAN"):
        services.assign_staff_function(staff, StaffFunctionFactory(school=school, code=code), actor=admin)
    assert sorted(a.function.code for a in staff.function_assignments.filter(active=True)) == ["LIBRARIAN", "SECRETARY"]


def test_function_history_is_kept(school, staff):
    admin, bursar = admin_of(school), StaffFunctionFactory(school=school, code="BURSAR")
    first = services.assign_staff_function(staff, bursar, actor=admin)
    with pytest.raises(IntegrityError), transaction.atomic():
        services.assign_staff_function(staff, bursar, actor=admin)  # same function twice at the same time
    services.end_staff_function(first, actor=admin)
    services.assign_staff_function(staff, bursar, actor=admin)  # again later: allowed
    rows = StaffFunctionAssignment.objects.filter(staff=staff, function=bursar)
    assert (rows.count(), rows.filter(active=True).count()) == (2, 1)


def test_assignment_active_flag_and_end_date_agree_postgresql(school, staff):
    a = services.assign_staff_function(staff, StaffFunctionFactory(school=school), actor=admin_of(school))
    with pytest.raises(IntegrityError), transaction.atomic():
        StaffFunctionAssignment.objects.filter(pk=a.pk).update(active=False)  # no ended_at
    with pytest.raises(IntegrityError), transaction.atomic():
        StaffFunctionAssignment.objects.filter(pk=a.pk).update(ended_at=a.assigned_at - timezone.timedelta(days=1))


def test_function_assignment_requires_admin_of_the_school(school, staff):
    function = StaffFunctionFactory(school=school)
    for actor in (member_with_role(school, "STAFF"), admin_of(SchoolFactory())):
        with pytest.raises(PermissionDenied):
            services.assign_staff_function(staff, function, actor=actor)


def test_function_of_another_school_is_refused_by_postgresql(school, staff):
    with pytest.raises(IntegrityError), transaction.atomic():
        StaffFunctionAssignment.objects.create(
            school=school, staff=staff, function=StaffFunctionFactory(school=SchoolFactory())
        )


# --- Guardians -----------------------------------------------------------------------


def test_guardian_attached_to_school_through_membership(school):
    guardian = services.create_guardian(member_with_role(school, "GUARDIAN"), guardian_number="G-01")
    assert guardian.school == guardian.membership.school == school
    assert guardian.membership.role_codes() == {"GUARDIAN"}


def test_guardian_requires_guardian_role_and_unique_number(school):
    with pytest.raises(ValidationError):
        services.create_guardian(member_with_role(school, "STAFF"), guardian_number="G-01")
    services.create_guardian(member_with_role(school, "GUARDIAN"), guardian_number="G-01")
    with pytest.raises(IntegrityError), transaction.atomic():
        services.create_guardian(member_with_role(school, "GUARDIAN"), guardian_number="G-01")
