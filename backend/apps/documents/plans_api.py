"""School plans API (2D maps of the premises).

Administration (ADMIN / SUPER_ADMIN of the school):
    GET/POST  /admin/plans/                          list (?status= ?building=) / create a draft
    GET/PATCH /admin/plans/{id}/                     detail / metadata + distribution (never notifies)
    GET/POST  /admin/plans/{id}/versions/            history / import a file (multipart `file`) -> DRAFT version
    GET       /admin/plans/{id}/versions/{v}/file/   any version (preview, history), streamed
    POST      /admin/plans/{id}/publish/   {version} publish it (notifies the readers, once per version)
    POST      /admin/plans/{id}/withdraw/  {reason?}  gone for every reader at once
    GET/PUT   /admin/plans/{id}/audience/  {entries: [{target, school_class?}]}   MANUAL distribution
    GET       /admin/plans/{id}/access/                who can see it (resolved now)

Readers (parents / teachers allowed by the distribution, administrators):
    GET /plans/                 published plans I may see
    GET /plans/{id}/            one of them (404 otherwise)
    GET /plans/{id}/file/       its CURRENT version, streamed after the check

Every read re-checks the school, the role, the plan / version status and
the audience: what the caller may not see answers 404, like what does not
exist. Files: private storage, `Cache-Control: private, no-store`, never a
public URL nor a storage path.
"""

import re

from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import path
from rest_framework import generics, serializers, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.academics.models import SchoolClass
from common.permissions import ADMIN_ROLES, HasSchoolRole
from common.tenancy import scope_to_current_school
from common.views import SchoolScopedMixin

from . import plans
from .models import PlanAudienceTarget, PlanDistribution, PlanStatus, SchoolPlan, SchoolPlanVersion

EXTENSIONS = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg"}


def scoped(model, pk, request):
    return get_object_or_404(scope_to_current_school(model.objects.all(), request), pk=pk)


def _name(member):
    return member.user.full_name if member else None


class VersionSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.SerializerMethodField()
    uploaded_at = serializers.DateTimeField(source="created_at")
    is_current = serializers.SerializerMethodField()

    class Meta:
        model = SchoolPlanVersion
        fields = [
            "id",
            "number",
            "status",
            "original_name",
            "mime_type",
            "size_bytes",
            "sha256",
            "width",
            "height",
            "page_count",
            "uploaded_by_name",
            "uploaded_at",
            "published_at",
            "is_current",
        ]

    def get_uploaded_by_name(self, obj):
        return _name(obj.uploaded_by)

    def get_is_current(self, obj):
        return obj.plan.current_version_id == obj.pk


class AudienceSerializer(serializers.Serializer):
    target = serializers.ChoiceField(choices=PlanAudienceTarget.choices)
    school_class = serializers.UUIDField(required=False, allow_null=True)


class AdminPlanSerializer(serializers.ModelSerializer):
    current_version = serializers.SerializerMethodField()
    published_by_name = serializers.SerializerMethodField()
    versions_count = serializers.IntegerField(source="versions.count", read_only=True)
    audience = serializers.SerializerMethodField()

    class Meta:
        model = SchoolPlan
        fields = [
            "id",
            "title",
            "description",
            "building",
            "floor",
            "display_order",
            "status",
            "distribution",
            "current_version",
            "published_at",
            "published_by_name",
            "versions_count",
            "audience",
            "created_at",
        ]

    def get_current_version(self, obj):
        return VersionSerializer(obj.current_version).data if obj.current_version_id else None

    def get_published_by_name(self, obj):
        return _name(obj.published_by)

    def get_audience(self, obj):
        return [
            {
                "target": row.target,
                "school_class": str(row.school_class_id) if row.school_class_id else None,
                "school_class_name": row.school_class.name if row.school_class_id else None,
            }
            for row in obj.audience.select_related("school_class")
        ]


