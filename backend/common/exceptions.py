"""DRF exception handler producing the error envelope (spec §6).

Kept apart from `common.envelope` on purpose (ADR 0004): it needs
`rest_framework.views.exception_handler`, and importing `rest_framework.views`
triggers the import of DEFAULT_RENDERER_CLASSES (= common.envelope). Since that
import goes to a *different* module, no cycle exists. The EXCEPTION_HANDLER
setting itself is only resolved when an exception is handled, long after all
modules are loaded.
"""

from rest_framework.views import exception_handler

from .envelope import error_envelope


def envelope_exception_handler(exc, context):
    """Turns DRF errors into the error envelope with structured field errors."""
    response = exception_handler(exc, context)
    if response is None:
        # Unexpected exception: let Django return a 500 (and log it). Internal
        # details are never leaked to the client.
        return None

    detail = response.data
    if isinstance(detail, dict) and set(detail) == {"detail"}:
        # Non-field error, e.g. "Authentication credentials were not provided."
        response.data = error_envelope(str(detail["detail"]))
    else:
        # Validation error: keep the per-field structure for client forms.
        response.data = error_envelope("Validation error.", detail)
    return response
