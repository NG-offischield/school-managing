"""AuditLog — who changed what, when, from what to what (spec §4.10).

Layers:
- BUSINESS: changes of business data (attendance correction, QR issuance...);
- ADMINISTRATIVE: configuration / catalogue changes (categories, subjects,
  policies...).
Security events (logins, token reuse...) keep their own table, SecurityEvent,
written on an autonomous connection (ADR 0005); the spec's SECURITY layer is
therefore served by SecurityEvent (ADR 0010).

Unlike SecurityEvent, an audit row is written IN the business transaction:
if the change is rolled back, so is its audit row — the trail never claims a
change that did not happen.

Append-only: a PostgreSQL trigger refuses DELETE and any UPDATE, except the
ON DELETE SET NULL of `school` / `actor` (history survives the referenced row).
"""

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import Q

from common.models import BaseModel


class AuditLayer(models.TextChoices):
    BUSINESS = "BUSINESS", "Métier"
    ADMINISTRATIVE = "ADMINISTRATIVE", "Administratif"


class AuditLog(BaseModel):
    school = models.ForeignKey("core.School", on_delete=models.SET_NULL, blank=True, null=True, related_name="+")
    layer = models.CharField(max_length=20, choices=AuditLayer.choices, db_index=True)
    actor = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+", db_index=True
    )
    action = models.CharField(max_length=50, db_index=True)
    entity_type = models.CharField(max_length=120, db_index=True)
    entity_id = models.UUIDField(blank=True, null=True, db_index=True)
    old_data = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    new_data = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)
    correlation_id = models.UUIDField(blank=True, null=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(layer__in=AuditLayer.values), name="audit_layer_valid"),
            models.CheckConstraint(condition=~Q(action=""), name="audit_action_required"),
        ]

    def __str__(self):
        return f"{self.action} {self.entity_type}:{self.entity_id}"
