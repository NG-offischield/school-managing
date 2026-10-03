"""Django admin registrations — developer tooling only."""

from django.contrib import admin

from .models import AttendancePolicy, Convocation, GuardianScan, StudentDailyAttendance, StudentQRCode


@admin.register(GuardianScan)
class GuardianScanAdmin(admin.ModelAdmin):
    list_display = ("scanned_at", "result", "student", "scanned_by")
    list_filter = ("school", "result")

    # Immutable log (also enforced by a PostgreSQL trigger).
    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StudentQRCode)
class StudentQRCodeAdmin(admin.ModelAdmin):
    list_display = ("student", "academic_year", "version", "status", "issued_at")
    list_filter = ("school", "status")
    exclude = ("token",)  # the token is a credential-like secret


for model in (AttendancePolicy, StudentDailyAttendance, Convocation):
    admin.site.register(model)
