"""Account lifecycle part of the fake API (mixin of FakeBackend, ADR 0024):
admin state / code / revoke / disable / enable on a membership, with the
rules the desktop must surface (409 account_already_active, account_disabled,
no_pending_activation; 404 for another school's member)."""

import secrets

import httpx

NOW = "2026-03-04T10:00:00+01:00"
LATER = "2026-03-07T10:00:00+01:00"


class AccountsFake:
    def init_accounts(self):
        self.accounts = {}  # membership id -> {"state", "login", "name", "codes": [...], "last_code"}

    def account_for(self, teacher_id):
        member = f"mem-{teacher_id}"
        if member not in self.accounts:
            teacher = self.teachers[teacher_id]
            self.accounts[member] = {
                "state": "NOT_ACTIVATED",
                "login": teacher["email"],
                "name": f"{teacher['first_name']} {teacher['last_name']}",
                "codes": [],
            }
        return member

    def _summary(self, member):
        row = self.accounts[member]
        return {
            "membership": member,
            "name": row["name"],
            "login": row["login"],
            "state": row["state"],
            "last_login": None,
            "pending_expires_at": LATER if row["state"] == "PENDING_ACTIVATION" else None,
            "last_issued_at": NOW if row["codes"] else None,
            "activated_at": NOW if row["state"] == "ACTIVE" else None,
        }

    def _a_ok(self, data, status=200):
        return httpx.Response(status, json={"success": True, "data": data, "message": None, "meta": None})

    def _a_fail(self, status, code, rule=None):
        error = {"code": code, "message": code}
        if rule:
            error["details"] = {"rule": rule}
        return httpx.Response(status, json={"success": False, "error": error})

    def _accounts(self, request, path, body, admin):
        if not admin:
            return self._a_fail(403, "PERMISSION_DENIED")
        parts = path.split("/")  # admin, accounts, <member>, [action, [revoke]], ''
        member = parts[2] if len(parts) > 2 else None
        if member not in self.accounts:
            return self._a_fail(404, "NOT_FOUND")
        row = self.accounts[member]
        action = "/".join(p for p in parts[3:] if p)
        if action == "":
            return self._a_ok(self._summary(member))
        if action == "activation":
            if row["state"] == "ACTIVE":
                return self._a_fail(409, "CONFLICT", "account_already_active")
            if row["state"] == "DISABLED":
                return self._a_fail(409, "CONFLICT", "account_disabled")
            code = "-".join(secrets.token_hex(2).upper() for _ in range(5))
            row["codes"].append(code)
            row["state"] = "PENDING_ACTIVATION"
            return self._a_ok({"code": code, "expires_at": LATER, "account": self._summary(member)}, 201)
        if action == "activation/revoke":
            if row["state"] != "PENDING_ACTIVATION":
                return self._a_fail(409, "CONFLICT", "no_pending_activation")
            row["state"] = "NOT_ACTIVATED"
            return self._a_ok(self._summary(member))
        if action == "disable":
            if not (body or {}).get("reason"):
                return self._a_fail(400, "VALIDATION_ERROR")
            row["state"] = "DISABLED"
            return self._a_ok(self._summary(member))
        if action == "enable":
            if row["state"] != "DISABLED":
                return self._a_fail(409, "CONFLICT", "account_not_disabled")
            row["state"] = "NOT_ACTIVATED"
            return self._a_ok(self._summary(member))
        return None