class ReaderPlanSerializer(serializers.ModelSerializer):
    """What a parent / teacher sees: no history, no audience, no author."""

    school_name = serializers.CharField(source="school.name")
    version = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = SchoolPlan
        fields = [
            "id",
            "title",
            "description",
            "building",
            "floor",
            "display_order",
            "published_at",
            "school_name",
            "version",
            "file_url",
        ]

    def get_version(self, obj):
        v = obj.current_version
        return {
            "number": v.number,
            "mime_type": v.mime_type,
            "size_bytes": v.size_bytes,
            "width": v.width,
            "height": v.height,
            "page_count": v.page_count,
            "published_at": v.published_at,
        }

    def get_file_url(self, obj):
        return f"/api/v1/plans/{obj.pk}/file/"


class PlanInput(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    building = serializers.CharField(required=False, allow_blank=True, max_length=100, default="")
    floor = serializers.CharField(required=False, allow_blank=True, max_length=60, default="")
    display_order = serializers.IntegerField(required=False, min_value=0, default=0)
    distribution = serializers.ChoiceField(choices=PlanDistribution.choices, required=False, default="AUTO")


class PlanUpdateInput(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    building = serializers.CharField(required=False, allow_blank=True, max_length=100)
    floor = serializers.CharField(required=False, allow_blank=True, max_length=60)
    display_order = serializers.IntegerField(required=False, min_value=0)
    distribution = serializers.ChoiceField(choices=PlanDistribution.choices, required=False)


def stream(version, handle, title):
    """A protected plan file: inline (a viewer shows it), never cached by a proxy."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", title).strip("-")[:60] or "plan"
    response = FileResponse(
        handle,
        as_attachment=False,
        filename=f"{slug}-v{version.number}.{EXTENSIONS[version.mime_type]}",
        content_type=version.mime_type,
    )
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response


# --- administration -----------------------------------------------------------------------


class AdminMixin(SchoolScopedMixin):
    permission_classes = [HasSchoolRole]
    required_roles = ADMIN_ROLES

    def plan(self, pk):
        return scoped(SchoolPlan, pk, self.request)


class AdminPlans(AdminMixin, generics.ListAPIView):
    serializer_class = AdminPlanSerializer

    def get_queryset(self):
        queryset = scope_to_current_school(SchoolPlan.objects.all(), self.request).select_related(
            "current_version", "published_by__user"
        )
        params = self.request.query_params
        if params.get("status"):
            queryset = queryset.filter(status=params["status"])
        if params.get("building"):
            queryset = queryset.filter(building__iexact=params["building"])
        return queryset

    def post(self, request):
        data = PlanInput(data=request.data)
        data.is_valid(raise_exception=True)
        plan = plans.create_plan(self.membership().school, actor=self.membership(), **data.validated_data)
        return Response(AdminPlanSerializer(plan).data, status=status.HTTP_201_CREATED)


class AdminPlanDetail(AdminMixin, APIView):
    def get(self, request, pk):
        return Response(AdminPlanSerializer(self.plan(pk)).data)

    def patch(self, request, pk):
        data = PlanUpdateInput(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        plan = plans.update_plan(self.plan(pk), actor=self.membership(), **data.validated_data)
        return Response(AdminPlanSerializer(plan).data)


class AdminPlanVersions(AdminMixin, APIView):
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request, pk):
        plan = self.plan(pk)
        return Response(VersionSerializer(plan.versions.select_related("plan", "uploaded_by__user"), many=True).data)

    def post(self, request, pk):
        upload = request.FILES.get("file")
        if upload is None:
            raise serializers.ValidationError({"file": ["Choose a PDF, PNG or JPEG file."]})
        version = plans.add_version(self.plan(pk), actor=self.membership(), upload=upload)
        return Response(VersionSerializer(version).data, status=status.HTTP_201_CREATED)


class AdminVersionFile(AdminMixin, APIView):
    def get(self, request, pk, version_pk):
        plan = self.plan(pk)
        version = get_object_or_404(plan.versions.all(), pk=version_pk)
        try:
            handle = plans.open_any_version(version, self.membership())
        except PermissionDenied:
            raise Http404 from None
        return stream(version, handle, plan.title)


class PublishInput(serializers.Serializer):
    version = serializers.UUIDField()


class AdminPlanPublish(AdminMixin, APIView):
    parser_classes = [JSONParser]

    def post(self, request, pk):
        data = PublishInput(data=request.data)
        data.is_valid(raise_exception=True)
        plan = self.plan(pk)
        version = get_object_or_404(plan.versions.all(), pk=data.validated_data["version"])
        plan = plans.publish(plan, actor=self.membership(), version=version)
        return Response(AdminPlanSerializer(plan).data)


class WithdrawInput(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")


class AdminPlanWithdraw(AdminMixin, APIView):
    parser_classes = [JSONParser]

    def post(self, request, pk):
        data = WithdrawInput(data=request.data)
        data.is_valid(raise_exception=True)
        plan = plans.withdraw(self.plan(pk), actor=self.membership(), reason=data.validated_data["reason"])
        return Response(AdminPlanSerializer(plan).data)


class AudienceInput(serializers.Serializer):
    entries = AudienceSerializer(many=True)


class AdminPlanAudience(AdminMixin, APIView):
    parser_classes = [JSONParser]

    def get(self, request, pk):
        return Response(AdminPlanSerializer(self.plan(pk)).data["audience"])

    def put(self, request, pk):
        data = AudienceInput(data=request.data)
        data.is_valid(raise_exception=True)
        entries = [
            (row["target"], scoped(SchoolClass, row["school_class"], request) if row.get("school_class") else None)
            for row in data.validated_data["entries"]
        ]
        plan = plans.set_audience(self.plan(pk), actor=self.membership(), entries=entries)
        return Response(AdminPlanSerializer(plan).data["audience"])


class AdminPlanAccess(AdminMixin, APIView):
    def get(self, request, pk):
        plan = self.plan(pk)
        readers = plans.readers(plan)
        return Response(
            {
                "published": plan.status == PlanStatus.PUBLISHED,
                "distribution": plan.distribution,
                "count": len(readers),
                "readers": [
                    {"id": str(m.pk), "name": m.user.full_name, "roles": sorted(m.role_codes() & {"PARENT", "TEACHER"})}
                    for m in readers
                ],
            }
        )


# --- readers ---------------------------------------------------------------------------------


class ReaderMixin(SchoolScopedMixin):
    def visible(self, pk):
        plan = scoped(SchoolPlan, pk, self.request)
        if not plans.can_view(self.membership(), plan):
            raise Http404  # withdrawn, not published, not for me: as if it did not exist
        return plan


class Plans(ReaderMixin, APIView):
    def get(self, request):
        return Response(ReaderPlanSerializer(plans.visible_plans(self.membership()), many=True).data)


class PlanDetail(ReaderMixin, APIView):
    def get(self, request, pk):
        return Response(ReaderPlanSerializer(self.visible(pk)).data)


class PlanFile(ReaderMixin, APIView):
    def get(self, request, pk):
        plan = scoped(SchoolPlan, pk, request)
        try:
            version, handle = plans.open_current(plan, self.membership())
        except PermissionDenied:
            raise Http404 from None
        return stream(version, handle, plan.title)


urlpatterns = [
    path("admin/plans/", AdminPlans.as_view()),
    path("admin/plans/<uuid:pk>/", AdminPlanDetail.as_view()),
    path("admin/plans/<uuid:pk>/versions/", AdminPlanVersions.as_view()),
    path("admin/plans/<uuid:pk>/versions/<uuid:version_pk>/file/", AdminVersionFile.as_view()),
    path("admin/plans/<uuid:pk>/publish/", AdminPlanPublish.as_view()),
    path("admin/plans/<uuid:pk>/withdraw/", AdminPlanWithdraw.as_view()),
    path("admin/plans/<uuid:pk>/audience/", AdminPlanAudience.as_view()),
    path("admin/plans/<uuid:pk>/access/", AdminPlanAccess.as_view()),
    path("plans/", Plans.as_view()),
    path("plans/<uuid:pk>/", PlanDetail.as_view()),
    path("plans/<uuid:pk>/file/", PlanFile.as_view()),
]
