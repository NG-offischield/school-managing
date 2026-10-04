"""Account lifecycle (backend accounts/activation_api.py, ADR 0024). Thin
client: the server creates the single-use activation code, stores only its
hash and returns it ONCE; this module hands it to the screen and never keeps
or logs it. The person sets their own first password themselves (public
activation endpoint, e.g. the mobile app) — the administration never sees
or sends a password.

    GET  /admin/accounts/{membership}/
    POST /admin/accounts/{membership}/activation/          -> {code, expires_at, account}
    POST /admin/accounts/{membership}/activation/revoke/
    POST /admin/accounts/{membership}/disable/ {reason}    POST /admin/accounts/{membership}/enable/
"""

from dataclasses import dataclass
from datetime import datetime

from ..api.errors import ValidationFailed
from ..models import AccountSummary


@dataclass(frozen=True)
class IssuedCode:
    code: str  # shown once on screen, never stored by the desktop
    expires_at: datetime | None
    account: AccountSummary

    def __repr__(self):  # never leaks the code into logs or tracebacks
        return f"IssuedCode(expires_at={self.expires_at!r}, account={self.account.membership_id!r})"


class AccountService:
    def __init__(self, api):
        self.api = api

    def summary(self, membership_id):
        return AccountSummary.from_api(self.api.get(f"admin/accounts/{membership_id}/"))

    def issue_code(self, membership_id):
        data = self.api.post(f"admin/accounts/{membership_id}/activation/")
        expires = data.get("expires_at")
        return IssuedCode(
            data["code"],
            datetime.fromisoformat(expires) if expires else None,
            AccountSummary.from_api(data["account"]),
        )

    def revoke_code(self, membership_id):
        return AccountSummary.from_api(self.api.post(f"admin/accounts/{membership_id}/activation/revoke/"))

    def disable(self, membership_id, reason):
        if not (reason or "").strip():
            raise ValidationFailed("Formulaire incomplet.", details={"reason": ["Indiquez le motif."]})
        return AccountSummary.from_api(
            self.api.post(f"admin/accounts/{membership_id}/disable/", {"reason": reason.strip()})
        )

    def enable(self, membership_id):
        return AccountSummary.from_api(self.api.post(f"admin/accounts/{membership_id}/enable/"))
