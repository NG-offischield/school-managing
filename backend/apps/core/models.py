"""Tenant core models (spec §4.1).

`School` is the root tenant. V1 operates a single school, but every
school-owned row points to it so that more schools can be added later
without redesigning the domain.
"""

from datetime import time
from decimal import Decimal

from django.db import models
from django.db.models import Q

from common.models import BaseModel


class SchoolStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    SUSPENDED = "SUSPENDED", "Suspendue"
    ARCHIVED = "ARCHIVED", "Archivée"


# ISO-4217 codes accepted for school accounting. XAF (Central African CFA
# franc) is the V1 default; the list is short on purpose and can grow.
SUPPORTED_CURRENCIES = ["XAF", "XOF", "EUR", "USD", "NGN", "GHS"]


class School(BaseModel):
    """Root tenant. Never deleted (PROTECT everywhere): archived via `status`."""

    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=200, db_index=True)
    legal_name = models.CharField(max_length=255, blank=True, null=True)
    short_name = models.CharField(max_length=80, blank=True, null=True)
    logo = models.ImageField(upload_to="schools/logos/", blank=True, null=True)
    crest = models.ImageField(upload_to="schools/crests/", blank=True, null=True)
    address = models.TextField()
    city = models.CharField(max_length=120)
    country = models.CharField(max_length=80, default="Cameroon")
    phone = models.CharField(max_length=40, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    website = models.URLField(blank=True, null=True)
    timezone = models.CharField(max_length=64, default="Africa/Douala")
    currency = models.CharField(max_length=3, default="XAF")
    description = models.TextField(blank=True, null=True)
    mission = models.TextField(blank=True, null=True)
    vision = models.TextField(blank=True, null=True)
    history = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=SchoolStatus.choices, default=SchoolStatus.ACTIVE, db_index=True)

    class Meta:
        ordering = ["name"]
        # CHECK constraints are enforced by PostgreSQL itself: even a buggy
        # script or a raw SQL update cannot store an invalid status/currency.
        constraints = [
            models.CheckConstraint(condition=Q(status__in=SchoolStatus.values), name="school_status_valid"),
            models.CheckConstraint(condition=Q(currency__in=SUPPORTED_CURRENCIES), name="school_currency_supported"),
        ]

    def __str__(self):
        return self.name


class SchoolConfiguration(BaseModel):
    """Business settings administrators can tune (thresholds, limits...).

    Values are read by later phases (attendance alerts, report cards...). They
    live in the database, not in settings.py, because they are school policy,
    not deployment configuration.
    """

    school = models.OneToOneField(School, on_delete=models.PROTECT, related_name="configuration")
    # Attendance (spec §15: parent alerts use configured severity thresholds).
    default_late_threshold_minutes = models.PositiveIntegerField(default=15)
    attendance_closing_time = models.TimeField(default=time(10, 0))
    notification_absence_threshold_hours = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("10.00"))
    notification_yellow_hours = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("10.00"))
    notification_orange_hours = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("20.00"))
    notification_red_hours = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("30.00"))
    # Academics: averages below this value are flagged.
    low_average_threshold = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("8.00"))
    default_attachment_limit_mb = models.PositiveIntegerField(default=10)
    # Length of one paid teaching session ("vacation"), used by payroll.
    teacher_vacation_duration_minutes = models.PositiveIntegerField(default=120)
    # When True, every subject must belong to a pedagogical category
    # (enforced by academics.services.create_subject). Addition to spec
    # §4.1, see ADR 0008: "a subject belongs to a category when the
    # school's rule requires it".
    subject_category_required = models.BooleanField(default=True)

    class Meta:
        constraints = [
            # Alert severities must escalate: yellow <= orange <= red.
            models.CheckConstraint(
                condition=Q(notification_yellow_hours__lte=models.F("notification_orange_hours"))
                & Q(notification_orange_hours__lte=models.F("notification_red_hours")),
                name="school_config_alert_thresholds_ordered",
            ),
        ]

    def __str__(self):
        return f"Configuration — {self.school}"


class SchoolBranding(BaseModel):
    """Visual identity used on student cards, report cards and public pages."""

    school = models.OneToOneField(School, on_delete=models.PROTECT, related_name="branding")
    primary_color = models.CharField(max_length=20, default="#173B73")
    secondary_color = models.CharField(max_length=20, default="#36A2EB")
    report_background = models.FileField(upload_to="schools/branding/", blank=True, null=True)
    card_background = models.FileField(upload_to="schools/branding/", blank=True, null=True)
    font_family = models.CharField(max_length=80, blank=True, null=True)

    def __str__(self):
        return f"Branding — {self.school}"
