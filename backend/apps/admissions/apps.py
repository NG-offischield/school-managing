from django.apps import AppConfig


class AdmissionsConfig(AppConfig):
    """Pre-enrollment requests and portal invitations (ADR 0032)."""

    name = "apps.admissions"
    label = "admissions"
    verbose_name = "Préinscriptions"
