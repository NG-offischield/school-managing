"""Django admin registrations — developer tooling only (the real admin client
is the PySide6 desktop application)."""

from django.contrib import admin

from .models import (
    AcademicPeriod,
    AcademicYear,
    Level,
    PedagogicalCategory,
    SchoolClass,
    Subject,
    SubjectCompatibilityRule,
)


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ("name", "school", "start_date", "end_date", "status", "is_current")
    list_filter = ("school", "status")


@admin.register(AcademicPeriod)
class AcademicPeriodAdmin(admin.ModelAdmin):
    list_display = ("name", "academic_year", "parent_period", "period_type", "order_index", "status")
    list_filter = ("school", "period_type")


@admin.register(Level)
class LevelAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "cycle", "order_index", "school", "active")
    list_filter = ("school", "cycle")


@admin.register(PedagogicalCategory)
class PedagogicalCategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "school", "active")


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "category", "subject_type", "school", "active")
    list_filter = ("school", "subject_type")


@admin.register(SubjectCompatibilityRule)
class SubjectCompatibilityRuleAdmin(admin.ModelAdmin):
    list_display = ("pedagogical_category", "subject", "level", "compatible", "requires_admin_review", "priority")


@admin.register(SchoolClass)
class SchoolClassAdmin(admin.ModelAdmin):
    list_display = ("name", "level", "academic_year", "school", "active")
    list_filter = ("school", "academic_year")
