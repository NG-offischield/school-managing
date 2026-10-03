"""Django admin registrations — developer tooling only.

Payroll data is read-only here: calculations, approvals, payments and
corrections go through the services (audited, and guarded by triggers).
"""

from django.contrib import admin

from .models import (
    PayrollLine,
    PayrollPeriod,
    PayrollSettlement,
    SalaryAdjustment,
    StaffCompensationProfile,
    StaffPayroll,
    TeacherCompensationProfile,
    TeacherPayroll,
    TeacherSessionCheckIn,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


for model in (
    TeacherSessionCheckIn,
    TeacherCompensationProfile,
    StaffCompensationProfile,
    PayrollPeriod,
    TeacherPayroll,
    StaffPayroll,
    PayrollLine,
    PayrollSettlement,
    SalaryAdjustment,
):
    admin.site.register(model, ReadOnlyAdmin)
