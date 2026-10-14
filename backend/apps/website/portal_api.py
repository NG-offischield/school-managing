"""Espace ISBREE — portal API (ADR 0032). Authenticated members only (same
tokens and session checks as every API: a revoked session is refused).

    GET /portal/context/?role=            the chosen role context among the roles HELD, and what
                                          this role may read: pages, FAQ, news, general resources,
                                          applications, the family's pre-enrollment requests
    GET /portal/pages/{slug}/?role=       one page of that role
    GET /portal/resources/?role=&student= resources of that role, narrowed by the server:
                                          PARENT -> the chosen child's level / class / year (VERIFIED
                                          link only), TEACHER -> the classes of their active courses,
                                          STAFF -> their current functions, GUARDIAN -> general only
    GET /portal/resources/{id}/document/  the PDF of a resource the caller may read (same rules)
    GET /portal/apps/{id}/download/       a PUBLISHED release of an application whose role is HELD

The personal school data (children, timetables, courses, staff record) are
NOT copied here: the portal reads the existing endpoints (parents/children,
students/{id}/timetable, courses, teacher/sessions, staff), whose visibility
the server already enforces.

A role context never adds a permission: a role not held is a 403. Every
response is private and never cached (Cache-Control: private, no-store).
"""

from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import path
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied as ApiPermissionDenied
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.admissions.models import PreEnrollment
from apps.gradebook.models import Course
from apps.people.models import EnrollmentStatus, ParentStudent, StaffFunctionAssignment, StudentEnrollment
from common.views import SchoolScopedMixin

from . import files
from .models import (
    ANDROID_PACKAGES,
    FaqEntry,
    MobileApp,
    MobileAppRelease,
    NewsArticle,
    Page,
    ReleaseStatus,
    RoleResource,
)
from .public_api import FaqSerializer, ImageRefSerializer, PageListSerializer, PageSerializer
from .services import published, role_context, scoped_resources

NO_STORE = "private, no-store"


