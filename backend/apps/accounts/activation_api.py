"""Account lifecycle API (ADR 0024). Three clearly separate families:

Administration (ADMIN / SUPER_ADMIN of the school; another school's member = 404):
    GET  /admin/accounts/{membership}/                    state (never a code)
    POST /admin/accounts/{membership}/activation/         new single-use code, returned ONCE
    POST /admin/accounts/{membership}/activation/revoke/
    POST /admin/accounts/{membership}/disable/ {reason}   POST /admin/accounts/{membership}/enable/

Activation by the person (anonymous, throttled "auth-activation"):
    POST /auth/activation/check/    {code}             -> first name, school, login, expiry
    POST /auth/activation/complete/ {code, password}   -> first password set; then the normal login
    Every refusal of a code: 400 INVALID_ACTIVATION_CODE (same answer whatever the reason).

Normal authentication is unchanged (/auth/login/, /auth/refresh/, /auth/logout/).
No endpoint ever receives a password from the administration.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.urls import path
from django.utils.decorators import method_decorator
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from common.errors import ApiError, ErrorCode
from common.permissions import ADMIN_ROLES, HasSchoolRole
from common.tenancy import scope_to_current_school
from common.views import SchoolScopedMixin

from . import activation
from .models import SchoolMembership
from .services import ClientContext


class AdminAccountMixin(SchoolScopedMixin):
    permission_classes = [HasSchoolRole]
    required_roles = ADMIN_ROLES

    def target(self, pk):
        """A member of the CURRENT school only (another school's id = 404)."""
        queryset = scope_to_current_school(SchoolMembership.objects.select_related("user", "school"), self.request)
        return get_object_or_404(queryset, pk=pk)


class AccountDetail(AdminAccountMixin, APIView):
    def get(self, request, pk):
        return Response(activation.account_summary(self.target(pk)))


class ActivationIssue(AdminAccountMixin, APIView):
    def post(self, request, pk):
        issued, code = activation.issue_activation(
            self.target(pk), actor=self.membership(), ctx=ClientContext.from_request(request)
        )
        response = Response(
            {"code": code, "expires_at": issued.expires_at, "account": activation.account_summary(issued.membership)},
            status=status.HTTP_201_CREATED,
        )
        response["Cache-Control"] = "no-store"  # the code is shown once, never cached
        return response


class ActivationRevoke(AdminAccountMixin, APIView):
    def post(self, request, pk):
        target = self.target(pk)
        activation.revoke_activation(target, actor=self.membership(), ctx=ClientContext.from_request(request))
        return Response(activation.account_summary(target))


class ReasonInput(serializers.Serializer):
    reason = serializers.CharField(max_length=500)


class AccountDisable(AdminAccountMixin, APIView):
    def post(self, request, pk):
        data = ReasonInput(data=request.data)
        data.is_valid(raise_exception=True)
        target = activation.disable_account(
            self.target(pk),
            actor=self.membership(),
            reason=data.validated_data["reason"],
            ctx=ClientContext.from_request(request),
        )
        return Response(activation.account_summary(target))


class AccountEnable(AdminAccountMixin, APIView):
    def post(self, request, pk):
        target = activation.enable_account(
            self.target(pk), actor=self.membership(), ctx=ClientContext.from_request(request)
        )
        return Response(activation.account_summary(target))


# --- the person -----------------------------------------------------------------------


class CodeInput(serializers.Serializer):
    code = serializers.CharField(max_length=64, write_only=True)


class CompleteInput(CodeInput):
    # trim_whitespace=False: spaces can be part of a password.
    password = serializers.CharField(max_length=256, trim_whitespace=False, write_only=True)


class PublicActivationView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth-activation"

    @staticmethod
    def refused():
        return ApiError(ErrorCode.INVALID_ACTIVATION_CODE, status.HTTP_400_BAD_REQUEST)


class ActivationCheck(PublicActivationView):
    def post(self, request):
        data = CodeInput(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            return Response(
                activation.check_activation(data.validated_data["code"], ctx=ClientContext.from_request(request))
            )
        except activation.InvalidActivation:
            raise self.refused() from None


# Not wrapped in the request transaction: a refusal is logged (security_log
# connection) and the burnt code is committed by the service's own atomic block.
@method_decorator(transaction.non_atomic_requests, name="dispatch")
class ActivationComplete(PublicActivationView):
    def post(self, request):
        data = CompleteInput(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            result = activation.complete_activation(
                data.validated_data["code"], data.validated_data["password"], ctx=ClientContext.from_request(request)
            )
        except activation.InvalidActivation:
            raise self.refused() from None
        except DjangoValidationError as exc:  # weak password: the code stays usable
            raise serializers.ValidationError({"password": exc.messages}) from None
        return Response(result)


admin_urlpatterns = [
    path("admin/accounts/<uuid:pk>/", AccountDetail.as_view()),
    path("admin/accounts/<uuid:pk>/activation/", ActivationIssue.as_view()),
    path("admin/accounts/<uuid:pk>/activation/revoke/", ActivationRevoke.as_view()),
    path("admin/accounts/<uuid:pk>/disable/", AccountDisable.as_view()),
    path("admin/accounts/<uuid:pk>/enable/", AccountEnable.as_view()),
]

public_urlpatterns = [
    path("activation/check/", ActivationCheck.as_view(), name="activation-check"),
    path("activation/complete/", ActivationComplete.as_view(), name="activation-complete"),
]
urlpatterns = admin_urlpatterns
