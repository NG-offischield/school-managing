"""Vie scolaire → Présences (backend attendance/api.py, people/guardian_admin_api.py).
Read only for attendance and scans; guardians are created by the server's
service and activated / suspended with the EXISTING account endpoints
(services/accounts.py, ADR 0024).

    GET  admin/attendance/daily/?date=&school_class=     the day's records
    GET  admin/scans/?date=&guardian=&result=            gate passages
    GET/POST admin/guardians/   GET admin/guardians/{id}/
"""

from dataclasses import dataclass
from datetime import date, datetime

from ..api.errors import ValidationFailed

DAILY_STATUSES = {
    "PENDING": "En attente",
    "PRESENT": "Présent",
    "LATE": "En retard",
    "ABSENT": "Absent",
    "EXCUSED": "Absence justifiée",
}
SCAN_RESULTS = {
    "ACCEPTED": "Accepté (arrivée)",
    "ALREADY_PRESENT": "Accepté (déjà présent)",
    "UNKNOWN_TOKEN": "QR inconnu",
    "REVOKED_TOKEN": "QR révoqué",
    "EXPIRED_TOKEN": "QR d'une autre année",
    "STUDENT_NOT_ENROLLED": "Élève non inscrit",
}
ACCOUNT_STATUSES = {"ACTIVE": "Actif", "SUSPENDED": "Suspendu", "PENDING": "En attente", "LEFT": "Parti"}


def _when(value):
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


@dataclass(frozen=True)
class DailyRecord:
    id: str
    student_name: str
    student_number: str
    school_class: str
    status: str
    arrival: datetime | None
    late_minutes: int

    active = True  # CatalogPage: nothing to deactivate here

    @property
    def status_label(self):
        return DAILY_STATUSES.get(self.status, self.status)

    @classmethod
    def from_api(cls, row):
        return cls(
            id=str(row["id"]),
            student_name=row.get("student_name") or "",
            student_number=row.get("student_number") or "",
            school_class=row.get("school_class_name") or "—",
            status=row.get("status") or "PENDING",
            arrival=_when(row.get("arrival_time")),
            late_minutes=int(row.get("late_minutes") or 0),
        )


@dataclass(frozen=True)
class ScanRecord:
    id: str
    scanned_at: datetime | None
    result: str
    student_name: str
    scanned_by: str

    active = True

    @property
    def result_label(self):
        return SCAN_RESULTS.get(self.result, self.result)

    @property
    def accepted(self):
        return self.result in ("ACCEPTED", "ALREADY_PRESENT")

    @classmethod
    def from_api(cls, row):
        return cls(
            id=str(row["id"]),
            scanned_at=_when(row.get("scanned_at")),
            result=row.get("result") or "",
            student_name=row.get("student_name") or "—",
            scanned_by=row.get("scanned_by_name") or "—",
        )


@dataclass(frozen=True)
class Guardian:
    id: str
    membership_id: str
    number: str
    first_name: str
    last_name: str
    email: str
    phone: str
    account_status: str
    activated: bool
    scans_today: int
    last_scan_at: datetime | None

    @property
    def name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def active(self):
        return self.account_status == "ACTIVE"

    @property
    def code(self):  # CatalogPage messages: « Gardien « Moussa Bello » créé »
        return self.name

    @property
    def account_label(self):
        if self.account_status == "ACTIVE" and not self.activated:
            return "À activer"
        return ACCOUNT_STATUSES.get(self.account_status, self.account_status)

    @classmethod
    def from_api(cls, row):
        return cls(
            id=str(row["id"]),
            membership_id=str(row.get("membership") or ""),
            number=row.get("guardian_number") or "",
            first_name=row.get("first_name") or "",
            last_name=row.get("last_name") or "",
            email=row.get("email") or "",
            phone=row.get("phone") or "",
            account_status=row.get("account_status") or "",
            activated=bool(row.get("activated")),
            scans_today=int(row.get("scans_today") or 0),
            last_scan_at=_when(row.get("last_scan_at")),
        )


class AttendanceService:
    def __init__(self, api):
        self.api = api

    def daily(self, day: date, school_class=None):
        rows = self.api.list_all("admin/attendance/daily/", date=day.isoformat(), school_class=school_class or None)
        return [DailyRecord.from_api(r) for r in rows]

    def scans(self, day: date | None = None, *, guardian=None, result=None):
        rows = self.api.list_all(
            "admin/scans/",
            date=day.isoformat() if day else None,
            guardian=guardian or None,
            result=result or None,
        )
        return [ScanRecord.from_api(r) for r in rows]

    def guardians(self, *, search=None, status=None):
        rows = self.api.list_all("admin/guardians/", search=search or None, status=status or None)
        return [Guardian.from_api(r) for r in rows]

    def create_guardian(self, *, first_name, last_name, email, guardian_number, phone=""):
        missing = [
            k
            for k, v in {
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "guardian_number": guardian_number,
            }.items()
            if not (v or "").strip()
        ]
        if missing:
            raise ValidationFailed("Formulaire incomplet.", details={k: ["Obligatoire."] for k in missing})
        payload = {
            "first_name": first_name.strip(),
            "last_name": last_name.strip(),
            "email": email.strip(),
            "guardian_number": guardian_number.strip(),
            "phone": (phone or "").strip(),
        }
        return Guardian.from_api(self.api.post("admin/guardians/", payload))
