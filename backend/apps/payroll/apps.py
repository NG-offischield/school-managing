from django.apps import AppConfig


class PayrollConfig(AppConfig):
    """Teachers' and staff remuneration: session validation, rates, periods,
    payrolls, corrections; payment through Finance (spec 4.8, ADR 0014)."""

    name = "apps.payroll"
    label = "payroll"
    verbose_name = "Paie"
