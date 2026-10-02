"""Settings used by pytest.

Still PostgreSQL (constraints must be tested on the real engine), but cache
and channel layer run in memory so tests do not depend on Redis state.
"""

from .base import *  # noqa: F403

DEBUG = False

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

# Isolate uploaded files produced by tests.
MEDIA_ROOT = BASE_DIR / ".test-media"  # noqa: F405
