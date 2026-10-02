from django.apps import AppConfig


class PeopleConfig(AppConfig):
    """People of a school: students and their enrollments, parents, teachers,
    staff, guardians (spec §4.3 and §4.4)."""

    name = "apps.people"
    label = "people"
    verbose_name = "Personnes"
