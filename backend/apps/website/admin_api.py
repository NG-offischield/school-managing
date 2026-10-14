"""Administration of the ISBREE contents (ADR 0032) — used by the PySide6
desktop. ADMIN / SUPER_ADMIN or CONTENT_MANAGER of the school; every write
goes through services.py (role re-checked, audited). Ids of other schools are
404. Nothing is deleted: a content is archived (status ARCHIVED).

    GET/PATCH /admin/website/profile/
    GET/POST  /admin/website/{pages|faq|news|locations|resources}/      GET/PATCH …/{id}/
    GET /admin/website/images/   POST …/images/upload/ (multipart "file")   GET/PATCH …/{id}/   GET …/{id}/file/
    POST      /admin/website/resources/{id}/document/  (multipart "file", PDF)
    GET/POST  /admin/website/releases/  (multipart "file", signed release APK)   POST …/{id}/status/ {status}
    GET       /admin/website/readiness/   what is missing before a production opening
"""

from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import path
from rest_framework import serializers, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.academics.models import AcademicYear, Level, SchoolClass
from apps.people.models import StaffFunction
from common.permissions import HasSchoolRole
from common.views import SchoolScopedMixin

from . import files, services
from .models import (
    AUDIENCES,
    ContentImage,
    FaqEntry,
    MobileApp,
    MobileAppRelease,
    NewsArticle,
    Page,
    PublicationStatus,
    ReleaseStatus,
    RoleResource,
    SiteLocation,
    SiteProfile,
)

COMMON = ["status", "to_validate", "is_demo", "order"]


class EditorMixin(SchoolScopedMixin):
    permission_classes = [HasSchoolRole]
    required_roles = services.EDITOR_ROLES

    def school(self):
        return self.membership().school

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        return response


def _audiences():
    return serializers.ListField(child=serializers.ChoiceField(choices=list(AUDIENCES)), allow_empty=False)


class PageSerializer(serializers.ModelSerializer):
    audiences = _audiences()
    slug = serializers.SlugField(max_length=80, required=False, allow_blank=True)

    class Meta:
        model = Page
        fields = ["id", "kind", "slug", "title", "summary", "body", "audiences", *COMMON, "updated_at"]
        read_only_fields = ["id", "updated_at"]
        validators = []  # slug uniqueness: services.unique_slug


class FaqSerializer(serializers.ModelSerializer):
    audiences = _audiences()

    class Meta:
        model = FaqEntry
        fields = ["id", "category", "question", "answer", "audiences", *COMMON, "updated_at"]
        read_only_fields = ["id", "updated_at"]


class NewsSerializer(serializers.ModelSerializer):
    audiences = _audiences()
    slug = serializers.SlugField(max_length=120, required=False, allow_blank=True)
    cover = serializers.PrimaryKeyRelatedField(queryset=ContentImage.objects.all(), allow_null=True, required=False)

    class Meta:
        model = NewsArticle
        fields = [
            "id",
            "slug",
            "title",
            "summary",
            "body",
            "category",
            "event_date",
            "cover",
            "audiences",
            "published_at",
            *COMMON,
            "updated_at",
        ]
        read_only_fields = ["id", "published_at", "updated_at"]
        validators = []


class LocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteLocation
        fields = ["id", "name", "description", "address_text", "is_main", *COMMON, "updated_at"]
        read_only_fields = ["id", "updated_at"]


