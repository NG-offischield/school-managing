"""Public API of the ISBREE site (ADR 0032) — anonymous, read-only except the
pre-enrollment request. The school is named in the URL by its public code.

    GET  /public/{code}/site/                 identity, presentation, locations, offered levels / years
    GET  /public/{code}/pages/                published public pages (list)   GET …/pages/{slug}/
    GET  /public/{code}/faq/                  published public questions
    GET  /public/{code}/news/                 published public articles (paginated)   GET …/news/{slug}/
    GET  /public/{code}/gallery/              published public images
    GET  /public/{code}/images/{id}/          the image file (published + public only)
    POST /public/{code}/pre-enrollments/      a family's request (throttled, honeypot)

Only PUBLISHED rows with the PUBLIC audience, through explicit serializers:
no private field, no internal id beyond what links need, no draft. An
unknown or inactive school is a 404. Nothing here needs or reads a session.
"""

from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import path
from rest_framework import generics, serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.services import ClientContext
from apps.admissions import services as admissions
from apps.admissions.models import GuardianRelationship
from apps.core.models import School, SchoolStatus

from . import files
from .models import PUBLIC, ContentImage, FaqEntry, NewsArticle, Page, PublicationStatus, SiteLocation, SiteProfile
from .services import published


def public_school(code):
    school = School.objects.filter(code=code, status=SchoolStatus.ACTIVE).first()
    if school is None:
        raise Http404
    return school


class PublicView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "public-content"

    def school(self):
        return public_school(self.kwargs["code"])


class PublicList(PublicView, generics.ListAPIView):
    model = None

    def get_queryset(self):
        return published(self.model.objects.filter(school=self.school()), PUBLIC)


# --- serializers ---------------------------------------------------------------------


class ImageRefSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContentImage
        fields = ["id", "width", "height", "alt_text", "caption", "credit", "category", "is_illustration", "is_demo"]


class PageListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Page
        fields = ["slug", "kind", "title", "summary", "to_validate", "is_demo"]


class PageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Page
        fields = ["slug", "kind", "title", "summary", "body", "to_validate", "is_demo", "updated_at"]


class FaqSerializer(serializers.ModelSerializer):
    class Meta:
        model = FaqEntry
        fields = ["id", "category", "question", "answer", "to_validate", "is_demo"]


class NewsListSerializer(serializers.ModelSerializer):
    cover = serializers.SerializerMethodField()

    class Meta:
        model = NewsArticle
        fields = ["slug", "title", "summary", "category", "event_date", "published_at", "cover", "is_demo"]

    def get_cover(self, obj):
        cover = obj.cover
        if cover is None or cover.status != PublicationStatus.PUBLISHED or PUBLIC not in cover.audiences:
            return None  # never a link to an image the public may not see
        return ImageRefSerializer(cover).data


class NewsSerializer(NewsListSerializer):
    class Meta(NewsListSerializer.Meta):
        fields = [*NewsListSerializer.Meta.fields, "body"]


class LocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteLocation
        fields = ["id", "name", "description", "address_text", "is_main", "is_demo"]


# --- views ---------------------------------------------------------------------------


class SiteView(PublicView):
    def get(self, request, code):
        school = self.school()
        profile = SiteProfile.objects.filter(school=school).first()
        # Locations have no audience: a published location is public.
        locations = SiteLocation.objects.filter(school=school, status=PublicationStatus.PUBLISHED)
        return Response(
            {
                "school": {
                    "code": school.code,
                    "name": school.name,
                    "short_name": school.short_name or "",
                    "city": school.city,
                    "country": school.country,
                    "phone": school.phone or "",
                    "email": school.email or "",
                    "description": school.description or "",
                    "mission": school.mission or "",
                    "vision": school.vision or "",
                    "history": school.history or "",
                },
                "profile": {
                    "tagline": profile.tagline if profile else "",
                    "presentation": profile.presentation if profile else "",
                    "values": [v.strip() for v in (profile.values if profile else "").splitlines() if v.strip()],
                    "pedagogy": profile.pedagogy if profile else "",
                    "location_details": profile.location_details if profile else "",
                    # The street address is shown only once the school confirmed it.
                    "address": school.address if profile and profile.address_confirmed else "",
                    "address_confirmed": bool(profile and profile.address_confirmed),
                    "office_hours": profile.office_hours if profile else "",
                    "to_validate": bool(profile.to_validate) if profile else True,
                },
                "locations": LocationSerializer(locations, many=True).data,
                "levels": [
                    {"id": str(level.pk), "code": level.code, "name": level.name, "cycle": level.cycle}
                    for level in admissions.offered_levels(school)
                ],
                "years": [{"id": str(y.pk), "name": y.name} for y in admissions.offered_years(school)],
                "relationships": [{"value": v, "label": label} for v, label in GuardianRelationship.choices],
            }
        )


