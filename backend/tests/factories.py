"""Test data factories (factory_boy).

Factories build valid objects with sensible defaults, so each test only spells
out the fields it actually cares about.
"""

from datetime import date

import factory
from django.utils import timezone

from apps.academics.models import (
    AcademicYear,
    Level,
    PedagogicalCategory,
    SchoolClass,
    Subject,
    SubjectType,
)
from apps.accounts.models import MembershipRole, MembershipStatus, Role, SchoolMembership, User
from apps.core.services import create_school
from apps.people.models import (
    EmployeeProfile,
    EmployeeType,
    ParentProfile,
    Sex,
    StaffFunction,
    Student,
)

DEFAULT_PASSWORD = "Str0ng-Test-Passw0rd!"


class SchoolFactory(factory.Factory):
    """Goes through the `create_school` service so configuration and branding
    rows always exist, exactly like in production."""

    class Meta:
        model = dict

    code = factory.Sequence(lambda n: f"SCH{n:03d}")
    name = factory.Sequence(lambda n: f"École {n}")
    city = "Douala"
    address = "Rue de l'École"

    @classmethod
    def _create(cls, model_class, **kwargs):
        from apps.academics.services import seed_default_grading_scales

        school = create_school(**kwargs)
        # Like SchoolProvisioningService: every school has /20 (default), /100, /60.
        seed_default_grading_scales(school)
        return school


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda u: f"{u.username}@example.cm")
    first_name = "Test"
    last_name = "User"
    password = DEFAULT_PASSWORD

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        # Go through the manager so the password is hashed like in real life.
        return model_class.objects.create_user(*args, **kwargs)


class MembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SchoolMembership

    school = factory.SubFactory(SchoolFactory)
    user = factory.SubFactory(UserFactory)
    status = MembershipStatus.ACTIVE
    joined_at = factory.LazyFunction(timezone.now)


def grant_role(membership, code):
    """Assign one of the system roles seeded by migration."""
    return MembershipRole.objects.create(membership=membership, role=Role.objects.get(code=code))


def member_with_role(school, code, **membership_fields):
    """An ACTIVE membership of `school` holding role `code`."""
    membership = MembershipFactory(school=school, **membership_fields)
    grant_role(membership, code)
    return membership


# =============================================================================
# Academic structure
# =============================================================================


class AcademicYearFactory(factory.django.DjangoModelFactory):
    """Consecutive, non-overlapping years: 2001-2002, 2002-2003... per sequence."""

    class Meta:
        model = AcademicYear

    school = factory.SubFactory(SchoolFactory)
    name = factory.Sequence(lambda n: f"{2001 + n}-{2002 + n}")
    start_date = factory.Sequence(lambda n: date(2001 + n, 9, 1))
    end_date = factory.Sequence(lambda n: date(2002 + n, 7, 31))


class LevelFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Level

    school = factory.SubFactory(SchoolFactory)
    code = factory.Sequence(lambda n: f"LVL{n}")
    name = factory.Sequence(lambda n: f"Niveau {n}")
    order_index = factory.Sequence(lambda n: n)


class CategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PedagogicalCategory

    school = factory.SubFactory(SchoolFactory)
    code = factory.Sequence(lambda n: f"CAT{n}")
    name = factory.Sequence(lambda n: f"Catégorie {n}")


class SubjectFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Subject

    school = factory.SubFactory(SchoolFactory)
    code = factory.Sequence(lambda n: f"SUBJ{n}")
    name = factory.Sequence(lambda n: f"Matière {n}")
    category = factory.SubFactory(CategoryFactory, school=factory.SelfAttribute("..school"))
    subject_type = SubjectType.THEORETICAL


class SchoolClassFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SchoolClass

    school = factory.SubFactory(SchoolFactory)
    name = factory.Sequence(lambda n: f"Classe {n}")
    level = factory.SubFactory(LevelFactory, school=factory.SelfAttribute("..school"))
    academic_year = factory.SubFactory(AcademicYearFactory, school=factory.SelfAttribute("..school"))


# =============================================================================
# People
# =============================================================================


class StudentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Student

    school = factory.SubFactory(SchoolFactory)
    student_number = factory.Sequence(lambda n: f"MAT{n:05d}")
    registration_number = factory.Sequence(lambda n: f"REG{n:05d}")
    first_name = "Awa"
    last_name = factory.Sequence(lambda n: f"Élève{n}")
    date_of_birth = date(2012, 5, 4)
    sex = Sex.FEMALE


class ParentFactory(factory.django.DjangoModelFactory):
    """ParentProfile on a membership holding the PARENT role."""

    class Meta:
        model = ParentProfile

    school = factory.SubFactory(SchoolFactory)
    membership = factory.LazyAttribute(lambda o: member_with_role(o.school, "PARENT"))


class EmployeeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = EmployeeProfile

    school = factory.SubFactory(SchoolFactory)
    employee_type = EmployeeType.STAFF
    membership = factory.LazyAttribute(lambda o: member_with_role(o.school, o.employee_type))
    employee_number = factory.Sequence(lambda n: f"EMP{n:04d}")


class StaffFunctionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StaffFunction

    school = factory.SubFactory(SchoolFactory)
    code = factory.Sequence(lambda n: f"FUNC{n}")
    name = factory.Sequence(lambda n: f"Fonction {n}")


def make_teacher(school, *, category=None, primary_subject=None, number=None):
    """A complete teacher through the real service (creates the primary
    subject qualification too)."""
    from apps.people.services import create_teacher

    category = category or CategoryFactory(school=school)
    primary_subject = primary_subject or SubjectFactory(school=school, category=category)
    employee = EmployeeFactory(
        school=school, employee_type=EmployeeType.TEACHER, **({"employee_number": number} if number else {})
    )
    return create_teacher(employee, pedagogical_category=category, primary_subject=primary_subject)


def admin_of(school):
    return member_with_role(school, "ADMIN")
