"""WSGI entry point (HTTP only). The ASGI app (asgi.py) is the main one;
this file exists for tooling that expects WSGI."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

application = get_wsgi_application()