class PortalView(SchoolScopedMixin, APIView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = NO_STORE
        return response

    def context(self):
        from django.core.exceptions import PermissionDenied

        try:
            return role_context(self.membership(), self.request.query_params.get("role"))
        except PermissionDenied as exc:
            raise ApiPermissionDenied(str(exc)) from None


class NewsCardSerializer(serializers.ModelSerializer):
    cover = serializers.SerializerMethodField()

    class Meta:
        model = NewsArticle
        fields = ["slug", "title", "summary", "body", "category", "event_date", "published_at", "cover", "is_demo"]

    def get_cover(self, obj):
        role = self.context["role"]
        cover = obj.cover
        if cover is None or cover.status != "PUBLISHED" or not ({"PUBLIC", role} & set(cover.audiences)):
            return None
        return ImageRefSerializer(cover).data


class ResourceSerializer(serializers.ModelSerializer):
    level = serializers.CharField(source="level.name", default=None)
    school_class = serializers.CharField(source="school_class.name", default=None)
    academic_year = serializers.CharField(source="academic_year.name", default=None)
    staff_function = serializers.CharField(source="staff_function.name", default=None)
    has_document = serializers.SerializerMethodField()

    class Meta:
        model = RoleResource
        fields = [
            "id",
            "kind",
            "title",
            "body",
            "level",
            "school_class",
            "academic_year",
            "staff_function",
            "visible_until",
            "has_document",
            "document_name",
            "document_size",
            "to_validate",
            "is_demo",
        ]

    def get_has_document(self, obj):
        return bool(obj.document_path)


class ReleaseSerializer(serializers.ModelSerializer):
    label = serializers.CharField(source="get_app_display")
    package = serializers.SerializerMethodField()

    class Meta:
        model = MobileAppRelease
        fields = [
            "id",
            "app",
            "label",
            "package",
            "version_name",
            "version_code",
            "release_notes",
            "min_android",
            "size",
            "sha256",
            "published_at",
        ]

    def get_package(self, obj):
        return ANDROID_PACKAGES[obj.app]


def latest_releases(school, roles):
    """The newest PUBLISHED release of each application whose role is held."""
    out = []
    for app in [a for a in MobileApp.values if a in roles]:
        release = (
            MobileAppRelease.objects.filter(school=school, app=app, status=ReleaseStatus.PUBLISHED)
            .order_by("-version_code")
            .first()
        )
        out.append(
            {"app": app, "label": MobileApp(app).label, "release": ReleaseSerializer(release).data if release else None}
        )
    return out


class PortalContext(PortalView):
    def get(self, request):
        membership = self.membership()
        role, held = self.context()
        school = membership.school
        user = membership.user
        news = published(NewsArticle.objects.filter(school=school), role).select_related("cover")[:6]
        data = {
            "role": role,
            "roles": held,
            "user": {"first_name": user.first_name, "last_name": user.last_name},
            "school": {"name": school.name, "phone": school.phone or "", "email": school.email or ""},
            "pages": PageListSerializer(published(Page.objects.filter(school=school), role), many=True).data,
            "faq": FaqSerializer(published(FaqEntry.objects.filter(school=school), role), many=True).data,
            "news": NewsCardSerializer(news, many=True, context={"role": role}).data,
            # Teacher / staff: narrowed to their classes / functions; parent: general
            # ones (a child's resources need the child: /portal/resources/?student=).
            "resources": ResourceSerializer(resources_for(membership, role), many=True).data,
            # Applications of the roles HELD (a person with two roles may use two apps).
            "apps": latest_releases(school, held),
            "pre_enrollments": [],
        }
        if role == "PARENT":
            data["pre_enrollments"] = [
                {
                    "reference": r.reference,
                    "child": f"{r.child_first_name} {r.child_last_name}",
                    "level": r.requested_level.name,
                    "year": r.requested_year.name,
                    "status": r.status,
                    "status_label": r.get_status_display(),
                    "message": r.message_to_family,
                    "submitted_at": r.submitted_at,
                }
                for r in PreEnrollment.objects.filter(school=school, account=membership).select_related(
                    "requested_level", "requested_year"
                )
            ]
        return Response(data)


class PortalPage(PortalView):
    def get(self, request, slug):
        role, _ = self.context()
        rows = published(Page.objects.filter(school=self.membership().school), role)
        return Response(PageSerializer(get_object_or_404(rows, slug=slug)).data)


def child_scope(membership, student_id):
    """Level / class / year of a child linked to this parent by an ACTIVE,
    VERIFIED link — 404 otherwise (another family's child, an unverified
    link and an unknown id look the same)."""
    linked = ParentStudent.objects.filter(
        parent__membership=membership, student_id=student_id, active=True, identity_verified=True
    ).exists()
    if not linked:
        raise Http404
    enrollment = (
        StudentEnrollment.objects.filter(
            student_id=student_id, status=EnrollmentStatus.ACTIVE, academic_year__is_current=True
        )
        .select_related("school_class")
        .first()
    )
    if enrollment is None:
        return {"levels": (), "classes": (), "years": ()}
    klass = enrollment.school_class
    return {"levels": [klass.level_id], "classes": [klass.pk], "years": [enrollment.academic_year_id]}


def resources_for(membership, role, student_id=None):
    school = membership.school
    if role == "PARENT":
        scope = child_scope(membership, student_id) if student_id else {}
        return scoped_resources(school, role, **scope)
    if role == "TEACHER":
        courses = Course.objects.filter(teacher__employee__membership=membership, active=True).select_related(
            "school_class"
        )
        return scoped_resources(
            school,
            role,
            levels={c.school_class.level_id for c in courses},
            classes={c.school_class_id for c in courses},
            years={c.academic_year_id for c in courses},
        )
    if role == "STAFF":
        functions = StaffFunctionAssignment.objects.filter(
            staff__employee__membership=membership, active=True
        ).values_list("function_id", flat=True)
        return scoped_resources(school, role, functions=list(functions))
    return scoped_resources(school, role)


class PortalResources(PortalView):
    def get(self, request):
        role, _ = self.context()
        student = self.uuid_param("student")
        if student and role != "PARENT":
            raise ApiPermissionDenied("Only a parent context reads a child's resources.")
        rows = resources_for(self.membership(), role, student)
        return Response(ResourceSerializer(rows, many=True).data)


class ResourceDocument(PortalView):
    def get(self, request, pk):
        role, _ = self.context()
        student = self.uuid_param("student")
        resource = get_object_or_404(resources_for(self.membership(), role, student), pk=pk)
        if not resource.document_path:
            raise Http404
        response = FileResponse(
            files.open_file(resource.document_path),
            content_type="application/pdf",
            as_attachment=False,
            filename=resource.document_name or "document.pdf",
        )
        response["X-Content-Type-Options"] = "nosniff"
        return response


class AppDownload(PortalView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "app-download"

    def get(self, request, pk):
        membership = self.membership()
        _, held = self.context()  # the roles really held (403 without a portal role)
        release = get_object_or_404(
            MobileAppRelease.objects.filter(school=membership.school, status=ReleaseStatus.PUBLISHED), pk=pk
        )
        if release.app not in held:
            raise ApiPermissionDenied("This application is not for your role.")
        response = FileResponse(
            files.open_file(release.storage_path),
            content_type="application/vnd.android.package-archive",
            as_attachment=True,
            filename=f"isbree-{release.app.lower()}-{release.version_name}.apk",
        )
        response["X-Content-Type-Options"] = "nosniff"
        return response


urlpatterns = [
    path("portal/context/", PortalContext.as_view(), name="portal-context"),
    path("portal/pages/<slug:slug>/", PortalPage.as_view(), name="portal-page"),
    path("portal/resources/", PortalResources.as_view(), name="portal-resources"),
    path("portal/resources/<uuid:pk>/document/", ResourceDocument.as_view(), name="portal-resource-document"),
    path("portal/apps/<uuid:pk>/download/", AppDownload.as_view(), name="portal-app-download"),
]
