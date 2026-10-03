from django.apps import AppConfig


class AttendanceConfig(AppConfig):
    """Student attendance and annual QR codes (spec §4.5, ADR 0011)."""

    name = "apps.attendance"
    label = "attendance"
    verbose_name = "Présences et QR"
