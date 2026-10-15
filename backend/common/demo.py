"""Read-only demonstration accounts (public demo, config.settings.demo).

The public demo hands out the credentials of fictitious accounts (Parent,
Teacher, Staff, Guardian) so that visitors can try the Espace ISBREE. A shared
password must not let one visitor change data for the others: change the
password, revoke everyone's sessions, post messages, request links…

For the accounts listed in DEMO_READ_ONLY_ACCOUNTS (username or e-mail), every
unsafe method (POST, PUT, PATCH, DELETE) is refused with 403 DEMO_READ_ONLY,
except signing in, refreshing the session and signing out. Reading stays
subject to the usual permissions: this only ever REMOVES rights.
Empty setting (development, tests, production) = the middleware does nothing.
"""

from django.conf import settings
from django.http import JsonResponse

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
ALLOWED_PATHS = ("/api/v1/auth/login/", "/api/v1/auth/refresh/", "/api/v1/auth/logout/")


def _demo_user(request):
    """The listed demo account behind the Bearer token, if any."""
    from apps.accounts.authentication import session_from_access_token

    header = request.META.get("HTTP_AUTHORIZATION", "").split()
    if len(header) != 2 or header[0].lower() != "bearer":
        return None
    session = session_from_access_token(header[1])
    if session is None:
        return None  # invalid token: DRF answers 401 as usual
    accounts = {a.lower() for a in settings.DEMO_READ_ONLY_ACCOUNTS}
    user = session.user
    return user if {user.username.lower(), (user.email or "").lower()} & accounts else None


class DemoReadOnlyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            getattr(settings, "DEMO_READ_ONLY_ACCOUNTS", None)
            and request.method not in SAFE_METHODS
            and request.path not in ALLOWED_PATHS
            and _demo_user(request) is not None
        ):
            return JsonResponse(
                {
                    "success": False,
                    "error": {
                        "code": "DEMO_READ_ONLY",
                        "message": "Compte de démonstration : consultation uniquement.",
                        "details": None,
                    },
                },
                status=403,
            )
        return self.get_response(request)
