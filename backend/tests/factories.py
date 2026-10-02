"""Test data factories (factory_boy).

Factories build valid objects with sensible defaults, so each test only spells
out the fields it actually cares about.
"""

import factory
from django.utils import timezone

from apps.accounts.models import MembershipRole, MembershipStatus, Role, SchoolMembership, User
from apps.core.services import create_school

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
        return create_school(**kwargs)


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
