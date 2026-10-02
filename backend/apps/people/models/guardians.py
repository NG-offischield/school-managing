"""Guardians (gate keepers who will scan student QR codes) — spec §4.3.

Only the profile exists in this phase. QR codes, scans and attendance come
with their dedicated phase; the guardian is already attached to the school
through the standard chain User → SchoolMembership (role GUARDIAN).
"""

from django.db import models
from django.db.models import Q

from common.models import TenantModel


class GuardianStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Actif"
    SUSPENDED = "SUSPENDED", "Suspendu"
    LEFT = "LEFT", "Parti"


class GuardianProfile(TenantModel):
    """Guardian-specific data. `guardian_number` is unique per school."""

    membership = models.OneToOneField(
        "accounts.SchoolMembership", on_delete=models.PROTECT, related_name="guardian_profile"
    )
    guardian_number = models.CharField(max_length=50, db_index=True)
    status = models.CharField(
        max_length=20, choices=GuardianStatus.choices, default=GuardianStatus.ACTIVE, db_index=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["school", "guardian_number"], name="guardian_school_number_unique"),
            models.CheckConstraint(condition=Q(status__in=GuardianStatus.values), name="guardian_status_valid"),
        ]

    def __str__(self):
        return f"Gardien {self.guardian_number}"
