"""Configuration shared by every environment.

Secrets and machine-specific values are NEVER written here: they come from
environment variables (or a git-ignored `.env` file) through django-environ.
"""

from datetime import timedelta
from pathlib import Path

import environ

# backend/ directory (this file lives in backend/config/settings/).
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
# Load the repository-level .env if present (local runs outside Docker).
# Inside Docker the variables are injected by docker-compose `env_file`.
_ENV_FILE = BASE_DIR.parent / ".env"
if _ENV_FILE.exists() and _ENV_FILE.read_bytes().startswith(b"\xef\xbb\xbf"):
    # Windows PowerShell 5.1 writes UTF-8 *with BOM*. django-environ would then
    # silently drop the first variable (its name starts with an invisible
    # character). Docker Compose tolerates the BOM, local runs do not: fail
    # loudly instead of starting with a missing setting.
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured(f"{_ENV_FILE} starts with a UTF-8 BOM: re-save it as UTF-8 without BOM.")
environ.Env.read_env(_ENV_FILE, overwrite=False)

# No default value on purpose: starting without a secret key must fail loudly
# instead of silently running with a guessable one.
SECRET_KEY = env("DJANGO_SECRET_KEY")

DEBUG = False
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])


# --- Applications -------------------------------------------------------------

INSTALLED_APPS = [
    # Must be first: replaces `runserver` with an ASGI server so WebSockets
    # work in development exactly as in production.
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "rest_framework",
    "channels",
    # PostgreSQL-specific features: exclusion constraints, range types (ADR 0008).
    "django.contrib.postgres",
    # Domain apps (spec UML 06 - package diagram). Phase 1 only ships the
    # tenant core and identity; the other domains arrive in later phases.
    "apps.core",
    "apps.accounts",
    "apps.academics",
    "apps.people",
    "apps.gradebook",
    "apps.audit",
    "apps.attendance",
    "apps.scheduling",
    "apps.finance",
    "apps.payroll",
    "apps.communication",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # Picks the language of user-facing messages from Accept-Language
    # (fr by default, en available) — ADR 0007. Must sit after
    # SessionMiddleware and before CommonMiddleware.
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


# --- Database -----------------------------------------------------------------
# PostgreSQL only. SQLite is explicitly forbidden by the spec: its constraint
# and timezone behaviour differs and would hide bugs until production.

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB"),
        "USER": env("POSTGRES_USER"),
        "PASSWORD": env("POSTGRES_PASSWORD"),
        "HOST": env("POSTGRES_HOST", default="localhost"),
        "PORT": env("POSTGRES_PORT", default="5432"),
        # Each HTTP request runs in a transaction: a failure half-way through a
        # business operation can never leave partially written data.
        "ATOMIC_REQUESTS": True,
    }
}

# Second connection to the SAME database, dedicated to the security log
# (ADR 0005). It runs in autocommit and is never part of a request transaction:
# a security event written through it is committed immediately and survives a
# rollback of the business transaction that caused it (failed login, rejected
# refresh, refused bootstrap...). Routing is done by common.db_routers.
DATABASES["security_log"] = {
    **DATABASES["default"],
    "ATOMIC_REQUESTS": False,
    # Tests: no separate test database; point to the default test database.
    "TEST": {"MIRROR": "default"},
}
DATABASE_ROUTERS = ["common.db_routers.SecurityLogRouter"]

# UUID primary keys are declared explicitly on every model (common.models);
# this default only applies to third-party models.
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --- Identity & passwords -----------------------------------------------------

AUTH_USER_MODEL = "accounts.User"

# Argon2 first: new passwords are hashed with it. The others stay only so that
# Django can still verify (and transparently upgrade) hashes it created itself.
# MD5-based hashers are deliberately absent (spec §9).
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Lifetimes of the API tokens (see apps/accounts/tokens.py and ADR 0002).
ACCESS_TOKEN_LIFETIME = timedelta(minutes=env.int("ACCESS_TOKEN_LIFETIME_MINUTES", default=15))
REFRESH_TOKEN_LIFETIME = timedelta(days=env.int("REFRESH_TOKEN_LIFETIME_DAYS", default=30))


# --- Internationalisation -----------------------------------------------------
# V1 school is in Cameroon (spec: School.timezone default Africa/Douala).

LANGUAGE_CODE = "fr"  # V1 default language (ADR 0007)
LANGUAGES = [("fr", "Français"), ("en", "English")]
# Our own translations (API error messages...). Source strings are English;
# French lives in backend/locale/fr. Compiled .mo files are committed so the
# bind-mounted source tree works without running compilemessages first.
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Africa/Douala"
USE_I18N = True
# Datetimes are stored as timestamptz (UTC) and converted for display only.
USE_TZ = True


# --- Static & media files -----------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Uploaded files go through Django's storage abstraction (spec §3): business
# code never builds file paths by hand, so storage can later move to an
# object store without code changes. Media is PRIVATE: it is not served by a
# public URL route (see config/urls.py).
MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "media/"

# Private files (attachments of messages and complaints, ADR 0015): a
# separate storage with no public route at all. Files are only streamed by
# views that check permissions first. Moving to an object store later means
# changing this backend, not the business code.
PRIVATE_MEDIA_ROOT = env("PRIVATE_MEDIA_ROOT", default=str(BASE_DIR / "private-media"))
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    "private": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": PRIVATE_MEDIA_ROOT},
    },
}
# Hard ceiling for any upload; the school's own limit
# (SchoolConfiguration.default_attachment_limit_mb) applies below it.
ATTACHMENT_MAX_BYTES = 25 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2_621_440


# --- Cache (rate limiting) ----------------------------------------------------
# Login throttling counters live in Redis so every server process shares them.

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("REDIS_URL", default="redis://localhost:6379/0"),
    }
}


# --- Real-time (Channels) -----------------------------------------------------

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [env("REDIS_URL", default="redis://localhost:6379/0")]},
    }
}


# --- REST API -----------------------------------------------------------------

REST_FRAMEWORK = {
    # Bearer tokens bound to a revocable UserSession (apps/accounts/authentication.py).
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.accounts.authentication.SessionTokenAuthentication",
    ],
    # Secure by default: an endpoint is private unless it explicitly opts out.
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    # Uniform `{success, data, message, meta}` envelope (spec §6).
    "DEFAULT_RENDERER_CLASSES": ["common.envelope.EnvelopeJSONRenderer"],
    "EXCEPTION_HANDLER": "common.exceptions.envelope_exception_handler",
    "DEFAULT_PAGINATION_CLASS": "common.envelope.EnvelopePagination",
    "PAGE_SIZE": 25,
    # Rate limits. `auth-login` protects against brute force (spec §9).
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/min",
        "user": "600/min",
        "auth-login": "10/min",
        "auth-refresh": "30/min",
        # Gate scanning: a busy gate scans many pupils per minute (ADR 0011).
        "qr-scan": "240/min",
    },
}


# --- Security headers common to all environments -------------------------------

X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"


# --- Logging ------------------------------------------------------------------
# Logs must never contain passwords, raw tokens or identity documents (spec §9):
# code logs identifiers (UUIDs), never credentials.

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "{asctime} {levelname} {name}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}
