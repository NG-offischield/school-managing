"""Hardened settings for a real deployment.

Production deployment itself is out of scope for Phase 1, but the secure
defaults are written now so they are never "forgotten later".
"""

from .base import *  # noqa: F403

DEBUG = False

# Cookies only travel over HTTPS and are not readable from JavaScript.
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True

# Redirect HTTP to HTTPS and tell browsers to stay on HTTPS (HSTS).
# Kept configurable because a pure-LAN demo may not have a TLS certificate yet.
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)  # noqa: F405
SECURE_HSTS_SECONDS = env.int("DJANGO_SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 30)  # noqa: F405
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
