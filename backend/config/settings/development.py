"""Local / LAN development settings."""

from .base import *  # noqa: F403

DEBUG = True

# Browsable API is convenient while developing; production only returns JSON.
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [  # noqa: F405
    "common.envelope.EnvelopeJSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
]