class ResourceSerializer(serializers.ModelSerializer):
    audiences = serializers.ListField(
        child=serializers.ChoiceField(choices=["PARENT", "TEACHER", "STAFF", "GUARDIAN"]), allow_empty=False
    )
    level = serializers.PrimaryKeyRelatedField(queryset=Level.objects.all(), allow_null=True, required=False)
    school_class = serializers.PrimaryKeyRelatedField(
        queryset=SchoolClass.objects.all(), allow_null=True, required=False
    )
    academic_year = serializers.PrimaryKeyRelatedField(
        queryset=AcademicYear.objects.all(), allow_null=True, required=False
    )
    staff_function = serializers.PrimaryKeyRelatedField(
        queryset=StaffFunction.objects.all(), allow_null=True, required=False
    )

    class Meta:
        model = RoleResource
        fields = [
            "id",
            "kind",
            "title",
            "body",
            "audiences",
            "level",
            "school_class",
            "academic_year",
            "staff_function",
            "visible_from",
            "visible_until",
            "document_name",
            "document_size",
            *COMMON,
            "updated_at",
        ]
        read_only_fields = ["id", "document_name", "document_size", "updated_at"]


class ImageSerializer(serializers.ModelSerializer):
    audiences = _audiences()

    class Meta:
        model = ContentImage
        fields = [
            "id",
            "alt_text",
            "caption",
            "credit",
            "category",
            "in_gallery",
            "is_illustration",
            "audiences",
            "width",
            "height",
            "size",
            *COMMON,
            "updated_at",
        ]
        read_only_fields = ["id", "width", "height", "size", "updated_at"]


class ReleaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = MobileAppRelease
        fields = [
            "id",
            "app",
            "version_name",
            "version_code",
            "release_notes",
            "min_android",
            "file_name",
            "size",
            "sha256",
            "status",
            "published_at",
            "created_at",
        ]
        read_only_fields = fields


KINDS = {
    "pages": (Page, PageSerializer),
    "faq": (FaqEntry, FaqSerializer),
    "news": (NewsArticle, NewsSerializer),
    "locations": (SiteLocation, LocationSerializer),
    "resources": (RoleResource, ResourceSerializer),
    "images": (ContentImage, ImageSerializer),
}


def _kind(kind):
    if kind not in KINDS:
        raise Http404
    return KINDS[kind]


def _save(kind, school, actor, serializer, instance=None):
    # A refused rule -> 400 BUSINESS_RULE_VIOLATION {rule} (common/exceptions.py)
    return services.save_content(kind, school, actor=actor, values=dict(serializer.validated_data), instance=instance)


class ContentList(EditorMixin, APIView):
    def get(self, request, kind):
        model, serializer = _kind(kind)
        rows = model.objects.filter(school=self.school())
        wanted = request.query_params.get("status")
        if wanted in PublicationStatus.values:
            rows = rows.filter(status=wanted)
        return Response(serializer(rows, many=True).data)

    def post(self, request, kind):
        model, serializer_class = _kind(kind)
        if model is ContentImage:
            raise Http404  # images are uploaded through /images/ with a file
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = _save(kind, self.school(), self.membership(), serializer)
        return Response(serializer_class(row).data, status=status.HTTP_201_CREATED)


