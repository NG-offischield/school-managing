"""« Mon compte » of the connected administrator (backend accounts/profile_api.py
and the existing password / session endpoints). Thin client: the server says
which fields are editable and refuses any other; identity, e-mail, role and
school stay administrative (not editable here, not even by an admin for
themself).

    GET/PATCH auth/me/profile/      GET/POST/DELETE auth/me/photo/
    POST auth/password/change/ {current_password, new_password}  (other devices disconnected)
    GET auth/sessions/   POST auth/sessions/{id}/revoke/   POST auth/sessions/revoke-all/
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..api.errors import NotFound
from ..i18n import Labels, tr

FIELD_LABELS = Labels(
    {
        "phone": "Téléphone",
        "occupation": "Profession",
        "address": "Adresse",
        "emergency_phone": "Téléphone d'urgence",
        "preferred_language": "Langue préférée",
    }
)
PHOTO_FILTER = "Photos (*.jpg *.jpeg *.png *.webp)"


def _when(value):
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


@dataclass(frozen=True)
class MyProfile:
    first_name: str
    last_name: str
    email: str
    school_name: str
    roles: list
    has_photo: bool
    values: dict = field(default_factory=dict)
    editable: list = field(default_factory=list)
    languages: dict = field(default_factory=dict)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @classmethod
    def from_api(cls, data):
        values = {"phone": data.get("phone") or ""}
        for group in ("parent", "employee"):
            for key, value in (data.get(group) or {}).items():
                values[key] = value or ""
        return cls(
            first_name=data.get("first_name") or "",
            last_name=data.get("last_name") or "",
            email=data.get("email") or "",
            school_name=data.get("school_name") or "",
            roles=list(data.get("roles") or []),
            has_photo=bool(data.get("has_photo")),
            values=values,
            editable=list(data.get("editable") or []),
            languages=dict(data.get("languages") or {}),
        )


@dataclass(frozen=True)
class MySession:
    id: str
    device_name: str
    platform: str
    current: bool
    last_used_at: datetime | None

    @classmethod
    def from_api(cls, data):
        return cls(
            id=str(data["id"]),
            device_name=data.get("device_name") or tr("Appareil"),
            platform=data.get("platform") or "",
            current=bool(data.get("is_current")),
            last_used_at=_when(data.get("last_used_at") or data.get("created_at")),
        )


class MeService:
    def __init__(self, api):
        self.api = api

    def profile(self):
        return MyProfile.from_api(self.api.get("auth/me/profile/"))

    def update(self, changes):
        """Only the changed fields are sent; the server refuses any other."""
        return MyProfile.from_api(self.api.patch("auth/me/profile/", changes))

    def photo(self):
        try:
            return self.api.get_bytes("auth/me/photo/")
        except NotFound:
            return None

    def upload_photo(self, path):
        """Runs in the worker: only the bytes leave the computer (bare name, no local path)."""
        content = Path(path).read_bytes()
        data = self.api.post_multipart(
            "auth/me/photo/", {}, [("photo", ("photo", content, "application/octet-stream"))]
        )
        return MyProfile.from_api(data)

    def delete_photo(self):
        return MyProfile.from_api(self.api.delete("auth/me/photo/"))

    def change_password(self, current, new):
        self.api.post("auth/password/change/", {"current_password": current, "new_password": new})

    def sessions(self):
        return [MySession.from_api(row) for row in self.api.get("auth/sessions/") or []]

    def revoke(self, session_id):
        self.api.post(f"auth/sessions/{session_id}/revoke/")

    def revoke_all(self):
        return (self.api.post("auth/sessions/revoke-all/") or {}).get("revoked_count", 0)
