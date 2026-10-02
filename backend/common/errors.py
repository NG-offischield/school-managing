"""Stable API error codes and their localisable messages (ADR 0007).

Error body:

    {"success": false,
     "error": {"code": "INVALID_CREDENTIALS", "message": "Identifiants incorrects."}}

- `code`: stable, technical English, never translated. Clients (Flutter,
  PySide6) branch on it; renaming one is a breaking API change.
- `message`: for humans, translated with Django i18n. Source strings are
  English (Django convention); French is the V1 default language and is
  provided by locale/fr. The client picks the language with Accept-Language.
- `details` (optional): structured complement, e.g. per-field validation
  errors or `retry_after` for rate limiting.

Like common.envelope, this module must not import rest_framework.views
(ADR 0004).
"""

from enum import StrEnum

from django.utils.translation import gettext_lazy as _
from rest_framework import status
from rest_framework.exceptions import APIException, AuthenticationFailed, PermissionDenied


class ErrorCode(StrEnum):
    # Generic
    VALIDATION_ERROR = "VALIDATION_ERROR"
    PARSE_ERROR = "PARSE_ERROR"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    NOT_ACCEPTABLE = "NOT_ACCEPTABLE"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    RATE_LIMITED = "RATE_LIMITED"
    SERVER_ERROR = "SERVER_ERROR"
    # Authentication
    NOT_AUTHENTICATED = "NOT_AUTHENTICATED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    # Error-code names, not secrets (silences the hardcoded-password lint rule).
    INVALID_ACCESS_TOKEN = "INVALID_ACCESS_TOKEN"  # noqa: S105
    INVALID_REFRESH_TOKEN = "INVALID_REFRESH_TOKEN"  # noqa: S105
    # Authorization / tenancy
    PERMISSION_DENIED = "PERMISSION_DENIED"
    NO_ACTIVE_MEMBERSHIP = "NO_ACTIVE_MEMBERSHIP"


ERROR_MESSAGES = {
    ErrorCode.VALIDATION_ERROR: _("Some fields are invalid."),
    ErrorCode.PARSE_ERROR: _("The request body is malformed."),
    ErrorCode.NOT_FOUND: _("Resource not found."),
    ErrorCode.METHOD_NOT_ALLOWED: _("This method is not allowed on this resource."),
    ErrorCode.NOT_ACCEPTABLE: _("The requested response format is not available."),
    ErrorCode.UNSUPPORTED_MEDIA_TYPE: _("Unsupported content type."),
    ErrorCode.RATE_LIMITED: _("Too many requests. Please try again later."),
    ErrorCode.SERVER_ERROR: _("An unexpected error occurred."),
    ErrorCode.NOT_AUTHENTICATED: _("Authentication is required."),
    ErrorCode.AUTHENTICATION_FAILED: _("Authentication failed."),
    ErrorCode.INVALID_CREDENTIALS: _("Invalid credentials."),
    ErrorCode.INVALID_ACCESS_TOKEN: _("Invalid or expired access token."),
    ErrorCode.INVALID_REFRESH_TOKEN: _("Invalid or expired refresh token."),
    ErrorCode.PERMISSION_DENIED: _("You do not have permission to perform this action."),
    ErrorCode.NO_ACTIVE_MEMBERSHIP: _("No active school membership for this request."),
}


class ApiError(APIException):
    """An API error carrying a stable code from the catalogue above.

    Raise it from views/services:  raise ApiError(ErrorCode.INVALID_CREDENTIALS, 401)
    """

    def __init__(self, code: ErrorCode, status_code=status.HTTP_400_BAD_REQUEST, details=None):
        self.error_code = code
        self.status_code = status_code
        self.details = details
        super().__init__(detail=ERROR_MESSAGES[code], code=code.value)


class ApiAuthenticationError(ApiError, AuthenticationFailed):
    """401 with WWW-Authenticate: DRF only keeps 401 (instead of turning it
    into 403) for subclasses of AuthenticationFailed / NotAuthenticated."""

    def __init__(self, code: ErrorCode = ErrorCode.INVALID_ACCESS_TOKEN):
        super().__init__(code, status.HTTP_401_UNAUTHORIZED)


class ApiPermissionError(ApiError, PermissionDenied):
    def __init__(self, code: ErrorCode = ErrorCode.PERMISSION_DENIED):
        super().__init__(code, status.HTTP_403_FORBIDDEN)


def error_body(code: ErrorCode, details=None):
    error = {"code": code.value, "message": str(ERROR_MESSAGES[code])}
    if details is not None:
        error["details"] = details
    return {"success": False, "error": error}
