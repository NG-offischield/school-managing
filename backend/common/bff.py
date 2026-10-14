"""Client IP behind the ISBREE web servers (ADR 0032).

The public site and the portal are Next.js servers: browsers never call
Django directly, so every request reaches Django from the web server's
address. Without care, the per-IP rate limits (login brute force,
pre-enrollment spam, activation) would count ALL visitors as one.

X-Forwarded-For is not trusted (any direct client — the mobile apps call
Django directly — could forge it). Instead, a web server proves itself with a
server-to-server token (WEB_BFF_TOKEN, environment only, never sent to a
browser) and passes the visitor's address in X-ISBREE-Client-IP. Only then is
REMOTE_ADDR replaced, so DRF throttles, sessions and security events all see
the real visitor. Without the token (or with a wrong one), the headers are
ignored and dropped. WEB_BFF_TOKEN unset = the mechanism is off.
"""

import hmac
import ipaddress

from django.conf import settings

TOKEN_HEADER = "HTTP_X_ISBREE_BFF"  # noqa: S105 - a header name, not a secret
CLIENT_IP_HEADER = "HTTP_X_ISBREE_CLIENT_IP"


def _valid_ip(value):
    try:
        return str(ipaddress.ip_address((value or "").strip()))
    except ValueError:
        return None


class TrustedWebServerMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = request.META.pop(TOKEN_HEADER, "")
        client_ip = request.META.pop(CLIENT_IP_HEADER, "")
        expected = getattr(settings, "WEB_BFF_TOKEN", "")
        request.via_web_server = False
        if expected and token and hmac.compare_digest(token.encode(), expected.encode()):
            ip = _valid_ip(client_ip)
            if ip:
                request.META["REMOTE_ADDR"] = ip
            request.via_web_server = True
        return self.get_response(request)
