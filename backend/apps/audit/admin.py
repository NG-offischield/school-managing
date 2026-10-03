from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "layer", "action", "entity_type", "entity_id", "actor")
    list_filter = ("layer", "action", "entity_type")

    # Append-only (also enforced by a PostgreSQL trigger).
    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
