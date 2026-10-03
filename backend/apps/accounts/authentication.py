"""DRF authentication backend for `Authorization: Bearer <access token>`."""

import uuid

from rest_framework import authentication

from common.errors import ApiAuthenticationError

from .models import UserSession
from .tokens import read_access_token


def session_from_access_token(raw_token):
    """The usable UserSession of an access token, or None. Shared by REST
    (below) and the WebSocket consumer, so both accept exactly the same
    tokens and see revocation / logout immediately."""
    session_id = read_access_token(raw_token or "")
    try:
        session_uuid = uuid.UUID(session_id) if session_id else None
    except ValueError:
        return None
    if session_uuid is None:
        return None
    session = UserSession.objects.select_related("user").filter(pk=session_uuid).first()
    return session if session is not None and session.is_usable() else None


class SessionTokenAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).split()
        if not header or header[0].decode().lower() != self.keyword.lower():
            # No credentials: let permission classes decide (401 if required).
            return None
        if len(header) != 2:
            raise ApiAuthenticationError()

        # The DB check is what makes logout/revocation effective immediately.
        session = session_from_access_token(header[1].decode())
        if session is None:
            raise ApiAuthenticationError()

        # request.user = the person, request.auth = the session (used by logout).
        return session.user, session

    def authenticate_header(self, request):
        # Makes DRF answer 401 (not 403) when credentials are missing/invalid.
        return self.keyword
