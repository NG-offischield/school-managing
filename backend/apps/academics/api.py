"""Read-only endpoints of the academic structure (spec §6.4, §6.6).

Who can read: every ACTIVE member of the school. These are catalogues
(periods, scales) that every role needs to display its own screens; they
contain no personal data. Years and levels (with their admin writes) live
in structure_api.py, classes in class_api.py.
"""

from django.urls import path
from rest_framework import generics, serializers

from common.views import SchoolScopedMixin

from .models import AcademicPeriod, GradingScale


class AcademicPeriodSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcademicPeriod
        fields = [
            "id",
            "academic_year",
            "parent_period",
            "name",
            "period_type",
            "order_index",
            "start_date",
            "end_date",
            "status",
        ]


class GradingScaleSerializer(serializers.ModelSerializer):
    class Meta:
        model = GradingScale
        fields = ["id", "code", "label", "max_score", "pass_score", "decimal_places", "is_default", "active"]


class GradingScaleList(SchoolScopedMixin, generics.ListAPIView):
    queryset = GradingScale.objects.all()
    serializer_class = GradingScaleSerializer


class AcademicPeriodList(SchoolScopedMixin, generics.ListAPIView):
    """Optional filter: ?academic_year=<uuid>."""

    queryset = AcademicPeriod.objects.all()
    serializer_class = AcademicPeriodSerializer

    def restrict(self, queryset):
        year = self.uuid_param("academic_year")
        return queryset.filter(academic_year_id=year) if year else queryset


urlpatterns = [
    path("academic-periods/", AcademicPeriodList.as_view(), name="academic-periods"),
    path("grading-scales/", GradingScaleList.as_view(), name="grading-scales"),
]
