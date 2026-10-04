"""Where the refresh token is kept between two launches ("rester connecté").

- the PASSWORD is never stored anywhere: it only lives in the login form
  until the request is sent;
- the access token stays in memory (short-lived, 15 min by default);
- the refresh token is kept only if the user ticks "rester connecté", in
  the OS credential vault (Windows Credential Manager...) through `keyring`
  — never in a plain file. The backend rotates it at every refresh and
  revokes it at logout.
"""

import keyring
from keyring.errors import KeyringError

SERVICE = "SchoolManagingDesktop"


class MemoryTokenStore:
    """Nothing survives the process (default when not remembering)."""

    def __init__(self):
        self._value = None

    def load(self):
        return self._value

    def save(self, refresh_token):
        self._value = refresh_token

    def clear(self):
        self._value = None


class KeyringTokenStore:
    """One entry per backend URL in the OS vault."""

    def __init__(self, api_url):
        self.account = f"refresh-token@{api_url}"

    def load(self):
        try:
            return keyring.get_password(SERVICE, self.account)
        except KeyringError:
            return None

    def save(self, refresh_token):
        try:
            keyring.set_password(SERVICE, self.account, refresh_token)
        except KeyringError:
            pass  # no vault available: the session simply won't be remembered

    def clear(self):
        try:
            keyring.delete_password(SERVICE, self.account)
        except KeyringError:
            pass
