"""ASGI entry point: serves both HTTP (Django) and WebSockets (Channels).

WebSocket consumers enforce the same authorization scope as REST (spec §9):
bearer token of a usable session, tenant resolved like REST, permissions
re-checked by the consumer (apps/communication/consumers.py, ADR 0015).
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

# Django must be initialised before importing anything that touches models.
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402

from apps.communication.routing import websocket_urlpatterns  # noqa: E402
from common.websocket import BrowserOriginValidator  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        # Browser handshakes from origins not in ALLOWED_HOSTS are refused
        # (cross-site WebSocket hijacking); see common/websocket.py.
        "websocket": BrowserOriginValidator(URLRouter(websocket_urlpatterns)),
    }
)
