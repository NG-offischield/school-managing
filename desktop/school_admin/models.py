"""Plain data objects built from API payloads (no business rule here)."""

from dataclasses import dataclass, field

ADMIN_ROLES = frozenset({"SUPER_ADMIN", "ADMIN"})


@dataclass(frozen=True)
class Identity:
    user_id: str
    username: str
    full_name: str
    school_code: str
    school_name: str
    roles: tuple

    @property
    def is_admin(self):
        return bool(ADMIN_ROLES & set(self.roles))

    @property
    def role_label(self):
        return "Super-administrateur" if "SUPER_ADMIN" in self.roles else "Administrateur"

    @classmethod
    def from_me(cls, me):
        """GET /auth/me/ -> identity in the primary (or single) ACTIVE school,
        the same school the backend resolves for this user."""
        memberships = [m for m in me.get("memberships", []) if m.get("status") == "ACTIVE"]
        primary = [m for m in memberships if m.get("is_primary_school")]
        chosen = primary[0] if len(primary) == 1 else (memberships[0] if len(memberships) == 1 else None)
        full_name = f"{me.get('first_name', '')} {me.get('last_name', '')}".strip() or me.get("username", "")
        return cls(
            user_id=me.get("id", ""),
            username=me.get("username", ""),
            full_name=full_name,
            school_code=chosen.get("school_code", "") if chosen else "",
            school_name=chosen.get("school_name", "") if chosen else "",
            roles=tuple(chosen.get("roles", [])) if chosen else (),
        )


@dataclass(frozen=True)
class Category:
    id: str
    code: str
    name: str
    description: str
    active: bool
    active_subject_count: int | None = None

    @classmethod
    def from_api(cls, row):
        return cls(
            row["id"],
            row["code"],
            row["name"],
            row.get("description") or "",
            row["active"],
            row.get("active_subject_count"),
        )


@dataclass(frozen=True)
class Subject:
    id: str
    code: str
    name: str
    category_id: str
    category_label: str
    subject_type: str
    public_visible: bool
    active: bool

    @classmethod
    def from_api(cls, row):
        category = row.get("category") or {}
        return cls(
            row["id"],
            row["code"],
            row["name"],
            category.get("id", ""),
            f"{category.get('code', '')} — {category.get('name', '')}".strip(" —"),
            row.get("subject_type", ""),
            bool(row.get("public_visible")),
            row["active"],
        )


SUBJECT_TYPES = {"THEORETICAL": "Théorique", "PRACTICAL": "Pratique"}


@dataclass
class Metric:
    label: str
    value: str | None = None
    hint: str = ""
    error: str | None = None  # this indicator could not be loaded


@dataclass
class DashboardData:
    school_name: str = ""
    school_city: str = ""
    year_name: str = ""
    metrics: list = field(default_factory=list)
