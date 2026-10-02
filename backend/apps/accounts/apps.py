from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """Identity, roles, memberships, sessions and security events (spec §4.2)."""

    name = "apps.accounts"
    label = "accounts"
    verbose_name = "Comptes & sécurité"
