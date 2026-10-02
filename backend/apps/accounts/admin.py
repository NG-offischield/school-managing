"""Django admin registrations — developer tooling only."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import MembershipRole, Role, SchoolMembership, SecurityEvent, User, UserSession


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ("username",)
    list_display = ("username", "email", "first_name", "last_name", "is_active")
    search_fields = ("username", "email", "first_name", "last_name")
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Identité", {"fields": ("first_name", "last_name", "email", "phone", "profile_photo")}),
        ("Vérifications", {"fields": ("email_verified", "phone_verified")}),
        ("Accès", {"fields": ("is_active", "is_staff", "is_superuser")}),
    )
    add_fieldsets = ((None, {"fields": ("username", "email", "first_name", "last_name", "password1", "password2")}),)
    filter_horizontal = ()
    list_filter = ("is_active", "is_staff")


class MembershipRoleInline(admin.TabularInline):
    model = MembershipRole
    fk_name = "membership"
    extra = 0


@admin.register(SchoolMembership)
class SchoolMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "school", "status", "is_primary_school")
    list_filter = ("status", "school")
    inlines = [MembershipRoleInline]


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "system_role")


@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "device", "created_at", "expires_at", "revoked_at")
    # The hash is useless to an admin and should not be displayed.
    exclude = ("refresh_token_hash",)
    readonly_fields = ("user", "device", "ip_address", "user_agent", "last_used_at", "expires_at")


@admin.register(SecurityEvent)
class SecurityEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "event_type", "severity", "user", "ip_address")
    list_filter = ("event_type", "severity")

    # Security log is append-only, even for superusers.
    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
