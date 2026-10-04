from django.urls import path

from . import views
from .activation_api import public_urlpatterns

app_name = "accounts"

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("refresh/", views.RefreshView.as_view(), name="refresh"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("me/", views.MeView.as_view(), name="me"),
    path("sessions/", views.SessionListView.as_view(), name="sessions"),
    path("sessions/revoke-all/", views.SessionRevokeAllView.as_view(), name="sessions-revoke-all"),
    path("sessions/<uuid:pk>/revoke/", views.SessionRevokeView.as_view(), name="session-revoke"),
    path("password/change/", views.PasswordChangeView.as_view(), name="password-change"),
    # Account activation by the person (ADR 0024): anonymous, throttled.
    *public_urlpatterns,
]
