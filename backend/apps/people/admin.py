"""Django admin registrations — developer tooling only."""

from django.contrib import admin

from . import models as m


@admin.register(m.Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("student_number", "last_name", "first_name", "school", "status")
    list_filter = ("school", "status")
    search_fields = ("student_number", "registration_number", "last_name", "first_name")

    def has_delete_permission(self, request, obj=None):
        # Students are archived, never deleted (services.archive_student).
        return False


@admin.register(m.StudentEnrollment)
class StudentEnrollmentAdmin(admin.ModelAdmin):
    list_display = ("student", "academic_year", "school_class", "status", "promotion_status")
    list_filter = ("school", "academic_year", "status", "promotion_status")


@admin.register(m.ParentStudent)
class ParentStudentAdmin(admin.ModelAdmin):
    list_display = ("parent", "student", "relationship_type", "identity_verified", "is_primary_contact", "active")
    list_filter = ("school", "identity_verified")


@admin.register(m.CompatibilityOverride)
class CompatibilityOverrideAdmin(admin.ModelAdmin):
    list_display = ("teacher", "subject", "level", "approved_by", "created_at", "expires_at")

    # The override row IS the audit record: read-only once created.
    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


for model in (
    m.ParentProfile,
    m.EmployeeProfile,
    m.TeacherProfile,
    m.TeacherSubjectQualification,
    m.StaffProfile,
    m.StaffFunction,
    m.StaffFunctionAssignment,
    m.GuardianProfile,
):
    admin.site.register(model)
