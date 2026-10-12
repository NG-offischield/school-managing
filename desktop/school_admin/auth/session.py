"""Authentication through the EXISTING backend endpoints (no second system):

    POST /auth/login/    {identifier, password, device} -> access + refresh tokens
    POST /auth/refresh/  {refresh_token}                 -> rotated tokens
    POST /auth/logout/                                   -> revokes the session server-side
    GET  /auth/me/                                       -> identity, memberships, roles

The password is passed straight to the login request and not kept. This
client is the ADMINISTRATION desktop: an account without ADMIN /
SUPER_ADMIN role in its school is logged out right away (the server enforces
every permission anyway; this only avoids an unusable shell).
"""

from ..api.errors import ApiError, Forbidden
from ..i18n import Tr
from ..models import Identity
from .token_store import MemoryTokenStore


class NotAnAdministrator(Forbidden):
    default_message = Tr("Ce poste est réservé à l'administration de l'école.")


class AuthService:
    def __init__(self, api, device, *, persistent_store=None):
        self.api = api
        self.device = device
        self.persistent_store = persistent_store  # KeyringTokenStore, or None
        self.store = MemoryTokenStore()
        self.identity = None
        api.refresh_handler = self.refresh

    # --- login / restore ---------------------------------------------------------

    def login(self, identifier, password, *, remember=False):
        identifier = (identifier or "").strip()
        if not identifier or not password:
            raise ApiError("Identifiant et mot de passe obligatoires.", code="VALIDATION_ERROR")
        payload = {"identifier": identifier, "password": password, "device": self.device}
        tokens, _ = self.api.request("POST", "auth/login/", json=payload, auth=False)
        del password, payload  # nothing keeps the password once the request is sent
        self.store = self.persistent_store if (remember and self.persistent_store) else MemoryTokenStore()
        self._accept(tokens)
        return self._load_identity()

    def restore(self):
        """Resume a remembered session (refresh token in the OS vault)."""
        if self.persistent_store is None or not self.persistent_store.load():
            return None
        self.store = self.persistent_store
        if not self.refresh():
            self.persistent_store.clear()
            return None
        try:
            return self._load_identity()
        except ApiError:
            self._forget()
            return None

    def refresh(self):
        """Called by ApiClient on a 401: rotate the tokens once."""
        token = self.store.load()
        if not token:
            return False
        try:
            tokens, _ = self.api.request("POST", "auth/refresh/", json={"refresh_token": token}, auth=False)
        except ApiError:
            self._forget()
            return False
        self._accept(tokens)
        return True

    # --- logout ------------------------------------------------------------------

    def logout(self):
        """Revoke the session server-side (best effort when offline), then
        forget every token locally — always."""
        try:
            if self.api.access_token:
                self.api.request("POST", "auth/logout/", _retry=False)
        except ApiError:
            pass
        finally:
            self._forget()

    # --- internals -----------------------------------------------------------------

    def _accept(self, tokens):
        self.api.access_token = tokens["access_token"]
        self.store.save(tokens["refresh_token"])

    def _forget(self):
        self.api.access_token = None
        self.store.clear()
        if self.persistent_store is not None:
            self.persistent_store.clear()
        self.identity = None

    def _load_identity(self):
        identity = Identity.from_me(self.api.get("auth/me/"))
        if not identity.is_admin:
            self.logout()
            raise NotAnAdministrator()
        self.identity = identity
        return identity

    @property
    def authenticated(self):
        return self.identity is not None and bool(self.api.access_token)
