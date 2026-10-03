from django.apps import AppConfig


class AuditConfig(AppConfig):
    """Business and administrative audit trail (spec §4.10, ADR 0010)."""

    name = "apps.audit"
    label = "audit"
    verbose_name = "Audit"
