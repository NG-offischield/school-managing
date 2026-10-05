from django.apps import AppConfig


class DemoConfig(AppConfig):
    """Demonstration dataset (docs/demo-data.md): no model, no migration, no
    URL. Only the `seed_demo` command, built on the domain services."""

    name = "apps.demo"
    label = "demo"
    verbose_name = "Jeu de démonstration"
