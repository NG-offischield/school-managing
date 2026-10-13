"""Vie scolaire → Présences (backend attendance/api.py, people/guardian_admin_api.py).
Read only for attendance and scans; guardians are created by the server's
service and activated / suspended with the EXISTING account endpoints
(services/accounts.py, ADR 0024).

    GET  admin/attendance/daily/?date=&school_class=     the day's records
    POST admin/attendance/{id}/correct/ {status, reason, arrival_time?}   audited correction
    GET  admin/scans/?date=&guardian=&result=            gate passages
    GET/POST admin/guardians/   GET admin/guardians/{id}/
    GET  admin/qr-codes/?student=&status=                annual QR codes (one active per pupil and year)
    POST admin/qr-codes/issue/ {student}   …/issue-class/ {school_class}   …/reissue/ {student, reason}
    POST admin/qr-codes/{id}/revoke/ {reason}

Every rule is the server's: who may correct, the status a time gives (late
or present), when a code can be issued (pupil actively enrolled, open year),
and the audit trail. The QR token itself is never shown here: the card is
printed from Documents (it carries the active code).
"""

from dataclasses import dataclass
from datetime import date, datetime, time

from ..api.errors import ValidationFailed
from ..i18n import Labels, tr

DAILY_STATUSES = Labels(
    {
        "PENDING": "En attente",
        "PRESENT": "Présent",
        "LATE": "En retard",
        "ABSENT": "Absent",
        "EXCUSED": "Absence justifiée",
    }
)
SCAN_RESULTS = Labels(
    {
        "ACCEPTED": "Accepté (arrivée)",
        "ALREADY_PRESENT": "Accepté (déjà présent)",
        "UNKNOWN_TOKEN": "QR inconnu",
        "REVOKED_TOKEN": "QR révoqué",
        "EXPIRED_TOKEN": "QR d'une autre année",
        "STUDENT_NOT_ENROLLED": "Élève non inscrit",
    }
)
ACCOUNT_STATUSES = Labels({"ACTIVE": "Actif", "SUSPENDED": "Suspendu", "PENDING": "En attente", "LEFT": "Parti"})
QR_STATUSES = Labels({"ACTIVE": "Actif", "REVOKED": "Révoqué", "": "Aucun code"})
# What a correction may set (PENDING is the server's own state). Present or late
# is decided by the server from the arrival time and the day's policy.
CORRECTIONS = Labels(
    {
        "PRESENT": "Présent (en retard selon l'heure d'arrivée)",
        "ABSENT": "Absent",
        "EXCUSED": "Absence justifiée",
    }
)


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
    day: date | None = None
    note: str = ""  # the reason of the last correction (server)

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
            day=date.fromisoformat(row["date"]) if row.get("date") else None,
            note=row.get("note") or "",
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
class StudentCode:
    """A pupil of the class and their annual QR code (latest version), if any."""

    student_id: str
    student_name: str
    student_number: str
    qr_id: str = ""
    version: int = 0
    qr_status: str = ""  # ACTIVE | REVOKED | "" (none yet)
    issued_at: datetime | None = None

    @property
    def id(self):  # CatalogPage selects rows by id
        return self.student_id

    @property
    def active(self):
        return self.qr_status == "ACTIVE"

    @property
    def status_label(self):
        return QR_STATUSES.get(self.qr_status, self.qr_status)


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
            return tr("À activer")
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

    def correct(self, record_id, *, status, reason, day=None, arrival: time | None = None):
        """Audited correction: reason mandatory; an arrival time for a present /
        late pupil (local time of that day, as the other screens send them)."""
        missing = {}
        if status not in CORRECTIONS:
            missing["status"] = [tr("Obligatoire.")]
        if not (reason or "").strip():
            missing["reason"] = [tr("Indiquez le motif.")]
        if status == "PRESENT" and (arrival is None or day is None):
            missing["arrival_time"] = [tr("Indiquez l'heure d'arrivée.")]
        if missing:
            raise ValidationFailed("Formulaire incomplet.", details=missing)
        payload = {"status": status, "reason": reason.strip()}
        if status == "PRESENT":
            payload["arrival_time"] = datetime.combine(day, arrival).isoformat()
        return self.api.post(f"admin/attendance/{record_id}/correct/", payload)

    def class_codes(self, class_id):
        """The class's pupils with their latest QR code (server lists, joined here)."""
        students = self.api.list_all("students/", school_class=class_id)
        codes = {}
        for row in self.api.list_all("admin/qr-codes/"):
            current = codes.get(row["student"])
            if current is None or int(row.get("version") or 0) > int(current.get("version") or 0):
                codes[row["student"]] = row
        result = []
        for student in students:
            qr = codes.get(str(student["id"]), {})
            result.append(
                StudentCode(
                    student_id=str(student["id"]),
                    student_name=f"{student.get('last_name', '')} {student.get('first_name', '')}".strip(),
                    student_number=student.get("student_number") or "",
                    qr_id=str(qr.get("id") or ""),
                    version=int(qr.get("version") or 0),
                    qr_status=qr.get("status") or "",
                    issued_at=_when(qr.get("issued_at")),
                )
            )
        return sorted(result, key=lambda r: r.student_name.lower())

    def issue_code(self, student_id):
        return self.api.post("admin/qr-codes/issue/", {"student": student_id})

    def issue_class_codes(self, class_id):
        """Missing codes of every active pupil of the class (existing ones are kept)."""
        return self.api.post("admin/qr-codes/issue-class/", {"school_class": class_id})

    def reissue_code(self, student_id, reason):
        """Lost or stolen card: the active code is revoked, version n+1 issued."""
        if not (reason or "").strip():
            raise ValidationFailed("Formulaire incomplet.", details={"reason": [tr("Indiquez le motif.")]})
        return self.api.post("admin/qr-codes/reissue/", {"student": student_id, "reason": reason.strip()})

    def revoke_code(self, qr_id, reason):
        if not (reason or "").strip():
            raise ValidationFailed("Formulaire incomplet.", details={"reason": [tr("Indiquez le motif.")]})
        return self.api.post(f"admin/qr-codes/{qr_id}/revoke/", {"reason": reason.strip()})

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
            raise ValidationFailed("Formulaire incomplet.", details={k: [tr("Obligatoire.")] for k in missing})
        payload = {
            "first_name": first_name.strip(),
            "last_name": last_name.strip(),
            "email": email.strip(),
            "guardian_number": guardian_number.strip(),
            "phone": (phone or "").strip(),
        }
        return Guardian.from_api(self.api.post("admin/guardians/", payload))
