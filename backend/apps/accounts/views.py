"""Authentication & session endpoints (spec §6.2).

There is intentionally NO admin signup endpoint (spec §9): administrators are
created with the `bootstrap_school` management command or by another admin.
"""

from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from common.envelope import error_response

from . import services
from .models import SecurityEventType
from .serializers import (
    LoginSerializer,
    MembershipSerializer,
    PasswordChangeSerializer,
    RefreshSerializer,
    SessionSerializer,
    token_payload,
)
from .services import ClientContext


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    # Brute-force protection: 10 attempts / minute / IP (settings).
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth-login"

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            issued = services.login(
                data["identifier"], data["password"], data["device"], ClientContext.from_request(request)
            )
        except services.InvalidCredentials:
            # The LOGIN_FAILED event is already durable (dedicated connection, ADR 0005).
            return error_response("Invalid credentials.", status.HTTP_401_UNAUTHORIZED)
        return Response(token_payload(issued), status=status.HTTP_200_OK)


class RefreshView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth-refresh"

    def post(self, request):
        serializer = RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            issued = services.refresh(serializer.validated_data["refresh_token"], ClientContext.from_request(request))
        except services.InvalidRefreshToken:
            return error_response("Invalid or expired refresh token.", status.HTTP_401_UNAUTHORIZED)
        return Response(token_payload(issued))


class LogoutView(APIView):
    def post(self, request):
        services.revoke_session(request.auth, ctx=ClientContext.from_request(request), reason=SecurityEventType.LOGOUT)
        return Response(None, status=status.HTTP_200_OK)


class MeView(APIView):
    """Current identity + its school memberships and roles."""

    def get(self, request):
        user = request.user
        memberships = user.memberships.select_related("school").order_by("-is_primary_school")
        return Response(
            {
                "id": str(user.id),
                "username": user.username,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "memberships": MembershipSerializer(memberships, many=True).data,
            }
        )


class SessionListView(APIView):
    """Lets a user see where they are logged in (multi-device security)."""

    def get(self, request):
        sessions = request.user.sessions.filter(revoked_at__isnull=True).select_related("device")
        return Response(SessionSerializer(sessions, many=True, context={"request": request}).data)


class SessionRevokeView(APIView):
    def post(self, request, pk):
        # Scoped to the current user: revoking someone else's session is a 404,
        # not a 403, so session ids of other users cannot be probed.
        session = get_object_or_404(request.user.sessions, pk=pk)
        services.revoke_session(session, ctx=ClientContext.from_request(request))
        return Response(None)


class PasswordChangeView(APIView):
    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        services.change_password(
            request.user,
            serializer.validated_data["new_password"],
            keep_session=request.auth,
            ctx=ClientContext.from_request(request),
        )
        return Response(None)
