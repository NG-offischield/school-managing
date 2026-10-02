"""Domain services for the tenant core.

Business operations live in services rather than in views or model.save():
the same rule then applies whether the call comes from the API, the admin
desktop, a management command or a test.
"""

from django.db import transaction

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
