"""Django admin registrations — developer tooling only (see config/urls.py)."""

from django.contrib import admin

from .models import School, SchoolBranding, SchoolConfiguration


class SchoolConfigurationInline(admin.StackedInline):
    model = SchoolConfiguration
    can_delete = False


class SchoolBrandingInline(admin.StackedInline):
    model = SchoolBranding
    can_delete = False


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "city", "status")
    list_filter = ("status",)
    search_fields = ("code", "name")
    inlines = [SchoolConfigurationInline, SchoolBrandingInline]

    def has_delete_permission(self, request, obj=None):
        # Schools are archived, never deleted (history must be preserved).
        return False
