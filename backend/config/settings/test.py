"""Settings used by pytest.

Still PostgreSQL (constraints must be tested on the real engine), but cache
and channel layer run in memory so tests do not depend on Redis state.
"""

from django.contrib.auth.hashers import Argon2PasswordHasher

from .base import *  # noqa: F403

DEBUG = False


class FastArgon2PasswordHasher(Argon2PasswordHasher):
    """Same algorithm (hashes still start with "argon2", tests still prove no
    plaintext / no MD5), but minimal cost parameters: the production cost
    (~0.17 s per hash) dominated the test suite's run time. Test-only."""

    time_cost = 1
    memory_cost = 8  # KiB, the minimum for parallelism=1
    parallelism = 1


PASSWORD_HASHERS = ["config.settings.test.FastArgon2PasswordHasher"]

# Tests run against the in-memory `db_test` service (docker-compose.yml), never
# against the development database. Both aliases (default + security_log, see
# ADR 0005) must point to it.
for _alias in DATABASES.values():  # noqa: F405
    _alias["HOST"] = env("TEST_POSTGRES_HOST", default="db_test")  # noqa: F405

CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

# Isolate uploaded files produced by tests.
MEDIA_ROOT = BASE_DIR / ".test-media"  # noqa: F405
