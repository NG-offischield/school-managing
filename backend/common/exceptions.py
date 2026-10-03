"""DRF exception handler producing the error body of ADR 0007.

Kept apart from `common.envelope` / `common.errors` on purpose (ADR 0004):
it needs `rest_framework.views`, and importing `rest_framework.views`
triggers the import of DEFAULT_RENDERER_CLASSES (= common.envelope). Since
that is a *different* module, no import cycle exists.
"""

import logging
import math

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from django.http import Http404
from rest_framework import exceptions as drf
from rest_framework.response import Response
from rest_framework.views import exception_handler, set_rollback

from .errors import ApiError, ErrorCode, error_body

logger = logging.getLogger(__name__)

# Service rule codes that mean "conflicts with the current state" (stale data,
# duplicate code, row still in use) rather than "invalid input":
# answered 409 CONFLICT (optimistic concurrency, spec §6).
CONFLICT_RULES = {"stale_grade", "duplicate_code", "category_in_use", "subject_in_use"}

# Order matters: subclasses before their parents.
_CODES = [
    (drf.ValidationError, ErrorCode.VALIDATION_ERROR),
    (drf.ParseError, ErrorCode.PARSE_ERROR),
    (drf.NotAuthenticated, ErrorCode.NOT_AUTHENTICATED),
    (drf.AuthenticationFailed, ErrorCode.AUTHENTICATION_FAILED),
    (drf.PermissionDenied, ErrorCode.PERMISSION_DENIED),
    (drf.NotFound, ErrorCode.NOT_FOUND),
    (drf.MethodNotAllowed, ErrorCode.METHOD_NOT_ALLOWED),
    (drf.NotAcceptable, ErrorCode.NOT_ACCEPTABLE),
    (drf.UnsupportedMediaType, ErrorCode.UNSUPPORTED_MEDIA_TYPE),
    (drf.Throttled, ErrorCode.RATE_LIMITED),
]


def _code_for(exc):
    if isinstance(exc, ApiError):
        return exc.error_code
    for exc_class, code in _CODES:
        if isinstance(exc, exc_class):
            return code
    return ErrorCode.SERVER_ERROR


def _details_for(exc):
    if isinstance(exc, ApiError):
        return exc.details
    if isinstance(exc, drf.ValidationError):
        # Per-field messages (already translated by DRF/Django) for client forms.
        return exc.detail
    if isinstance(exc, drf.Throttled) and exc.wait is not None:
        return {"retry_after": math.ceil(exc.wait)}
    return None


def envelope_exception_handler(exc, context):
    # DRF's handler converts Http404 / Django PermissionDenied, sets the
    # WWW-Authenticate / Retry-After headers and marks the request transaction
    # for rollback; only the body is rewritten here.
    response = exception_handler(exc, context)

    if response is None and isinstance(exc, DjangoValidationError):
        # Business rule refused by a service (apps/*/services.py). The stable
        # rule code goes in details so clients can react to it.
        set_rollback()
        rule = getattr(exc, "code", None)
        details = {"rule": rule, "messages": exc.messages}
        if rule in CONFLICT_RULES:
            return Response(error_body(ErrorCode.CONFLICT, details), status=409)
        return Response(error_body(ErrorCode.BUSINESS_RULE_VIOLATION, details), status=400)

    if response is None and isinstance(exc, IntegrityError):
        # Refused by PostgreSQL (unique constraint, integrity trigger...).
        # The database message is logged, not returned (it names tables).
        logger.warning("Integrity error: %s", exc)
        set_rollback()
        return Response(error_body(ErrorCode.CONFLICT), status=409)

    if response is None:
        # Unexpected error: same JSON shape instead of an HTML 500 page, and no
        # internal detail leaked. set_rollback() is essential: with
        # ATOMIC_REQUESTS, returning a response would otherwise COMMIT the
        # half-done work of the failed request.
        logger.exception("Unhandled API error", exc_info=exc)
        set_rollback()
        return Response(error_body(ErrorCode.SERVER_ERROR), status=500)

    if isinstance(exc, Http404):
        exc = drf.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = drf.PermissionDenied()
    response.data = error_body(_code_for(exc), _details_for(exc))
    return response
