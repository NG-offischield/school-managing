"""Pedagogical catalogue API: categories and subjects (ADR 0010).

Designed for the PySide6 admin desktop ("Gestion académique → Catégories /
Matières → Ajouter / Modifier / Désactiver") and readable by every member
(subject pickers in Flutter, report cards...).

    GET   /pedagogical-categories/                 ?search= ?active=true|false   (members)
    POST  /pedagogical-categories/                 {code, name, description}     (admin)
    GET   /pedagogical-categories/{id}/                                          (members)
    PATCH /pedagogical-categories/{id}/            {name?, description?}         (admin)
    POST  /pedagogical-categories/{id}/deactivate/ | /reactivate/                (admin)

    GET   /subjects/        ?search= ?active= ?category=<uuid> ?subject_type=    (members)
    POST  /subjects/        {code, name, category, subject_type?, default_grading_scale?, public_visible?}
    GET   /subjects/{id}/
    PATCH /subjects/{id}/   {name?, category?, subject_type?, default_grading_scale?, public_visible?}
    POST  /subjects/{id}/deactivate/ | /reactivate/

A category selector simply calls GET /pedagogical-categories/?active=true
(&page_size=100): {id, code, name}. A subject is created with the category's
id — never with free text.

All writes go through academics.services (permission ADMIN/SUPER_ADMIN of
the current school, audit trail). Referenced ids (category, scale) are looked
up inside the current school: another school's id is a 404. Errors: 403
missing role, 404 out of school, 409 duplicate code / row still in use,
400 invalid data or business rule (code immutable, inactive category...).
"""

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.urls import path
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from common.tenancy import scope_to_current_school
from common.views import SchoolScopedMixin

from . import services
from .models import GradingScale, PedagogicalCategory, Subject, SubjectType

# -----------------------------------------------------------------------------
# Serializers
# -----------------------------------------------------------------------------


class CategorySerializer(serializers.ModelSerializer):
    active_subject_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = PedagogicalCategory
        fields = ["id", "code", "name", "description", "active", "active_subject_count"]


class CategoryCreateSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=40)
    name = serializers.CharField(max_length=120)
    description = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class CategoryUpdateSerializer(serializers.Serializer):
    # `code` is accepted only to give an explicit "code_immutable" error.
    code = serializers.CharField(max_length=40, required=False)
    name = serializers.CharField(max_length=120, required=False)
    description = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class CategoryRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = PedagogicalCategory
        fields = ["id", "code", "name", "active"]


class SubjectSerializer(serializers.ModelSerializer):
    category = CategoryRefSerializer(read_only=True)

    class Meta:
        model = Subject
        fields = [
            "id",
            "code",
            "name",
            "category",
            "subject_type",
            "default_grading_scale",
            "public_visible",
            "active",
        ]


class SubjectCreateSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=30)
    name = serializers.CharField(max_length=120)
    category = serializers.UUIDField()
    subject_type = serializers.ChoiceField(choices=SubjectType.choices, default=SubjectType.THEORETICAL)
    default_grading_scale = serializers.UUIDField(required=False, allow_null=True)
    public_visible = serializers.BooleanField(required=False, default=False)


class SubjectUpdateSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=30, required=False)
    name = serializers.CharField(max_length=120, required=False)
    category = serializers.UUIDField(required=False)
    subject_type = serializers.ChoiceField(choices=SubjectType.choices, required=False)
    default_grading_scale = serializers.UUIDField(required=False, allow_null=True)
    public_visible = serializers.BooleanField(required=False)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _scoped(model, pk, request):
    return get_object_or_404(scope_to_current_school(model.objects.all(), request), pk=pk)


def _resolve_refs(data, request):
    """Replace referenced ids by objects of the CURRENT school (404 otherwise)."""
    resolved = dict(data)
    if "category" in resolved:
        resolved["category"] = _scoped(PedagogicalCategory, resolved["category"], request)
    if "default_grading_scale" in resolved:
        pk = resolved["default_grading_scale"]
        resolved["default_grading_scale"] = _scoped(GradingScale, pk, request) if pk else None
    return resolved


class CatalogueFilterMixin(SchoolScopedMixin):
    search_fields = ("code__icontains", "name__icontains")

    def bool_param(self, name):
        raw = self.request.query_params.get(name)
        if raw is None or raw == "":
            return None
        if raw.lower() in ("true", "1"):
            return True
        if raw.lower() in ("false", "0"):
            return False
        raise serializers.ValidationError({name: ["Must be true or false."]})

    def filter_catalogue(self, queryset):
        search = (self.request.query_params.get("search") or "").strip()
        if search:
            q = Q()
            for lookup in self.search_fields:
                q |= Q(**{lookup: search})
            queryset = queryset.filter(q)
        active = self.bool_param("active")
        if active is not None:
            queryset = queryset.filter(active=active)
        return queryset


