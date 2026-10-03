"""Django admin registrations — developer tooling only."""

from django.contrib import admin

from .models import (
    ScheduleChange,
    ScheduleSlot,
    SchoolBreak,
    TeacherAvailability,
    TeacherAvailabilityException,
    TeachingSession,
)


@admin.register(ScheduleChange)
class ScheduleChangeAdmin(admin.ModelAdmin):
    list_display = ("changed_at", "change_type", "school_class", "notification_status")
    list_filter = ("change_type", "notification_status")

    # Immutable history (also enforced by a PostgreSQL trigger).
    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


for model in (ScheduleSlot, TeachingSession, TeacherAvailability, TeacherAvailabilityException, SchoolBreak):
    admin.site.register(model)
