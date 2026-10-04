"""Admin dashboard aggregates (ADR 0017), read-only, ADMIN / SUPER_ADMIN of
the current school. They feed the charts of the PySide6 dashboard; each one
is a separate endpoint so a chart can fail (or be empty) on its own.

    GET /admin/dashboard/attendance-trend/  ?days=14 (1..92) &end=YYYY-MM-DD
        -> {date_from, date_to, days: [{date, PRESENT, LATE, ABSENT, EXCUSED, PENDING, total}]}
           only the days that have daily attendance rows (school days);
    GET /admin/dashboard/enrollments/       ?academic_year=<uuid> (default: current year)
        -> {academic_year, academic_year_name, total,
            by_level: [{level, code, name, count}], by_class: [{class, name, level_code, count, capacity}],
            by_month: [{month: "YYYY-MM", enrolled}]}   pupils enrolled at the end of each month
    GET /admin/dashboard/activity/          ?limit=10 (1..50)
        -> [{id, at, action, entity_type, label, actor}]   administrative audit trail

Only counts and labels of configuration rows leave the server: no pupil
name, no audit payload. Why aggregates on the server: computing them in the
client would mean downloading every attendance row and enrollment.
"""

from datetime import date, timedelta

from django.db.models import Count, Q
from django.urls import path
from django.utils import timezone
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from common.permissions import ADMIN_ROLES, HasSchoolRole
from common.tenancy import scope_to_current_school
from common.views import SchoolScopedMixin


class AdminView(SchoolScopedMixin, APIView):
    permission_classes = [HasSchoolRole]
    required_roles = ADMIN_ROLES

    def int_param(self, name, default, low, high):
        raw = self.request.query_params.get(name)
        if raw in (None, ""):
            return default
        try:
            value = int(raw)
        except ValueError:
            raise serializers.ValidationError({name: ["Must be an integer."]}) from None
        if not low <= value <= high:
            raise serializers.ValidationError({name: [f"Must be between {low} and {high}."]})
        return value


class AttendanceTrend(AdminView):
    def get(self, request):
        from apps.attendance.models import DailyStatus, StudentDailyAttendance

        days = self.int_param("days", 14, 1, 92)
        raw_end = request.query_params.get("end")
        try:
            end = serializers.DateField().to_internal_value(raw_end) if raw_end else timezone.localdate()
        except serializers.ValidationError:
            raise serializers.ValidationError({"end": ["Must be a date (YYYY-MM-DD)."]}) from None
        start = end - timedelta(days=days - 1)
        rows = (
            scope_to_current_school(StudentDailyAttendance.objects.all(), request)
            .filter(date__gte=start, date__lte=end)
            .values("date", "status")
            .annotate(n=Count("id"))
        )
        by_day = {}
        for row in rows:
            day = by_day.setdefault(row["date"], {s: 0 for s in DailyStatus.values})
            day[row["status"]] = row["n"]
        series = [{"date": day, **counts, "total": sum(counts.values())} for day, counts in sorted(by_day.items())]
        return Response({"date_from": start, "date_to": end, "days": series})


def _month_ends(start, end):
    """Last day of each month from `start` to `end` (the last one capped at `end`)."""
    months, cursor = [], date(start.year, start.month, 1)
    while cursor <= end:
        following = date(cursor.year + cursor.month // 12, cursor.month % 12 + 1, 1)
        months.append(min(following - timedelta(days=1), end))
        cursor = following
    return months


class EnrollmentStats(AdminView):
    def get(self, request):
        from apps.academics.models import AcademicYear, SchoolClass
        from apps.people.models import EnrollmentStatus, StudentEnrollment

        years = scope_to_current_school(AcademicYear.objects.all(), request)
        wanted = self.uuid_param("academic_year")
        year = years.filter(pk=wanted).first() if wanted else years.filter(is_current=True).first()
        if wanted and year is None:
            from django.http import Http404

            raise Http404
        empty = {"academic_year": None, "academic_year_name": "", "total": 0, "by_level": [], "by_class": []}
        if year is None:
            return Response({**empty, "by_month": []})
        enrollments = StudentEnrollment.objects.filter(school=year.school, academic_year=year)
        active = enrollments.filter(status=EnrollmentStatus.ACTIVE)
        by_level = (
            active.values("school_class__level", "school_class__level__code", "school_class__level__name")
            .annotate(count=Count("id"))
            .order_by("school_class__level__order_index", "school_class__level__code")
        )
        counts = dict(active.values_list("school_class").annotate(n=Count("id")))
        classes = SchoolClass.objects.filter(academic_year=year, active=True).select_related("level")
        by_class = [
            {
                "class": str(c.pk),
                "name": c.name,
                "level_code": c.level.code,
                "count": counts.get(c.pk, 0),
                "capacity": c.capacity,
            }
            for c in classes.order_by("level__order_index", "name")
        ]
        by_month = []
        for month_end in _month_ends(year.start_date, min(year.end_date, timezone.localdate())):
            enrolled = enrollments.filter(enrollment_date__lte=month_end).filter(
                Q(end_date__isnull=True) | Q(end_date__gt=month_end)
            )
            by_month.append({"month": f"{month_end:%Y-%m}", "enrolled": enrolled.count()})
        return Response(
            {
                "academic_year": str(year.pk),
                "academic_year_name": year.name,
                "total": active.count(),
                "by_level": [
                    {
                        "level": str(r["school_class__level"]),
                        "code": r["school_class__level__code"],
                        "name": r["school_class__level__name"],
                        "count": r["count"],
                    }
                    for r in by_level
                ],
                "by_class": by_class,
                "by_month": by_month,
            }
        )


class RecentActivity(AdminView):
    def get(self, request):
        from apps.audit.models import AuditLayer, AuditLog

        limit = self.int_param("limit", 10, 1, 50)
        school = self.membership().school
        rows = (
            AuditLog.objects.filter(school=school, layer=AuditLayer.ADMINISTRATIVE)
            .select_related("actor__user")
            .order_by("-created_at")[:limit]
        )
        return Response([_activity(row) for row in rows])


def _activity(row):
    data = row.new_data or row.old_data or {}
    # Configuration rows only (ADMINISTRATIVE layer): name / code, never a payload.
    label = data.get("name") or data.get("code") or ""
    actor = row.actor.user if row.actor_id else None
    return {
        "id": str(row.pk),
        "at": row.created_at,
        "action": row.action,
        "entity_type": row.entity_type.rsplit(".", 1)[-1],
        "label": str(label)[:120],
        "actor": (actor.full_name or actor.username) if actor else "",
    }


class TeacherStats(AdminView):
    """Active teachers (teaching AND employed) and their split by pedagogical category."""

    def get(self, request):
        from apps.people.teacher_api import teacher_counts

        school = self.membership().school
        rows = list(teacher_counts(school))
        return Response(
            {
                "active": sum(r["count"] for r in rows),
                "by_category": [
                    {
                        "code": r["pedagogical_category__code"],
                        "name": r["pedagogical_category__name"],
                        "count": r["count"],
                    }
                    for r in rows
                ],
            }
        )


urlpatterns = [
    path("admin/dashboard/attendance-trend/", AttendanceTrend.as_view(), name="dashboard-attendance-trend"),
    path("admin/dashboard/enrollments/", EnrollmentStats.as_view(), name="dashboard-enrollments"),
    path("admin/dashboard/activity/", RecentActivity.as_view(), name="dashboard-activity"),
    path("admin/dashboard/teachers/", TeacherStats.as_view(), name="dashboard-teachers"),
]
