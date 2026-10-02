from django.apps import AppConfig


class AcademicsConfig(AppConfig):
    """Academic structure of a school: years, periods, levels, subjects,
    pedagogical categories, compatibility rules and classes (spec §4.4)."""

    name = "apps.academics"
    label = "academics"
    verbose_name = "Structure académique"
