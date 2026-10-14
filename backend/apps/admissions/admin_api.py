"""Pre-enrollment review (ADR 0032) — PySide6 desktop, ADMIN / SUPER_ADMIN of
the school only (family data). Ids of another school are 404.

    GET  /admin/pre-enrollments/        ?status= ?search= ?level= ?year=   (paginated)
    GET  /admin/pre-enrollments/{id}/   detail + history + invitation state
    POST /admin/pre-enrollments/{id}/status/   {status, note?, message_to_family?}
    POST /admin/pre-enrollments/{id}/invite/   -> {code, link, expires_at} ONCE (no-store)

The invitation code is returned once to the administrator and never stored
in clear nor logged; nothing is e-mailed by the server.
"""

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.urls import path
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from common.permissions import ADMIN_ROLES, HasSchoolRole
from common.views import SchoolScopedMixin

from . import services
from .models import PreEnrollment, PreEnrollmentEvent, PreEnrollmentStatus


class AdminMixin(SchoolScopedMixin):
    permission_classes = [HasSchoolRole]
    required_roles = ADMIN_ROLES

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        return response


class RequestSerializer(serializers.ModelSerializer):
    requested_level = serializers.CharField(source="requested_level.name")
    requested_year = serializers.CharField(source="requested_year.name")
    status_label = serializers.CharField(source="get_status_display")
    relationship_label = serializers.CharField(source="get_relationship_display")
    has_account = serializers.SerializerMethodField()

    class Meta:
        model = PreEnrollment
        fields = [
            "id",
            "reference",
            "guardian_first_name",
            "guardian_last_name",
            "guardian_phone",
            "guardian_email",
            "relationship",
            "relationship_label",
            "child_first_name",
            "child_last_name",
            "child_birth_date",
            "requested_level",
            "requested_year",
            "previous_school",
            "comment",
            "consent_at",
            "consent_version",
            "status",
            "status_label",
            "submitted_at",
            "decided_at",
            "message_to_family",
            "has_account",
        ]

    def get_has_account(self, obj):
        return obj.account_id is not None


class EventSerializer(serializers.ModelSerializer):
    actor = serializers.SerializerMethodField()

    class Meta:
        model = PreEnrollmentEvent
        fields = ["action", "from_status", "to_status", "note", "actor", "created_at"]

    def get_actor(self, obj):
        return obj.actor.user.full_name if obj.actor_id else None


class RequestList(AdminMixin, generics.ListAPIView):
    queryset = PreEnrollment.objects.select_related("requested_level", "requested_year")
    serializer_class = RequestSerializer

    def restrict(self, queryset):
        params = self.request.query_params
        if params.get("status"):
            if params["status"] not in PreEnrollmentStatus.values:
                raise serializers.ValidationError({"status": ["Unknown status."]})
            queryset = queryset.filter(status=params["status"])
        search = (params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(reference__icontains=search)
                | Q(guardian_last_name__icontains=search)
                | Q(guardian_first_name__icontains=search)
                | Q(child_last_name__icontains=search)
                | Q(child_first_name__icontains=search)
                | Q(guardian_email__icontains=search)
            )
        for name, field in (("level", "requested_level_id"), ("year", "requested_year_id")):
            value = self.uuid_param(name)
            if value:
                queryset = queryset.filter(**{field: value})
        return queryset


class RequestDetail(AdminMixin, APIView):
    def get(self, request, pk):
        row = get_object_or_404(self.get_queryset_for_admin(), pk=pk)
        state, invitation = services.invitation_state(row)
        return Response(
            {
                **RequestSerializer(row).data,
                "events": EventSerializer(row.events.select_related("actor__user"), many=True).data,
                "invitation": {
                    "state": state,
                    "expires_at": invitation.activation.expires_at if invitation else None,
                    "count": row.invitations.count(),
                },
                "allowed": sorted(services.TRANSITIONS.get(row.status, set())),
            }
        )

    def get_queryset_for_admin(self):
        return PreEnrollment.objects.filter(school=self.membership().school).select_related(
            "requested_level", "requested_year"
        )


class StatusInput(serializers.Serializer):
    status = serializers.ChoiceField(choices=PreEnrollmentStatus.values)
    note = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    message_to_family = serializers.CharField(required=False, allow_blank=True, max_length=500)


class RequestStatus(AdminMixin, APIView):
    def post(self, request, pk):
        row = get_object_or_404(PreEnrollment.objects.filter(school=self.membership().school), pk=pk)
        data = StatusInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        row = services.change_status(
            row,
            v["status"],
            actor=self.membership(),
            note=v.get("note", ""),
            message_to_family=v.get("message_to_family"),
        )  # a refused rule -> 400 BUSINESS_RULE_VIOLATION {rule} (common/exceptions.py)
        return Response(RequestSerializer(row).data)


class RequestInvite(AdminMixin, APIView):
    def post(self, request, pk):
        from apps.accounts.services import ClientContext

        row = get_object_or_404(PreEnrollment.objects.filter(school=self.membership().school), pk=pk)
        invitation, code, link = services.invite(row, actor=self.membership(), ctx=ClientContext.from_request(request))
        return Response(
            {"code": code, "link": link, "expires_at": invitation.activation.expires_at},
            status=status.HTTP_201_CREATED,
        )


urlpatterns = [
    path("admin/pre-enrollments/", RequestList.as_view()),
    path("admin/pre-enrollments/<uuid:pk>/", RequestDetail.as_view()),
    path("admin/pre-enrollments/<uuid:pk>/status/", RequestStatus.as_view()),
    path("admin/pre-enrollments/<uuid:pk>/invite/", RequestInvite.as_view()),
]
