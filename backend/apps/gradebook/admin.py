"""Django admin registrations — developer tooling only."""

from django.contrib import admin

from .models import Assessment, ClassPrincipalAssignment, Course, Grade, GradeChangeLog, ReportCard, ReportCardLine


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("subject", "school_class", "teacher", "academic_year", "coefficient", "active")
    list_filter = ("school", "academic_year")


@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    list_display = ("name", "course", "academic_period", "max_score", "weight", "status")
    list_filter = ("school", "status")


@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ("student", "assessment", "score", "max_score", "entered_at")


@admin.register(GradeChangeLog)
class GradeChangeLogAdmin(admin.ModelAdmin):
    list_display = ("grade", "old_score", "new_score", "changed_by", "changed_at")

    # Immutable history (also enforced by a PostgreSQL trigger).
    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ReportCardLineInline(admin.TabularInline):
    model = ReportCardLine
    extra = 0


@admin.register(ReportCard)
class ReportCardAdmin(admin.ModelAdmin):
    list_display = ("student", "academic_period", "status", "general_average", "rank")
    list_filter = ("school", "status")
    inlines = [ReportCardLineInline]


@admin.register(ClassPrincipalAssignment)
class ClassPrincipalAssignmentAdmin(admin.ModelAdmin):
    list_display = ("school_class", "teacher", "start_date", "end_date", "active")
    list_filter = ("school", "active")