class PageList(PublicList):
    model, serializer_class, pagination_class = Page, PageListSerializer, None


class PageDetail(PublicView):
    def get(self, request, code, slug):
        page = get_object_or_404(published(Page.objects.filter(school=self.school()), PUBLIC), slug=slug)
        return Response(PageSerializer(page).data)


class FaqList(PublicList):
    model, serializer_class, pagination_class = FaqEntry, FaqSerializer, None


class NewsList(PublicList):
    model, serializer_class = NewsArticle, NewsListSerializer

    def get_queryset(self):
        return super().get_queryset().select_related("cover")


class NewsDetail(PublicView):
    def get(self, request, code, slug):
        rows = published(NewsArticle.objects.filter(school=self.school()), PUBLIC).select_related("cover")
        return Response(NewsSerializer(get_object_or_404(rows, slug=slug)).data)


class GalleryList(PublicList):
    model, serializer_class, pagination_class = ContentImage, ImageRefSerializer, None

    def get_queryset(self):
        return super().get_queryset().filter(in_gallery=True)


class ImageFile(PublicView):
    throttle_scope = "public-content"

    def get(self, request, code, pk):
        image = get_object_or_404(published(ContentImage.objects.filter(school=self.school()), PUBLIC), pk=pk)
        response = FileResponse(files.open_file(image.storage_path), content_type=image.mime_type)
        response["Cache-Control"] = "public, max-age=3600"
        response["X-Content-Type-Options"] = "nosniff"
        return response


# --- pre-enrollment --------------------------------------------------------------------


class PreEnrollmentInput(serializers.Serializer):
    guardian_first_name = serializers.CharField(max_length=100)
    guardian_last_name = serializers.CharField(max_length=100)
    guardian_phone = serializers.RegexField(r"^\+?[0-9 ()./-]{6,25}$", max_length=30)
    guardian_email = serializers.EmailField(max_length=254)
    relationship = serializers.ChoiceField(choices=GuardianRelationship.values)
    child_first_name = serializers.CharField(max_length=100)
    child_last_name = serializers.CharField(max_length=100)
    child_birth_date = serializers.DateField(required=False, allow_null=True)
    requested_level = serializers.UUIDField()
    requested_year = serializers.UUIDField()
    previous_school = serializers.CharField(max_length=200, required=False, allow_blank=True)
    comment = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    consent = serializers.BooleanField()
    # Honeypot: invisible to people, filled by naive bots. Any value -> the
    # request is "accepted" and silently dropped (the bot learns nothing).
    website = serializers.CharField(required=False, allow_blank=True, max_length=200)

    def validate_consent(self, value):
        if value is not True:
            raise serializers.ValidationError("The privacy notice must be accepted.")
        return value

    def validate_child_birth_date(self, value):
        from django.utils import timezone

        if value and not (timezone.localdate().year - 30 <= value.year <= timezone.localdate().year):
            raise serializers.ValidationError("Implausible date of birth.")
        return value


class PreEnrollmentCreate(PublicView):
    throttle_scope = "pre-enrollment"

    def post(self, request, code):
        school = self.school()
        data = PreEnrollmentInput(data=request.data)
        data.is_valid(raise_exception=True)
        if (data.validated_data.get("website") or "").strip():
            return Response({"received": True, "reference": None}, status=status.HTTP_202_ACCEPTED)
        created = admissions.submit(school, data=data.validated_data, ctx=ClientContext.from_request(request))
        # Only the family's own reference: nothing about other requests.
        return Response({"received": True, "reference": created.reference}, status=status.HTTP_202_ACCEPTED)


urlpatterns = [
    path("public/<str:code>/site/", SiteView.as_view(), name="public-site"),
    path("public/<str:code>/pages/", PageList.as_view(), name="public-pages"),
    path("public/<str:code>/pages/<slug:slug>/", PageDetail.as_view(), name="public-page"),
    path("public/<str:code>/faq/", FaqList.as_view(), name="public-faq"),
    path("public/<str:code>/news/", NewsList.as_view(), name="public-news"),
    path("public/<str:code>/news/<slug:slug>/", NewsDetail.as_view(), name="public-news-detail"),
    path("public/<str:code>/gallery/", GalleryList.as_view(), name="public-gallery"),
    path("public/<str:code>/images/<uuid:pk>/", ImageFile.as_view(), name="public-image"),
    path("public/<str:code>/pre-enrollments/", PreEnrollmentCreate.as_view(), name="public-pre-enrollment"),
]
