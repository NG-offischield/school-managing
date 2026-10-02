"""Domain services for the tenant core.

Business operations live in services rather than in views or model.save():
the same rule then applies whether the call comes from the API, the admin
desktop, a management command or a test.
"""

from dataclasses import dataclass

from django.contrib.auth import password_validation
from django.db import transaction
from django.utils import timezone

from .models import School, SchoolBranding, SchoolConfiguration


@transaction.atomic
def create_school(**school_fields) -> School:
    """Create a school together with its configuration and branding.

    Atomic: a school must never exist without its configuration row, otherwise
    later features reading `school.configuration` would crash.
    """
    school = School.objects.create(**school_fields)
    SchoolConfiguration.objects.create(school=school)
    SchoolBranding.objects.create(school=school)
    return school


@dataclass(frozen=True)
class FirstAdmin:
    """The first administrator of a newly provisioned school."""

    username: str
    email: str
    first_name: str
    last_name: str
    password: str  # raw, validated then hashed; never stored nor logged


@dataclass(frozen=True)
class ProvisionedSchool:
    school: School
    admin_membership: object  # accounts.SchoolMembership


class SchoolProvisioningService:
    """Creates a complete, ready-to-use tenant: school + configuration +
    branding + first SUPER_ADMIN (ADR 0006).

    It is the single code path for creating a school with its administrator.
    Today its only caller is `manage.py bootstrap_school` (first school of an
    installation). Later, the multi-tenant control plane (spec §4,
    SchoolInstallation — out of V1 scope) will call it to add further schools.

    Deliberately NOT exposed through any HTTP endpoint: creating schools is a
    platform operation, not a school-level action. Authorisation is the
    caller's responsibility (shell access today, control-plane permissions
    tomorrow); this service enforces data integrity only.
    """

    @transaction.atomic
    def provision(self, *, code, name, city, address, admin: FirstAdmin, **school_fields) -> ProvisionedSchool:
        # Imported here: accounts depends on core (FKs to School), not the
        # reverse; keeping this import local preserves that direction at
        # module-import time.
        from apps.accounts.models import (
            MembershipRole,
            MembershipStatus,
            Role,
            RoleCode,
            SchoolMembership,
            User,
        )

        user = User(
            username=admin.username,
            email=admin.email,
            first_name=admin.first_name,
            last_name=admin.last_name,
            # Lets the first admin also open the developer Django admin.
            is_staff=True,
            is_superuser=True,
        )
        # Validate before writing anything: a weak password leaves no data.
        password_validation.validate_password(admin.password, user)
        user.set_password(admin.password)

        school = create_school(code=code, name=name, city=city, address=address, **school_fields)
        # Initial academic catalogue (categories, /20 /100 /60 scales), editable later.
        from apps.academics.services import seed_default_categories, seed_default_grading_scales

        seed_default_categories(school)
        seed_default_grading_scales(school)
        user.save()
        membership = SchoolMembership.objects.create(
            school=school,
            user=user,
            status=MembershipStatus.ACTIVE,
            joined_at=timezone.now(),
            is_primary_school=not user.memberships.filter(is_primary_school=True).exists(),
        )
        # System roles exist from migration accounts.0002.
        MembershipRole.objects.create(membership=membership, role=Role.objects.get(code=RoleCode.SUPER_ADMIN))
        return ProvisionedSchool(school=school, admin_membership=membership)
