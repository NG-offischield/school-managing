"""Classes API (spec §6.4: GET/POST /api/v1/classes/), for the admin desktop
("Gestion académique → Classes") and readable by every member.

    GET   /classes/                ?academic_year= ?level= ?search= ?active=true|false   (members)
    POST  /classes/                {name, level, academic_year, capacity?, main_room?, regime?, public_visible?} (admin)
    GET   /classes/{id}/                                                                  (members)
    PATCH /classes/{id}/           {name?, level?, capacity?, main_room?, regime?, public_visible?}     (admin)
    POST  /classes/{id}/deactivate/ | /reactivate/                                                       (admin)

Timetable regimes (optional; day / evening classes sharing a default room):
    GET   /timetable-regimes/      ?academic_year=   (members)
    POST  /timetable-regimes/      {academic_year, name, start_time, end_time}   (admin)
    PATCH /timetable-regimes/{id}/ {name?, start_time?, end_time?, active?}        (admin)

Default room: optional, held by ONE class per year — or shared by classes of
explicit, non-overlapping regimes (409 room_default_taken /
room_default_regimes_overlap). Changing it never moves existing slots or
sessions (it only pre-fills new slots).

Writes go through academics.services (ADMIN/SUPER_ADMIN of the current
school, audit). Referenced ids (level, year, room) are looked up inside the
current school: another school's id is a 404. Errors: 403 role, 404 out of
school, 409 duplicate name in the year / class still in use / year
immutable, 400 invalid data or rule (closed year, inactive level or room).
The list keeps the fields it always had (id, name, level, level_code,
academic_year, capacity, active) and adds display labels.
"""

from django.urls import path
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .catalog_api import CatalogueFilterMixin, _scoped
from .models import AcademicYear, Level, Room, SchoolClass, TimetableRegime


class SchoolClassSerializer(serializers.ModelSerializer):
    level_code = serializers.CharField(source="level.code", read_only=True)
    level_name = serializers.CharField(source="level.name", read_only=True)
    academic_year_name = serializers.CharField(source="academic_year.name", read_only=True)
    main_room_name = serializers.SerializerMethodField()
    regime_name = serializers.SerializerMethodField()

    class Meta:
        model = SchoolClass
        fields = [
            "id",
            "name",
            "level",
            "level_code",
            "level_name",
            "academic_year",
            "academic_year_name",
            "capacity",
            "main_room",
            "main_room_name",
            "regime",
            "regime_name",
            "public_visible",
            "active",
        ]

    def get_main_room_name(self, obj):
        return f"{obj.main_room.code} — {obj.main_room.name}" if obj.main_room_id else None

    def get_regime_name(self, obj):
        return str(obj.regime) if obj.regime_id else None


class ClassCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80)
    level = serializers.UUIDField()
    academic_year = serializers.UUIDField()
    capacity = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    main_room = serializers.UUIDField(required=False, allow_null=True)
    regime = serializers.UUIDField(required=False, allow_null=True)
    public_visible = serializers.BooleanField(required=False, default=False)


class ClassUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80, required=False)
    level = serializers.UUIDField(required=False)
    academic_year = serializers.UUIDField(required=False)  # accepted only to say it is immutable
    capacity = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    main_room = serializers.UUIDField(required=False, allow_null=True)
    regime = serializers.UUIDField(required=False, allow_null=True)
    public_visible = serializers.BooleanField(required=False)


def _resolve(data, request):
    """Referenced ids -> objects of the CURRENT school (404 otherwise)."""
    resolved = dict(data)
    for field, model in (("level", Level), ("academic_year", AcademicYear)):
        if field in resolved:
            resolved[field] = _scoped(model, resolved[field], request)
    for field, model in (("main_room", Room), ("regime", TimetableRegime)):
        if field in resolved:
            resolved[field] = _scoped(model, resolved[field], request) if resolved[field] else None
    return resolved


