"""Fake of the self-service account endpoints (backend accounts/profile_api.py,
password change, sessions) for the desktop tests: the CONTRACT — editable
fields decided by the server, any other field refused per field (400),
photo content checked, password change revoking the OTHER sessions."""

import httpx

from .fake_comm import multipart

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class MeFake:
    def init_me(self):
        self.me_values = {"phone": "", "address": ""}
        self.me_photo = None
        self.me_password = "Ancien-Mot-2026!"
        self.me_patches = []
        self.me_sessions = [
            {"id": "s-this", "device_name": "Poste administration", "platform": "WINDOWS", "is_current": True},
            {"id": "s-phone", "device_name": "Pixel 7a", "platform": "ANDROID", "is_current": False},
        ]
        self.me_revoked_all = 0

    @staticmethod
    def _m_ok(data, status=200):
        return httpx.Response(status, json={"success": True, "data": data, "message": None, "meta": None})

    @staticmethod
    def _m_fail(status, code, details):
        return httpx.Response(
            status, json={"success": False, "error": {"code": code, "message": code, "details": details}}
        )

    def _me_profile(self):
        return {
            "first_name": "Ada",
            "last_name": "Admin",
            "email": "admin@school.local",
            "username": "admin",
            "phone": self.me_values["phone"],
            "has_photo": self.me_photo is not None,
            "school_name": "École Test",
            "school_code": "TEST01",
            "roles": self.roles,
            "parent": None,
            "employee": {"address": self.me_values["address"]},
            "editable": ["phone", "address"],
            "languages": {},
        }

    def _me(self, request, path, body):
        method = request.method
        if path == "auth/me/profile/":
            if method == "PATCH":
                self.me_patches.append(body)
                forbidden = [k for k in body if k not in ("phone", "address")]
                if forbidden:
                    return self._m_fail(
                        400,
                        "VALIDATION_ERROR",
                        {k: ["Ce champ ne peut pas être modifié depuis votre profil."] for k in forbidden},
                    )
                if any(c.isalpha() for c in body.get("phone", "")):
                    return self._m_fail(400, "VALIDATION_ERROR", {"phone": ["Numéro de téléphone invalide."]})
                self.me_values.update(body)
            return self._m_ok(self._me_profile())
        if path == "auth/me/photo/":
            if method == "GET":
                if self.me_photo is None:
                    return self._m_fail(404, "NOT_FOUND", None)
                return httpx.Response(200, content=self.me_photo, headers={"content-type": "image/jpeg"})
            if method == "DELETE":
                self.me_photo = None
                return self._m_ok(self._me_profile())
            _, files = multipart(request)
            content = files[0][2]
            if not content.startswith(PNG_MAGIC):
                return self._m_fail(400, "BUSINESS_RULE_VIOLATION", {"rule": "photo_invalid"})
            self.me_photo = content
            return self._m_ok(self._me_profile())
        if path == "auth/password/change/":
            if body.get("current_password") != self.me_password:
                return self._m_fail(400, "VALIDATION_ERROR", {"current_password": ["Current password is incorrect."]})
            self.me_password = body.get("new_password")
            self.me_sessions = [s for s in self.me_sessions if s["is_current"]]
            return self._m_ok(None)
        if path == "auth/sessions/":
            return self._m_ok(self.me_sessions)
        if path == "auth/sessions/revoke-all/":
            self.me_revoked_all += 1
            count = len(self.me_sessions)
            self.me_sessions = []
            return self._m_ok({"revoked_count": count})
        if path.startswith("auth/sessions/") and path.endswith("/revoke/"):
            sid = path.split("/")[2]
            self.me_sessions = [s for s in self.me_sessions if s["id"] != sid]
            return self._m_ok(None)
        return None
