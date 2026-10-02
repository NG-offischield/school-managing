"""Abstract base models applying the conventions of spec §3."""

import uuid

from django.db import models
from django.utils import timezone


class BaseModel(models.Model):
    """UUID primary key + creation/update timestamps.

    Why UUIDs: sequential integer IDs leak information (how many students,
    invoices...) and are guessable in URLs (`/students/42/` -> try 43). Human
    friendly identifiers such as matricules or invoice numbers are stored in
    separate business fields, never used as primary keys.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # DateTimeField + USE_TZ=True -> PostgreSQL `timestamptz`.
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TenantQuerySet(models.QuerySet):
    """Queryset helper for rows owned by a school (tenant)."""

    def for_school(self, school):
        # Every tenant-scoped query must carry the school context (spec §9).
        # Centralising the filter here makes forgetting it easy to spot in review.
        return self.filter(school=school)


class TenantModel(BaseModel):
    """Base for rows that belong to exactly one school.

    V1 runs a single school, but storing `school_id` directly on tenant rows
    means adding a second school later is a data operation, not a rewrite
    (spec §2, §3). PROTECT: a school with history can never be deleted by
    accident; it is archived through its status instead.
    """

    school = models.ForeignKey("core.School", on_delete=models.PROTECT, related_name="+")

    objects = TenantQuerySet.as_manager()

    class Meta:
        abstract = True
