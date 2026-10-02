"""Read-only endpoints of the academic structure (spec §6.4, §6.6).

Who can read: every ACTIVE member of the school. These are catalogues
(years, periods, levels, categories, subjects, classes) that every role
needs to display its own screens; they contain no personal data. Writes go
through services (admin desktop phase).
"""

from django.urls import path
from rest_framework import generics, serializers

from common.views import SchoolScopedMixin

from .models import AcademicPeriod, AcademicYear, GradingScale, Level, PedagogicalCategory, SchoolClass, Subject


class AcademicYearSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcademicYear
        fields = ["id", "name", "start_date", "end_date", "status", "is_current"]


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


class LevelSerializer(serializers.ModelSerializer):
    class Meta:
        model = Level
        fields = ["id", "code", "name", "cycle", "order_index", "first_character", "active"]


class PedagogicalCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = PedagogicalCategory
        fields = ["id", "code", "name", "description", "active"]


class SubjectSerializer(serializers.ModelSerializer):
    category_code = serializers.CharField(source="category.code", default=None, read_only=True)

    class Meta:
        model = Subject
        fields = ["id", "code", "name", "category", "category_code", "subject_type", "active"]


class SchoolClassSerializer(serializers.ModelSerializer):
    level_code = serializers.CharField(source="level.code", read_only=True)

    class Meta:
        model = SchoolClass
        fields = ["id", "name", "level", "level_code", "academic_year", "capacity", "active"]


class GradingScaleSerializer(serializers.ModelSerializer):
    class Meta:
        model = GradingScale
        fields = ["id", "code", "label", "max_score", "pass_score", "decimal_places", "is_default", "active"]


class GradingScaleList(SchoolScopedMixin, generics.ListAPIView):
    queryset = GradingScale.objects.all()
    serializer_class = GradingScaleSerializer


class AcademicYearList(SchoolScopedMixin, generics.ListAPIView):
    queryset = AcademicYear.objects.all()
    serializer_class = AcademicYearSerializer


class AcademicYearDetail(SchoolScopedMixin, generics.RetrieveAPIView):
    queryset = AcademicYear.objects.all()
    serializer_class = AcademicYearSerializer


class AcademicPeriodList(SchoolScopedMixin, generics.ListAPIView):
    """Optional filter: ?academic_year=<uuid>."""

    queryset = AcademicPeriod.objects.all()
    serializer_class = AcademicPeriodSerializer

    def restrict(self, queryset):
        year = self.uuid_param("academic_year")
        return queryset.filter(academic_year_id=year) if year else queryset


class LevelList(SchoolScopedMixin, generics.ListAPIView):
    queryset = Level.objects.all()
    serializer_class = LevelSerializer


class PedagogicalCategoryList(SchoolScopedMixin, generics.ListAPIView):
    queryset = PedagogicalCategory.objects.all()
    serializer_class = PedagogicalCategorySerializer


class SubjectList(SchoolScopedMixin, generics.ListAPIView):
    queryset = Subject.objects.select_related("category")
    serializer_class = SubjectSerializer


class SchoolClassList(SchoolScopedMixin, generics.ListAPIView):
    """Optional filter: ?academic_year=<uuid>."""

    queryset = SchoolClass.objects.select_related("level")
    serializer_class = SchoolClassSerializer

    def restrict(self, queryset):
        year = self.uuid_param("academic_year")
        return queryset.filter(academic_year_id=year) if year else queryset


urlpatterns = [
    path("academic-years/", AcademicYearList.as_view(), name="academic-years"),
    path("academic-years/<uuid:pk>/", AcademicYearDetail.as_view(), name="academic-year"),
    path("academic-periods/", AcademicPeriodList.as_view(), name="academic-periods"),
    path("levels/", LevelList.as_view(), name="levels"),
    path("pedagogical-categories/", PedagogicalCategoryList.as_view(), name="pedagogical-categories"),
    path("subjects/", SubjectList.as_view(), name="subjects"),
    path("classes/", SchoolClassList.as_view(), name="classes"),
    path("grading-scales/", GradingScaleList.as_view(), name="grading-scales"),
]
