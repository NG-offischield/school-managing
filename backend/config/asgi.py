"""ASGI entry point: serves both HTTP (Django) and WebSockets (Channels).

WebSocket consumers will be added by later phases (notifications, scans...).
They must enforce the same authorization scope as REST (spec §9), which is why
the router is wrapped in AllowedHostsOriginValidator from day one.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

# Django must be initialised before importing anything that touches models.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

websocket_urlpatterns = []  # populated in later phases

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        # Rejects WebSocket handshakes coming from origins not in ALLOWED_HOSTS
        # (protection against cross-site WebSocket hijacking).
        "websocket": AllowedHostsOriginValidator(URLRouter(websocket_urlpatterns)),
    }
)
