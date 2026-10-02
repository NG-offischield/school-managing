from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Tenant core: the School and its configuration (spec §4.1)."""

    name = "apps.core"
    label = "core"
    verbose_name = "Établissement"
