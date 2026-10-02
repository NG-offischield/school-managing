"""DRF authentication backend for `Authorization: Bearer <access token>`."""

import uuid

from rest_framework import authentication, exceptions

from .models import UserSession
from .tokens import read_access_token


class SessionTokenAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).split()
        if not header or header[0].decode().lower() != self.keyword.lower():
            # No credentials: let permission classes decide (401 if required).
            return None
        if len(header) != 2:
            raise exceptions.AuthenticationFailed("Invalid authorization header.")

        session_id = read_access_token(header[1].decode())
        try:
            session_uuid = uuid.UUID(session_id) if session_id else None
        except ValueError:
            session_uuid = None
        if session_uuid is None:
            raise exceptions.AuthenticationFailed("Invalid or expired access token.")

        session = UserSession.objects.select_related("user").filter(pk=session_uuid).first()
        # The DB check is what makes logout/revocation effective immediately.
        if session is None or not session.is_usable():
            raise exceptions.AuthenticationFailed("Session expired or revoked.")

        # request.user = the person, request.auth = the session (used by logout).
        return session.user, session

    def authenticate_header(self, request):
        # Makes DRF answer 401 (not 403) when credentials are missing/invalid.
        return self.keyword
