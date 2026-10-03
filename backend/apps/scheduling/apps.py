from django.apps import AppConfig


class SchedulingConfig(AppConfig):
    """Timetable (recurring slots), dated teaching sessions, teacher
    availability, substitutions and planning history (spec 4.5, ADR 0012)."""

    name = "apps.scheduling"
    label = "scheduling"
    verbose_name = "Planning"
