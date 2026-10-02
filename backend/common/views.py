from django.db import connection
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .permissions import ADMIN_ROLES, IsSchoolMember, membership_has_role
from .tenancy import get_active_membership, scope_to_current_school


class HealthView(APIView):
    """Liveness probe used by Docker / the admin client to check the server.

    Public on purpose, and returns no business data at all.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return Response({"status": "ok"})


class SchoolScopedMixin:
    """Base for every tenant-owned read endpoint.

    - authentication: the global default (Bearer session token);
    - permission: IsSchoolMember (ACTIVE membership in an ACTIVE school);
    - isolation: get_queryset() always starts from scope_to_current_school(),
      so an id of another school is a 404, identical to a missing id.

    Subclasses set `queryset` and may override `restrict(queryset)` to apply
    role-based visibility (e.g. a parent sees only their children).
    """

    permission_classes = [IsSchoolMember]
    queryset = None

    def restrict(self, queryset):
        return queryset

    def get_queryset(self):
        return self.restrict(scope_to_current_school(self.queryset.all(), self.request))

    def membership(self):
        return get_active_membership(self.request)

    def is_admin(self):
        return membership_has_role(self.membership(), ADMIN_ROLES)

    def uuid_param(self, name):
        """Optional UUID query parameter; a malformed value is a 400
        VALIDATION_ERROR, never a 500."""
        import uuid

        from rest_framework.exceptions import ValidationError

        raw = self.request.query_params.get(name)
        if not raw:
            return None
        try:
            return uuid.UUID(raw)
        except ValueError:
            raise ValidationError({name: ["Must be a valid UUID."]}) from None