class ContentDetail(EditorMixin, APIView):
    def get(self, request, kind, pk):
        model, serializer = _kind(kind)
        return Response(serializer(get_object_or_404(model.objects.filter(school=self.school()), pk=pk)).data)

    def patch(self, request, kind, pk):
        model, serializer_class = _kind(kind)
        row = get_object_or_404(model.objects.filter(school=self.school()), pk=pk)
        serializer = serializer_class(row, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        row = _save(kind, self.school(), self.membership(), serializer, instance=row)
        return Response(serializer_class(row).data)


class ImageUpload(EditorMixin, APIView):
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        upload = request.FILES.get("file")
        if upload is None:
            raise serializers.ValidationError({"file": ["A file is required."]})
        data = request.data.copy()
        audiences = data.getlist("audiences") if hasattr(data, "getlist") else data.get("audiences")
        values = {k: v for k, v in data.items() if k not in ("file", "audiences")}
        values["audiences"] = audiences or ["PUBLIC"]
        serializer = ImageSerializer(data=values, partial=True)
        serializer.is_valid(raise_exception=True)
        image = services.add_image(
            self.school(), actor=self.membership(), upload=upload, values=serializer.validated_data
        )
        return Response(ImageSerializer(image).data, status=status.HTTP_201_CREATED)


class ImageFile(EditorMixin, APIView):
    def get(self, request, pk):
        image = get_object_or_404(ContentImage.objects.filter(school=self.school()), pk=pk)
        return FileResponse(files.open_file(image.storage_path), content_type=image.mime_type)


class ResourceDocumentUpload(EditorMixin, APIView):
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        resource = get_object_or_404(RoleResource.objects.filter(school=self.school()), pk=pk)
        upload = request.FILES.get("file")
        if upload is None:
            raise serializers.ValidationError({"file": ["A file is required."]})
        resource = services.attach_document(resource, actor=self.membership(), upload=upload)
        return Response(ResourceSerializer(resource).data)


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteProfile
        fields = [
            "tagline",
            "presentation",
            "values",
            "pedagogy",
            "location_details",
            "office_hours",
            "address_confirmed",
            "to_validate",
        ]


class ProfileView(EditorMixin, APIView):
    def get(self, request):
        profile = SiteProfile.objects.filter(school=self.school()).first() or SiteProfile(school=self.school())
        return Response(ProfileSerializer(profile).data)

    def patch(self, request):
        serializer = ProfileSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        profile = services.save_profile(self.school(), actor=self.membership(), values=serializer.validated_data)
        return Response(ProfileSerializer(profile).data)


class ReleaseInput(serializers.Serializer):
    app = serializers.ChoiceField(choices=MobileApp.values)
    version_name = serializers.RegexField(r"^[0-9A-Za-z.+_-]{1,40}$")
    version_code = serializers.IntegerField(min_value=1)
    release_notes = serializers.CharField(required=False, allow_blank=True, max_length=4000)
    min_android = serializers.CharField(required=False, allow_blank=True, max_length=60)


class ReleaseList(EditorMixin, APIView):
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        return Response(ReleaseSerializer(MobileAppRelease.objects.filter(school=self.school()), many=True).data)

    def post(self, request):
        upload = request.FILES.get("file")
        if upload is None:
            raise serializers.ValidationError({"file": ["A file is required."]})
        data = ReleaseInput(data=request.data)
        data.is_valid(raise_exception=True)
        release = services.add_release(self.school(), actor=self.membership(), upload=upload, **data.validated_data)
        return Response(ReleaseSerializer(release).data, status=status.HTTP_201_CREATED)


class ReleaseStatusInput(serializers.Serializer):
    status = serializers.ChoiceField(choices=ReleaseStatus.values)


class ReleaseStatusView(EditorMixin, APIView):
    def post(self, request, pk):
        release = get_object_or_404(MobileAppRelease.objects.filter(school=self.school()), pk=pk)
        data = ReleaseStatusInput(data=request.data)
        data.is_valid(raise_exception=True)
        release = services.set_release_status(release, data.validated_data["status"], actor=self.membership())
        return Response(ReleaseSerializer(release).data)


class Readiness(EditorMixin, APIView):
    """What still prevents a production opening (never blocks local work)."""

    def get(self, request):
        from .readiness import readiness_report

        return Response(readiness_report(self.school()))


urlpatterns = [
    path("admin/website/profile/", ProfileView.as_view()),
    path("admin/website/readiness/", Readiness.as_view()),
    path("admin/website/images/upload/", ImageUpload.as_view()),
    path("admin/website/images/<uuid:pk>/file/", ImageFile.as_view()),
    path("admin/website/resources/<uuid:pk>/document/", ResourceDocumentUpload.as_view()),
    path("admin/website/releases/", ReleaseList.as_view()),
    path("admin/website/releases/<uuid:pk>/status/", ReleaseStatusView.as_view()),
    path("admin/website/<str:kind>/", ContentList.as_view()),
    path("admin/website/<str:kind>/<uuid:pk>/", ContentDetail.as_view()),
]
