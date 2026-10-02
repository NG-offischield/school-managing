"""Root URL configuration.

All business endpoints live under /api/v1/ (spec §6). Media files are
intentionally NOT exposed through a public route: private attachments must
never be reachable by URL alone (spec §9); later phases will serve them through
permission-checked views.
"""

from django.contrib import admin
from django.urls import include, path

from common.views import HealthView

urlpatterns = [
    # Django admin = developer tool only. The real admin client is the PySide6
    # desktop application, which goes through the API (spec §2).
    path("django-admin/", admin.site.urls),
    path("api/v1/health/", HealthView.as_view(), name="health"),
    path("api/v1/auth/", include("apps.accounts.urls")),
    # School + Academic + People: read-only in this phase (ADR 0008).
    path("api/v1/", include("apps.core.api")),
    path("api/v1/", include("apps.academics.api")),
    path("api/v1/", include("apps.people.api")),
    path("api/v1/", include("apps.gradebook.api")),
]
