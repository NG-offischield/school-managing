from django.apps import AppConfig


class FinanceConfig(AppConfig):
    """Fees, invoices, payments, refunds, simulated wallets and treasury
    (spec 4.9, ADR 0013)."""

    name = "apps.finance"
    label = "finance"
    verbose_name = "Finance"
