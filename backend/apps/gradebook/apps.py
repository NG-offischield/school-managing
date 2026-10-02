from django.apps import AppConfig


class GradebookConfig(AppConfig):
    """Academic core: courses, assessments, grades, change history and report
    cards (spec §4.4). Depends on academics (structure) and people (teachers,
    students), hence a separate app above both."""

    name = "apps.gradebook"
    label = "gradebook"
    verbose_name = "Notes et bulletins"
