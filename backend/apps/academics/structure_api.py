"""Academic years and levels API (ADR 0017), for the admin desktop
("Gestion académique → Années scolaires / Niveaux") and readable by every
member (year and level pickers everywhere).

    GET   /academic-years/                    ?status=PLANNED|ACTIVE|CLOSED|ARCHIVED   (members)
    POST  /academic-years/                    {name, start_date, end_date}             (admin)
    GET   /academic-years/{id}/                                                        (members)
    PATCH /academic-years/{id}/               {name?, start_date?, end_date?}          (admin)
    POST  /academic-years/{id}/set-current/                                            (admin)
    POST  /academic-years/{id}/close/                                                  (admin)

    GET   /levels/        ?search= ?active=true|false                                  (members)
    POST  /levels/        {code, name, cycle?, order_index?, first_character?, public_visible?}
    GET   /levels/{id}/
    PATCH /levels/{id}/   {name?, cycle?, order_index?, first_character?, public_visible?}
    POST  /levels/{id}/deactivate/ | /reactivate/

Writes go through academics.services (ADMIN/SUPER_ADMIN of the current
school, audit). Another school's id is a 404. Errors: 403 role, 409
duplicate name / code, overlapping dates, current year closed, pupils still
enrolled, dated content outside new dates, level still used by classes,
400 invalid data or rule (closed year, invalid dates, code immutable).
The lists keep the fields they always had and add `class_count`.
"""

from django.db.models import Count, Q
from django.urls import path
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .catalog_api import CatalogueFilterMixin, _scoped
from .models import AcademicYear, AcademicYearStatus, Level

# -----------------------------------------------------------------------------
# Academic years
# -----------------------------------------------------------------------------


class AcademicYearSerializer(serializers.ModelSerializer):
    class_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = AcademicYear
        fields = ["id", "name", "start_date", "end_date", "status", "is_current", "class_count"]


class YearCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=30)
    start_date = serializers.DateField()
    end_date = serializers.DateField()


class YearUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=30, required=False)
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)


def _with_counts(queryset):
    return queryset.annotate(class_count=Count("classes", filter=Q(classes__active=True), distinct=True))


def _year_out(year):
    return AcademicYearSerializer(_with_counts(AcademicYear.objects.filter(pk=year.pk)).get()).data


class AcademicYearListCreate(CatalogueFilterMixin, generics.ListAPIView):
    queryset = AcademicYear.objects.order_by("-start_date")
    serializer_class = AcademicYearSerializer

    def restrict(self, queryset):
        wanted = self.request.query_params.get("status")
        if wanted:
            if wanted not in AcademicYearStatus.values:
                allowed = ", ".join(AcademicYearStatus.values)
                raise serializers.ValidationError({"status": [f"Must be one of {allowed}."]})
            queryset = queryset.filter(status=wanted)
        return _with_counts(queryset)

    def post(self, request):
        data = YearCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        year = services.admin_create_year(self.membership().school, actor=self.membership(), **data.validated_data)
        return Response(_year_out(year), status=status.HTTP_201_CREATED)


class AcademicYearDetail(CatalogueFilterMixin, generics.RetrieveAPIView):
    queryset = AcademicYear.objects.all()
    serializer_class = AcademicYearSerializer

    def restrict(self, queryset):
        return _with_counts(queryset)

    def patch(self, request, pk):
        year = self.get_object()
        data = YearUpdateSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        year = services.admin_update_year(year, actor=self.membership(), **data.validated_data)
        return Response(_year_out(year))


class AcademicYearAction(CatalogueFilterMixin, APIView):
    operation = None  # "set-current" | "close", set by as_view()

    def post(self, request, pk):
        year = _scoped(AcademicYear, pk, request)
        handler = services.admin_set_current_year if self.operation == "set-current" else services.admin_close_year
        return Response(_year_out(handler(year, actor=self.membership())))


# -----------------------------------------------------------------------------
# Levels
# -----------------------------------------------------------------------------


class LevelSerializer(serializers.ModelSerializer):
    class_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Level
        fields = [
            "id",
            "code",
            "name",
            "cycle",
            "order_index",
            "first_character",
            "public_visible",
            "active",
            "class_count",
        ]


class LevelCreateSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=30)
    name = serializers.CharField(max_length=100)
    cycle = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    order_index = serializers.IntegerField(required=False, min_value=0, max_value=999, default=0)
    first_character = serializers.CharField(max_length=5, required=False, allow_blank=True, allow_null=True)
    public_visible = serializers.BooleanField(required=False, default=False)


class LevelUpdateSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=30, required=False)  # only to say it is immutable
    name = serializers.CharField(max_length=100, required=False)
    cycle = serializers.CharField(max_length=40, required=False, allow_blank=True)
    order_index = serializers.IntegerField(required=False, min_value=0, max_value=999)
    first_character = serializers.CharField(max_length=5, required=False, allow_blank=True, allow_null=True)
    public_visible = serializers.BooleanField(required=False)


def _level_counts(queryset):
    # Classes using the level in open (planned / current) years: what blocks a deactivation.
    used = Q(classes__active=True, classes__academic_year__status__in=services.OPEN_YEAR_STATUSES)
    return queryset.annotate(class_count=Count("classes", filter=used, distinct=True))


def _level_out(level):
    return LevelSerializer(_level_counts(Level.objects.filter(pk=level.pk)).get()).data


class LevelListCreate(CatalogueFilterMixin, generics.ListAPIView):
    queryset = Level.objects.order_by("order_index", "code")
    serializer_class = LevelSerializer
    search_fields = ("code__icontains", "name__icontains", "cycle__icontains")

    def restrict(self, queryset):
        return _level_counts(self.filter_catalogue(queryset))

    def post(self, request):
        data = LevelCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        level = services.create_level(self.membership().school, actor=self.membership(), **data.validated_data)
        return Response(_level_out(level), status=status.HTTP_201_CREATED)


class LevelDetail(CatalogueFilterMixin, generics.RetrieveAPIView):
    queryset = Level.objects.all()
    serializer_class = LevelSerializer

    def restrict(self, queryset):
        return _level_counts(queryset)

    def patch(self, request, pk):
        level = self.get_object()
        data = LevelUpdateSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        level = services.update_level(level, actor=self.membership(), **data.validated_data)
        return Response(_level_out(level))


class LevelActivation(CatalogueFilterMixin, APIView):
    active = None  # set by as_view(active=...)

    def post(self, request, pk):
        level = services.set_level_active(_scoped(Level, pk, request), self.active, actor=self.membership())
        return Response(_level_out(level))


urlpatterns = [
    path("academic-years/", AcademicYearListCreate.as_view(), name="academic-years"),
    path("academic-years/<uuid:pk>/", AcademicYearDetail.as_view(), name="academic-year"),
    path(
        "academic-years/<uuid:pk>/set-current/",
        AcademicYearAction.as_view(operation="set-current"),
        name="academic-year-set-current",
    ),
    path("academic-years/<uuid:pk>/close/", AcademicYearAction.as_view(operation="close"), name="academic-year-close"),
    path("levels/", LevelListCreate.as_view(), name="levels"),
    path("levels/<uuid:pk>/", LevelDetail.as_view(), name="level"),
    path("levels/<uuid:pk>/deactivate/", LevelActivation.as_view(active=False), name="level-deactivate"),
    path("levels/<uuid:pk>/reactivate/", LevelActivation.as_view(active=True), name="level-reactivate"),
]