class ClassListCreate(CatalogueFilterMixin, generics.ListAPIView):
    queryset = SchoolClass.objects.select_related("level", "academic_year", "main_room", "regime").order_by(
        "-academic_year__start_date", "level__order_index", "name"
    )
    serializer_class = SchoolClassSerializer
    search_fields = ("name__icontains", "level__name__icontains", "level__code__icontains")

    def restrict(self, queryset):
        queryset = self.filter_catalogue(queryset)
        for param, field in (("academic_year", "academic_year_id"), ("level", "level_id")):
            value = self.uuid_param(param)
            if value:
                queryset = queryset.filter(**{field: value})
        return queryset

    def post(self, request):
        data = ClassCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        school_class = services.create_class(
            self.membership().school, actor=self.membership(), **_resolve(data.validated_data, request)
        )
        return Response(SchoolClassSerializer(school_class).data, status=status.HTTP_201_CREATED)


class ClassDetail(CatalogueFilterMixin, generics.RetrieveAPIView):
    queryset = SchoolClass.objects.select_related("level", "academic_year", "main_room", "regime")
    serializer_class = SchoolClassSerializer

    def patch(self, request, pk):
        school_class = self.get_object()
        data = ClassUpdateSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        school_class = services.update_class(
            school_class, actor=self.membership(), **_resolve(data.validated_data, request)
        )
        return Response(SchoolClassSerializer(school_class).data)


class ClassActivation(CatalogueFilterMixin, APIView):
    active = None  # set by as_view(active=...)

    def post(self, request, pk):
        school_class = services.set_class_active(
            _scoped(SchoolClass, pk, request), self.active, actor=self.membership()
        )
        return Response(SchoolClassSerializer(school_class).data)


class RegimeSerializer(serializers.ModelSerializer):
    class Meta:
        model = TimetableRegime
        fields = ["id", "academic_year", "name", "start_time", "end_time", "active"]


class RegimeCreateSerializer(serializers.Serializer):
    academic_year = serializers.UUIDField()
    name = serializers.CharField(max_length=80)
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()


class RegimeUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80, required=False)
    start_time = serializers.TimeField(required=False)
    end_time = serializers.TimeField(required=False)
    active = serializers.BooleanField(required=False)


class RegimeListCreate(CatalogueFilterMixin, generics.ListAPIView):
    queryset = TimetableRegime.objects.select_related("academic_year").order_by("start_time", "name")
    serializer_class = RegimeSerializer
    search_fields = ("name__icontains",)

    def restrict(self, queryset):
        queryset = self.filter_catalogue(queryset)
        year = self.uuid_param("academic_year")
        return queryset.filter(academic_year_id=year) if year else queryset

    def post(self, request):
        data = RegimeCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = _resolve(data.validated_data, request)
        regime = services.create_regime(self.membership().school, actor=self.membership(), **values)
        return Response(RegimeSerializer(regime).data, status=status.HTTP_201_CREATED)


class RegimeDetail(CatalogueFilterMixin, generics.RetrieveAPIView):
    queryset = TimetableRegime.objects.all()
    serializer_class = RegimeSerializer

    def patch(self, request, pk):
        data = RegimeUpdateSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        regime = services.update_regime(self.get_object(), actor=self.membership(), **data.validated_data)
        return Response(RegimeSerializer(regime).data)


urlpatterns = [
    path("classes/", ClassListCreate.as_view(), name="classes"),
    path("classes/<uuid:pk>/", ClassDetail.as_view(), name="class"),
    path("classes/<uuid:pk>/deactivate/", ClassActivation.as_view(active=False), name="class-deactivate"),
    path("classes/<uuid:pk>/reactivate/", ClassActivation.as_view(active=True), name="class-reactivate"),
    path("timetable-regimes/", RegimeListCreate.as_view(), name="timetable-regimes"),
    path("timetable-regimes/<uuid:pk>/", RegimeDetail.as_view(), name="timetable-regime"),
]
