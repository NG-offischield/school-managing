"""Gate guardians, for the administration (PySide6 « Vie scolaire → Gardiens »).

    GET  /admin/guardians/          ?search= ?status=ACTIVE|SUSPENDED   (paginated)
    POST /admin/guardians/          {first_name, last_name, email, guardian_number, phone?}
    GET  /admin/guardians/{id}/     + today's scans count, last scan

Creation goes through people.services.admin_create_guardian (account WITHOUT
password, role GUARDIAN, profile; audited). Everything else reuses what
exists, never a second mechanism:
    activation code     POST /admin/accounts/{membership}/activation/   (ADR 0024)
    suspend / reactivate POST /admin/accounts/{membership}/disable/ {reason} | /enable/
    the guardian's scans GET /admin/scans/?guardian={id}
Administrators only; another school's guardian is a 404.
"""

from django.db.models import Count, Max, Q
from django.urls import path
from django.utils import timezone
from rest_framework import generics, serializers, status
from rest_framework.response import Response

from apps.attendance import services as attendance
from common.permissions import ADMIN_ROLES, HasSchoolRole
from common.views import SchoolScopedMixin

from . import services
from .models import GuardianProfile


class GuardianAdminSerializer(serializers.ModelSerializer):
    membership = serializers.UUIDField(source="membership_id", read_only=True)
    first_name = serializers.CharField(source="membership.user.first_name", read_only=True)
    last_name = serializers.CharField(source="membership.user.last_name", read_only=True)
    email = serializers.CharField(source="membership.user.email", read_only=True)
    phone = serializers.CharField(source="membership.user.phone", read_only=True, default=None)
    account_status = serializers.CharField(source="membership.status", read_only=True)
    activated = serializers.SerializerMethodField()
    scans_today = serializers.IntegerField(read_only=True, default=0)
    last_scan_at = serializers.DateTimeField(read_only=True, default=None)

    class Meta:
        model = GuardianProfile
        fields = [
            "id",
            "membership",
            "guardian_number",
            "status",
            "first_name",
            "last_name",
            "email",
            "phone",
            "account_status",
            "activated",
            "scans_today",
            "last_scan_at",
        ]

    def get_activated(self, obj):
        """The person has set their password (activation code used)."""
        return obj.membership.user.has_usable_password()


class GuardianInput(serializers.Serializer):
    first_name = serializers.CharField(max_length=120)
    last_name = serializers.CharField(max_length=120)
    email = serializers.EmailField()
    guardian_number = serializers.CharField(max_length=50)
    phone = serializers.CharField(max_length=40, required=False, allow_blank=True)


class GuardianScope(SchoolScopedMixin):
    permission_classes = [HasSchoolRole]
    required_roles = ADMIN_ROLES
    queryset = GuardianProfile.objects.select_related("membership__user")
    serializer_class = GuardianAdminSerializer

    def restrict(self, queryset):
        school = self.membership().school
        start, end = attendance.day_window(school, timezone.localdate())
        return queryset.annotate(
            scans_today=Count("scans", filter=Q(scans__scanned_at__gte=start, scans__scanned_at__lt=end)),
            last_scan_at=Max("scans__scanned_at"),
        )


class GuardianListCreate(GuardianScope, generics.ListAPIView):
    def restrict(self, queryset):
        queryset = super().restrict(queryset)
        search = (self.request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(
                Q(guardian_number__icontains=search)
                | Q(membership__user__first_name__icontains=search)
                | Q(membership__user__last_name__icontains=search)
                | Q(membership__user__email__icontains=search)
            )
        account = self.request.query_params.get("status")
        if account:
            queryset = queryset.filter(membership__status=account)
        return queryset.order_by("membership__user__last_name", "membership__user__first_name")

    def post(self, request):
        data = GuardianInput(data=request.data)
        data.is_valid(raise_exception=True)
        guardian = services.admin_create_guardian(
            self.membership().school, actor=self.membership(), **data.validated_data
        )
        guardian = self.get_queryset().get(pk=guardian.pk)
        return Response(GuardianAdminSerializer(guardian).data, status=status.HTTP_201_CREATED)


class GuardianDetail(GuardianScope, generics.RetrieveAPIView):
    pass


urlpatterns = [
    path("admin/guardians/", GuardianListCreate.as_view(), name="admin-guardians"),
    path("admin/guardians/<uuid:pk>/", GuardianDetail.as_view(), name="admin-guardian"),
]