# -----------------------------------------------------------------------------
# Categories
# -----------------------------------------------------------------------------


class CategoryListCreate(CatalogueFilterMixin, generics.ListAPIView):
    queryset = PedagogicalCategory.objects.order_by("code")
    serializer_class = CategorySerializer

    def restrict(self, queryset):
        from django.db.models import Count

        queryset = queryset.annotate(active_subject_count=Count("subjects", filter=Q(subjects__active=True)))
        return self.filter_catalogue(queryset)

    def post(self, request):
        data = CategoryCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        category = services.create_category(self.membership().school, actor=self.membership(), **data.validated_data)
        return Response(CategorySerializer(category).data, status=status.HTTP_201_CREATED)


class CategoryDetail(SchoolScopedMixin, generics.RetrieveAPIView):
    queryset = PedagogicalCategory.objects.all()
    serializer_class = CategorySerializer

    def patch(self, request, pk):
        category = self.get_object()
        data = CategoryUpdateSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        category = services.update_category(category, actor=self.membership(), **data.validated_data)
        return Response(CategorySerializer(category).data)


class CategoryActivation(SchoolScopedMixin, APIView):
    active = None  # set by as_view(active=...)

    def post(self, request, pk):
        category = _scoped(PedagogicalCategory, pk, request)
        category = services.set_category_active(category, self.active, actor=self.membership())
        return Response(CategorySerializer(category).data)


# -----------------------------------------------------------------------------
# Subjects
# -----------------------------------------------------------------------------


class SubjectListCreate(CatalogueFilterMixin, generics.ListAPIView):
    queryset = Subject.objects.select_related("category").order_by("name")
    serializer_class = SubjectSerializer

    def restrict(self, queryset):
        queryset = self.filter_catalogue(queryset)
        category = self.uuid_param("category")
        if category:
            queryset = queryset.filter(category_id=category)
        subject_type = self.request.query_params.get("subject_type")
        if subject_type:
            if subject_type not in SubjectType.values:
                raise serializers.ValidationError({"subject_type": ["Unknown subject type."]})
            queryset = queryset.filter(subject_type=subject_type)
        return queryset

    def post(self, request):
        data = SubjectCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        fields = _resolve_refs(data.validated_data, request)
        subject = services.create_subject(self.membership().school, actor=self.membership(), **fields)
        return Response(SubjectSerializer(subject).data, status=status.HTTP_201_CREATED)


class SubjectDetail(SchoolScopedMixin, generics.RetrieveAPIView):
    queryset = Subject.objects.select_related("category")
    serializer_class = SubjectSerializer

    def patch(self, request, pk):
        subject = self.get_object()
        data = SubjectUpdateSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        fields = _resolve_refs(data.validated_data, request)
        subject = services.update_subject(subject, actor=self.membership(), **fields)
        return Response(SubjectSerializer(subject).data)


class SubjectActivation(SchoolScopedMixin, APIView):
    active = None

    def post(self, request, pk):
        subject = _scoped(Subject, pk, request)
        subject = services.set_subject_active(subject, self.active, actor=self.membership())
        return Response(SubjectSerializer(subject).data)


urlpatterns = [
    path("pedagogical-categories/", CategoryListCreate.as_view(), name="pedagogical-categories"),
    path("pedagogical-categories/<uuid:pk>/", CategoryDetail.as_view(), name="pedagogical-category"),
    path(
        "pedagogical-categories/<uuid:pk>/deactivate/",
        CategoryActivation.as_view(active=False),
        name="pedagogical-category-deactivate",
    ),
    path(
        "pedagogical-categories/<uuid:pk>/reactivate/",
        CategoryActivation.as_view(active=True),
        name="pedagogical-category-reactivate",
    ),
    path("subjects/", SubjectListCreate.as_view(), name="subjects"),
    path("subjects/<uuid:pk>/", SubjectDetail.as_view(), name="subject"),
    path("subjects/<uuid:pk>/deactivate/", SubjectActivation.as_view(active=False), name="subject-deactivate"),
    path("subjects/<uuid:pk>/reactivate/", SubjectActivation.as_view(active=True), name="subject-reactivate"),
]
