"""Uniform API response envelope — renderer and pagination.

    success: {"success": true, "data": <payload>, "message": null, "meta": null}    (spec §6)
    list:    {"success": true, "data": [...], "message": null,
              "meta": {"count": .., "next": .., "previous": ..}}
    error:   {"success": false, "error": {"code": "...", "message": "..."}}     (ADR 0007)

Errors are built by common.errors / common.exceptions.

IMPORT RULE (see ADR 0004): this module is referenced by the
DEFAULT_RENDERER_CLASSES / DEFAULT_PAGINATION_CLASS settings. It must therefore
never import `rest_framework.views` (or anything importing it): `APIView`
reads DEFAULT_RENDERER_CLASSES while its class body executes, which would
import this module again while it is still half-initialised.
"""

from rest_framework.pagination import PageNumberPagination
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response


def _is_enveloped(data):
    return isinstance(data, dict) and "success" in data and ("data" in data or "error" in data)


class EnvelopeJSONRenderer(JSONRenderer):
    """Wraps any successful payload into the envelope."""

    def render(self, data, accepted_media_type=None, renderer_context=None):
        response = (renderer_context or {}).get("response")
        # Errors and paginated lists are already enveloped by the exception
        # handler / paginator: never wrap twice.
        if not _is_enveloped(data) and not (response is not None and response.status_code >= 400):
            data = {"success": True, "data": data, "message": None, "meta": None}
        return super().render(data, accepted_media_type, renderer_context)


class EnvelopePagination(PageNumberPagination):
    """Page-number pagination whose counters go into `meta`."""

    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response(
            {
                "success": True,
                "data": data,
                "message": None,
                "meta": {
                    "count": self.page.paginator.count,
                    "next": self.get_next_link(),
                    "previous": self.get_previous_link(),
                },
            }
        )
