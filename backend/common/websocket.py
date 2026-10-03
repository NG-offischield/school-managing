"""WebSocket origin check (ADR 0015).

Cross-site WebSocket hijacking needs a BROWSER: a malicious page opens a
socket that the browser authenticates with ambient credentials. Browsers
always send `Origin`, so when it is present it must match ALLOWED_HOSTS.
Native clients (Flutter, PySide6) send no Origin and authenticate with an
explicit bearer token — there is no ambient credential to abuse — so a
missing Origin is accepted. (Channels' AllowedHostsOriginValidator refuses
it, which would lock the native clients out.)
"""

from channels.security.websocket import AllowedHostsOriginValidator, OriginValidator


class BrowserOriginValidator(OriginValidator):
    def __init__(self, application):
        allowed = AllowedHostsOriginValidator(application).allowed_origins
        super().__init__(application, allowed)

    def valid_origin(self, parsed_origin):
        if parsed_origin is None:
            return True
        return self.validate_origin(parsed_origin)
