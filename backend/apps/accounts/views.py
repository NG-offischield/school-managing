"""Authentication & session endpoints (spec §6.2).

There is intentionally NO admin signup endpoint (spec §9): administrators are
created with the `bootstrap_school` management command or by another admin.
"""

from django.db import transaction
from django.utils.decorators import method_decorator
from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from common.errors import ApiError, ErrorCode

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
            # The LOGIN_FAILED event is already durable (dedicated connection,
            # ADR 0005), so raising (which rolls the request back) is safe.
            raise ApiError(ErrorCode.INVALID_CREDENTIALS, status.HTTP_401_UNAUTHORIZED) from None
        return Response(token_payload(issued), status=status.HTTP_200_OK)


# Excluded from ATOMIC_REQUESTS: when a reused refresh token is detected, the
# service revokes the session and then raises. Inside the request transaction
# that revocation would be rolled back with the error; here the service's own
# atomic block commits it first (ADR 0002).
@method_decorator(transaction.non_atomic_requests, name="dispatch")
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
            # Same answer whatever the reason (unknown, expired, revoked,
            # reused): details are only in the security log.
            raise ApiError(ErrorCode.INVALID_REFRESH_TOKEN, status.HTTP_401_UNAUTHORIZED) from None
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


class SessionRevokeAllView(APIView):
    """Global logout: revokes ALL active sessions of the caller, including the
    current one ("disconnect all my devices"). The access token used for this
    call stops working immediately.

    Administrative revocation of *another* user's sessions is not exposed yet:
    it will be a separate admin endpoint requiring ADMIN/SUPER_ADMIN in the
    target user's school, calling the same service with `actor=` (ADR 0002).
    """

    def post(self, request):
        count = services.revoke_all_sessions(request.user, ctx=ClientContext.from_request(request), actor=request.user)
        return Response({"revoked_count": count})


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
