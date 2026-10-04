"""Plain data objects built from API payloads (no business rule here)."""

from dataclasses import dataclass, field
from datetime import date, datetime

from .money import ZERO, to_decimal

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

YEAR_STATUSES = {"PLANNED": "planifiée", "ACTIVE": "en cours", "CLOSED": "clôturée", "ARCHIVED": "archivée"}
OPEN_YEAR_STATUSES = frozenset({"PLANNED", "ACTIVE"})  # where classes can be created / edited


def _date(value):
    """'2026-09-01' -> date (None if missing)."""
    return date.fromisoformat(value) if value else None


@dataclass(frozen=True)
class AcademicYear:
    id: str
    name: str
    status: str
    is_current: bool
    start_date: date | None = None
    end_date: date | None = None
    class_count: int | None = None

    @property
    def label(self):
        suffix = " — année courante" if self.is_current else f" ({YEAR_STATUSES.get(self.status, self.status)})"
        return f"{self.name}{suffix}"

    @property
    def short_label(self):
        """Compact form for narrow lists: '2025-2026 (courante)'."""
        return f"{self.name} ({'courante' if self.is_current else YEAR_STATUSES.get(self.status, self.status)})"

    @property
    def open(self):
        return self.status in OPEN_YEAR_STATUSES

    # The list screens name a row by `code`; a year is identified by its name.
    @property
    def code(self):
        return self.name

    @property
    def active(self):
        return self.open

    @property
    def status_label(self):
        return YEAR_STATUSES.get(self.status, self.status).capitalize()

    @classmethod
    def from_api(cls, row):
        return cls(
            row["id"],
            row["name"],
            row.get("status", ""),
            bool(row.get("is_current")),
            _date(row.get("start_date")),
            _date(row.get("end_date")),
            row.get("class_count"),
        )


@dataclass(frozen=True)
class Level:
    id: str
    code: str
    name: str
    order_index: int
    active: bool
    cycle: str = ""
    first_character: str = ""
    public_visible: bool = False
    class_count: int | None = None

    @property
    def label(self):
        return f"{self.name} ({self.code})" if self.code and self.code != self.name else self.name

    @classmethod
    def from_api(cls, row):
        return cls(
            row["id"],
            row.get("code", ""),
            row["name"],
            row.get("order_index", 0),
            bool(row.get("active")),
            row.get("cycle") or "",
            row.get("first_character") or "",
            bool(row.get("public_visible")),
            row.get("class_count"),
        )


@dataclass(frozen=True)
class Room:
    id: str
    code: str
    name: str
    capacity: int | None
    active: bool
    room_type: str = "CLASSROOM"
    bench_count: int | None = None

    @property
    def label(self):
        places = f" · {self.capacity} places" if self.capacity else ""
        return f"{self.code} — {self.name}{places}"

    @classmethod
    def from_api(cls, row):
        return cls(
            row["id"],
            row["code"],
            row["name"],
            row.get("capacity"),
            bool(row.get("active")),
            row.get("room_type") or "CLASSROOM",
            row.get("bench_count"),
        )


@dataclass(frozen=True)
class SchoolClass:
    id: str
    name: str
    level_id: str
    level_label: str
    year_id: str
    year_name: str
    capacity: int | None
    main_room_id: str | None
    main_room_label: str
    public_visible: bool
    active: bool

    # The list screens name a row by `code`; a class is identified by its name.
    @property
    def code(self):
        return self.name

    @classmethod
    def from_api(cls, row):
        return cls(
            row["id"],
            row["name"],
            row["level"],
            row.get("level_name") or row.get("level_code") or "",
            row["academic_year"],
            row.get("academic_year_name") or "",
            row.get("capacity"),
            row.get("main_room"),
            row.get("main_room_name") or "",
            bool(row.get("public_visible")),
            bool(row["active"]),
        )


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


@dataclass(frozen=True)
class Point:
    """One x position of a chart: label on the axis, values per series,
    full text of the tooltip."""

    label: str
    values: tuple
    tooltip: str = ""


@dataclass
class ChartData:
    """What a dashboard chart shows: real points, or why there are none.
    `error` = the API failed; no points and no error = nothing recorded yet."""

    series: tuple = ()  # names of the series (legend)
    points: list = field(default_factory=list)
    unit: str = ""  # "%" or "" (axis labels)
    maximum: float | None = None  # fixed top of the axis (100 for percentages)
    empty_text: str = "Aucune donnée pour le moment."
    error: str | None = None
    note: str = ""  # small text under the title (period, source)


@dataclass(frozen=True)
class Activity:
    at: datetime | None
    action: str
    entity_type: str
    label: str
    actor: str


@dataclass
class DashboardCharts:
    attendance: ChartData = field(default_factory=ChartData)
    by_level: ChartData = field(default_factory=ChartData)
    by_class: ChartData = field(default_factory=ChartData)
    enrollment_trend: ChartData = field(default_factory=ChartData)
    payments: ChartData = field(default_factory=ChartData)
    payrolls: ChartData = field(default_factory=ChartData)
    activity: list = field(default_factory=list)
    activity_error: str | None = None


# --- students (ADR 0018) -----------------------------------------------------------

SEXES = {"F": "Féminin", "M": "Masculin"}
STUDENT_STATUSES = {
    "ACTIVE": "Actif",
    "SUSPENDED": "Suspendu",
    "LEFT": "Parti",
    "GRADUATED": "Diplômé",
    "ARCHIVED": "Archivé",
}
ENROLLMENT_STATUSES = {"ACTIVE": "En cours", "COMPLETED": "Terminée", "WITHDRAWN": "Retirée"}


@dataclass(frozen=True)
class Enrollment:
    """A student in a class for one academic year."""

    id: str
    year_id: str
    year_name: str
    class_id: str
    class_name: str
    level_id: str
    level_code: str
    level_name: str
    status: str
    enrollment_date: date | None = None
    end_date: date | None = None

    @property
    def status_label(self):
        return ENROLLMENT_STATUSES.get(self.status, self.status)

    @property
    def active(self):
        return self.status == "ACTIVE"

    @classmethod
    def from_api(cls, row):
        return cls(
            row["id"],
            str(row.get("academic_year") or ""),
            row.get("academic_year_name") or "",
            str(row.get("school_class") or ""),
            row.get("class_name") or "",
            str(row.get("level") or ""),
            row.get("level_code") or "",
            row.get("level_name") or "",
            row.get("status") or "",
            _date(row.get("enrollment_date")),
            _date(row.get("end_date")),
        )


@dataclass(frozen=True)
class Student:
    id: str
    student_number: str
    registration_number: str
    first_name: str
    last_name: str
    date_of_birth: date | None
    sex: str
    status: str
    birth_place: str = ""
    address: str = ""
    height_cm: int | None = None
    has_photo: bool = False
    enrollment: Enrollment | None = None  # of the selected (default: current) year

    # The list screens name a row by `code`.
    @property
    def code(self):
        return self.student_number

    @property
    def name(self):
        return f"{self.last_name} {self.first_name}".strip()

    @property
    def active(self):
        return self.status == "ACTIVE"

    @property
    def status_label(self):
        return STUDENT_STATUSES.get(self.status, self.status)

    @property
    def sex_label(self):
        return SEXES.get(self.sex, self.sex)

    @classmethod
    def from_api(cls, row):
        enrollment = row.get("enrollment")
        return cls(
            row["id"],
            row.get("student_number", ""),
            row.get("registration_number", ""),
            row.get("first_name", ""),
            row.get("last_name", ""),
            _date(row.get("date_of_birth")),
            row.get("sex", ""),
            row.get("status", ""),
            row.get("birth_place") or "",
            row.get("address") or "",
            row.get("height_cm"),
            bool(row.get("has_photo")),
            Enrollment.from_api(enrollment) if enrollment else None,
        )


@dataclass(frozen=True)
class HistoryEntry:
    at: datetime | None
    action: str
    summary: str
    actor: str


# --- teachers (ADR 0019) -----------------------------------------------------------

PROFESSIONAL_STATUSES = {
    "ACTIVE": "En activité",
    "PROBATION": "Période d'essai",
    "SUSPENDED": "Suspendu",
    "INACTIVE": "Inactif",
}
EMPLOYMENT_STATUSES = {
    "ACTIVE": "Actif",
    "ON_LEAVE": "En congé",
    "SUSPENDED": "Suspendu",
    "TERMINATED": "Fin de contrat",
}
QUALIFICATION_STATUSES = {
    "DECLARED": "Déclarée",
    "PENDING": "À valider",
    "VERIFIED": "Vérifiée",
    "REJECTED": "Retirée / refusée",
}
COMPATIBILITY_RESULTS = {
    "COMPATIBLE": "Compatible",
    "REQUIRES_REVIEW": "À valider par l'administration",
    "INCOMPATIBLE": "Incompatible",
    "OVERRIDDEN": "Autorisé par dérogation",
}


def _ref_label(ref):
    return f"{ref.get('code', '')} — {ref.get('name', '')}".strip(" —") if ref else ""


@dataclass(frozen=True)
class Teacher:
    id: str
    number: str
    first_name: str
    last_name: str
    email: str = ""
    phone: str = ""
    category_id: str = ""
    category_label: str = ""
    primary_subject_id: str = ""
    primary_subject_label: str = ""
    subjects: tuple = ()
    professional_status: str = ""
    employment_status: str = ""
    active: bool = True
    hire_date: date | None = None
    address: str = ""
    qualification_summary: str = ""
    bio: str = ""
    account_activated: bool = False
    active_course_count: int | None = None
    upcoming_session_count: int | None = None
    employee_id: str = ""  # payroll / remuneration (EmployeeProfile)

    @property
    def code(self):  # the list screens name a row by `code`
        return self.number

    @property
    def name(self):
        return f"{self.last_name} {self.first_name}".strip()

    @property
    def status_label(self):
        if self.active:
            return "Actif"
        if self.employment_status and self.employment_status != "ACTIVE":
            return EMPLOYMENT_STATUSES.get(self.employment_status, self.employment_status)
        return PROFESSIONAL_STATUSES.get(self.professional_status, self.professional_status)

    @classmethod
    def from_api(cls, row):
        category, subject = row.get("pedagogical_category") or {}, row.get("primary_subject") or {}
        return cls(
            row["id"],
            row.get("teacher_number", ""),
            row.get("first_name", ""),
            row.get("last_name", ""),
            row.get("email") or "",
            row.get("phone") or "",
            category.get("id", "") if isinstance(category, dict) else str(category),
            _ref_label(category) if isinstance(category, dict) else "",
            subject.get("id", "") if isinstance(subject, dict) else str(subject),
            _ref_label(subject) if isinstance(subject, dict) else "",
            tuple(row.get("subjects") or ()),
            row.get("professional_status", ""),
            row.get("employment_status", ""),
            bool(row.get("active", row.get("professional_status") == "ACTIVE")),
            _date(row.get("hire_date")),
            row.get("address") or "",
            row.get("qualification_summary") or "",
            row.get("bio") or "",
            bool(row.get("account_activated")),
            row.get("active_course_count"),
            row.get("upcoming_session_count"),
            str(row.get("employee") or ""),
        )


@dataclass(frozen=True)
class Qualification:
    id: str
    subject_id: str
    subject_code: str
    subject_name: str
    status: str
    source: str
    computed: str
    current: str
    notes: str = ""

    @property
    def label(self):
        return f"{self.subject_code} — {self.subject_name}"

    @property
    def status_label(self):
        return QUALIFICATION_STATUSES.get(self.status, self.status)

    @classmethod
    def from_api(cls, row):
        subject = row.get("subject") or {}
        return cls(
            row["id"],
            subject.get("id", ""),
            subject.get("code", ""),
            subject.get("name", ""),
            row.get("status", ""),
            row.get("source", ""),
            row.get("computed_compatibility", ""),
            row.get("current_compatibility", row.get("computed_compatibility", "")),
            row.get("notes") or "",
        )


@dataclass(frozen=True)
class CompatibilityVerdict:
    """The server's verdict (people/compatibility.py) — displayed, never computed here."""

    result: str
    reason: str
    subject_label: str
    level_label: str = ""
    rule: dict | None = None
    override: dict | None = None
    qualification_status: str | None = None

    @property
    def result_label(self):
        return COMPATIBILITY_RESULTS.get(self.result, self.result)

    @classmethod
    def from_api(cls, row):
        return cls(
            row["result"],
            row.get("reason", ""),
            _ref_label(row.get("subject")),
            _ref_label(row.get("level")),
            row.get("rule"),
            row.get("override"),
            row.get("qualification_status"),
        )


# --- courses (ADR 0020) ------------------------------------------------------------


@dataclass(frozen=True)
class Course:
    """Course = subject + teacher + class + year (the only pedagogical relation)."""

    id: str
    subject_id: str
    subject_code: str
    subject_name: str
    teacher_id: str
    teacher_number: str
    teacher_name: str
    class_id: str
    class_name: str
    level_code: str
    year_id: str
    year_name: str
    coefficient: str
    weekly_hours: str
    active: bool
    scale_id: str | None = None
    scale_label: str = ""
    published_slot_count: int | None = None
    upcoming_session_count: int | None = None

    @property
    def code(self):  # the list screens name a row by `code`
        return f"{self.subject_code} — {self.class_name}"

    @property
    def subject_label(self):
        return f"{self.subject_code} — {self.subject_name}"

    @classmethod
    def from_api(cls, row):
        subject, teacher = row.get("subject_ref") or {}, row.get("teacher_ref") or {}
        klass, level, year, scale = (
            row.get("class_ref") or {},
            row.get("level") or {},
            row.get("year") or {},
            row.get("scale") or {},
        )
        return cls(
            row["id"],
            subject.get("id", row.get("subject", "")),
            subject.get("code", row.get("subject_code", "")),
            subject.get("name", ""),
            teacher.get("id", row.get("teacher", "")),
            teacher.get("number", ""),
            teacher.get("name", row.get("teacher_name", "")),
            klass.get("id", row.get("school_class", "")),
            klass.get("name", row.get("class_name", "")),
            level.get("code", ""),
            year.get("id", row.get("academic_year", "")),
            year.get("name", ""),
            str(row.get("coefficient", "")),
            str(row.get("weekly_hours", "")),
            bool(row.get("active")),
            scale.get("id"),
            f"{scale.get('code', '')} — {scale.get('label', '')}".strip(" —") if scale else "",
            row.get("published_slot_count"),
            row.get("upcoming_session_count"),
        )


@dataclass(frozen=True)
class EligibleTeacher:
    id: str
    number: str
    name: str
    category: str
    reason: str = ""  # empty when eligible; the server's rule code otherwise

    @property
    def label(self):
        return f"{self.name} ({self.number}, {self.category})"

    @classmethod
    def from_api(cls, row):
        return cls(
            row["id"], row.get("number", ""), row.get("name", ""), row.get("category", ""), row.get("reason", "")
        )


# --- planning (ADR 0021) -----------------------------------------------------------

WEEKDAY_NAMES = {1: "Lundi", 2: "Mardi", 3: "Mercredi", 4: "Jeudi", 5: "Vendredi", 6: "Samedi", 7: "Dimanche"}
ROOM_TYPES = {  # = academics.RoomType on the server
    "CLASSROOM": "Salle de classe",
    "LABORATORY": "Laboratoire",
    "WORKSHOP": "Atelier",
    "COMPUTER": "Salle informatique",
    "SPORTS": "Installation sportive",
    "OTHER": "Autre",
}
SESSION_STATUSES = {"SCHEDULED": "Planifiée", "COMPLETED": "Réalisée", "CANCELLED": "Annulée"}
REQUEST_STATUSES = {
    "PENDING": "En attente",
    "APPROVED": "Validée",
    "REJECTED": "Refusée",
    "CHANGES_REQUESTED": "Modification proposée",
    "CANCELLED": "Retirée",
}
BREAK_TYPES = {"HOLIDAY": "Vacances", "PUBLIC_HOLIDAY": "Jour férié", "EXAM": "Examens", "OTHER": "Autre"}


def _datetime(value):
    """Server datetime (ISO with the school's offset) — displayed as is: the
    school's local time, whatever the computer's time zone."""
    return datetime.fromisoformat(value) if value else None


def _ref(row, *names):
    row = row or {}
    return tuple(row.get(name) or "" for name in names)


@dataclass(frozen=True)
class Slot:
    id: str
    course_id: str
    subject_code: str
    subject_name: str
    class_id: str
    class_name: str
    teacher_id: str
    teacher_name: str
    room_id: str
    room_code: str
    weekday: int
    start_time: str
    end_time: str
    effective_from: date | None
    effective_to: date | None
    status: str

    @property
    def code(self):
        return f"{self.subject_code} — {self.class_name}"

    @property
    def active(self):
        return self.status == "PUBLISHED"

    @property
    def when(self):
        return f"{WEEKDAY_NAMES.get(self.weekday, '?')} {self.start_time[:5]}–{self.end_time[:5]}"

    @classmethod
    def from_api(cls, row):
        subject_id, subject_code, subject_name = _ref(row.get("subject"), "id", "code", "name")
        class_id, class_name = _ref(row.get("school_class"), "id", "name")
        teacher_id, teacher_name = _ref(row.get("teacher"), "id", "name")
        room_id, room_code = _ref(row.get("room"), "id", "code")
        return cls(
            row["id"],
            str(row.get("course") or ""),
            subject_code,
            subject_name,
            class_id,
            class_name,
            teacher_id,
            teacher_name,
            room_id,
            room_code,
            int(row.get("weekday") or 0),
            row.get("start_time") or "",
            row.get("end_time") or "",
            _date(row.get("effective_from")),
            _date(row.get("effective_to")),
            row.get("status") or "",
        )


@dataclass(frozen=True)
class Session:
    id: str
    course_id: str
    subject_code: str
    subject_name: str
    class_id: str
    class_name: str
    teacher_id: str
    teacher_name: str
    planned_teacher_id: str
    planned_teacher_name: str
    room_id: str
    room_code: str
    date: date | None
    start: datetime | None
    end: datetime | None
    status: str
    is_substituted: bool = False
    is_moved: bool = False

    @property
    def code(self):
        return f"{self.subject_code} — {self.class_name}"

    @property
    def active(self):
        return self.status == "SCHEDULED"

    @property
    def status_label(self):
        label = SESSION_STATUSES.get(self.status, self.status)
        extras = [x for x, on in (("remplacée", self.is_substituted), ("déplacée", self.is_moved)) if on]
        return f"{label} ({', '.join(extras)})" if extras and self.status != "CANCELLED" else label

    @property
    def hours(self):
        return f"{self.start:%H:%M}–{self.end:%H:%M}" if self.start and self.end else ""

    @classmethod
    def from_api(cls, row):
        subject_id, subject_code, subject_name = _ref(row.get("subject"), "id", "code", "name")
        class_id, class_name = _ref(row.get("school_class"), "id", "name")
        teacher_id, teacher_name = _ref(row.get("teacher"), "id", "name")
        planned_id, planned_name = _ref(row.get("planned_teacher"), "id", "name")
        room_id, room_code = _ref(row.get("room"), "id", "code")
        return cls(
            row["id"],
            str(row.get("course") or ""),
            subject_code,
            subject_name,
            class_id,
            class_name,
            teacher_id,
            teacher_name,
            planned_id or teacher_id,
            planned_name or teacher_name,
            room_id,
            room_code,
            _date(row.get("date")),
            _datetime(row.get("scheduled_start")),
            _datetime(row.get("scheduled_end")),
            row.get("status") or "",
            bool(row.get("is_substituted")),
            bool(row.get("is_moved")),
        )


@dataclass(frozen=True)
class UnavailabilityRequest:
    id: str
    teacher_id: str
    date: date | None
    start_time: str
    end_time: str
    reason: str
    status: str
    comment: str = ""

    @property
    def code(self):
        return f"{self.date:%d/%m/%Y}" if self.date else ""

    @property
    def active(self):
        return self.status == "PENDING"

    @classmethod
    def from_api(cls, row):
        return cls(
            row["id"],
            str(row.get("teacher") or ""),
            _date(row.get("date")),
            row.get("start_time") or "",
            row.get("end_time") or "",
            row.get("reason") or "",
            row.get("status") or "",
            row.get("decision_comment") or "",
        )


@dataclass(frozen=True)
class SchoolBreak:
    id: str
    year_id: str
    name: str
    start: datetime | None
    end: datetime | None
    break_type: str
    affects_scheduling: bool

    @property
    def code(self):
        return self.name

    @property
    def active(self):
        return self.affects_scheduling

    @classmethod
    def from_api(cls, row):
        return cls(
            row["id"],
            str(row.get("academic_year") or ""),
            row.get("name") or "",
            _datetime(row.get("start_datetime")),
            _datetime(row.get("end_datetime")),
            row.get("break_type") or "HOLIDAY",
            bool(row.get("affects_scheduling", True)),
        )


# --- finance (backend finance/api.py, ADR 0013 / 0022) -----------------------------
# Amounts are Decimal (from the API's strings): never floats.

PAYMENT_STATUSES = {
    "SUCCEEDED": "Réussi",
    "PENDING": "En attente",
    "DECLINED": "Refusé",
    "INSUFFICIENT_FUNDS": "Fonds insuffisants",
    "TIMEOUT": "Délai dépassé",
    "PROVIDER_ERROR": "Erreur fournisseur",
    "CANCELLED": "Annulé",
    "PARTIALLY_REFUNDED": "Partiellement remboursé",
    "REFUNDED": "Remboursé",
}
FAILED_PAYMENTS = frozenset({"DECLINED", "INSUFFICIENT_FUNDS", "TIMEOUT", "PROVIDER_ERROR", "CANCELLED"})
PAYMENT_METHODS = {"CASH": "Espèces (guichet)", "WALLET": "Portefeuille mobile"}
INVOICE_STATUSES = {
    "ISSUED": "Émise",
    "PARTIALLY_PAID": "Partiellement payée",
    "PAID": "Payée",
    "CANCELLED": "Annulée",
}
SIMULATION_BEHAVIORS = {
    "NORMAL": "Normal",
    "DECLINE": "Refus systématique",
    "TIMEOUT": "Délai dépassé",
    "PROVIDER_ERROR": "Erreur fournisseur",
}
LEDGER_TYPES = {
    "PAYMENT": "Paiement",
    "REFUND": "Remboursement",
    "FUNDING": "Approvisionnement",
    "CREDIT": "Crédit",
    "PAYROLL": "Paie",
}


def _money(value):
    return to_decimal(value) if value is not None else None


@dataclass(frozen=True)
class FeeType:
    id: str
    code: str
    name: str
    description: str = ""
    active: bool = True

    @classmethod
    def from_api(cls, row):
        return cls(row["id"], row.get("code", ""), row.get("name", ""), row.get("description") or "", row["active"])


@dataclass(frozen=True)
class Refund:
    id: str
    payment_id: str
    amount: object  # Decimal
    reason: str
    status: str
    completed_at: datetime | None
    inverse_reference: str = ""
    payment_reference: str = ""
    payment_amount: object = None
    payment_method: str = ""
    student_name: str = ""
    currency: str = ""

    @property
    def code(self):
        return self.payment_reference or self.inverse_reference

    @property
    def active(self):
        return self.status == "COMPLETED"

    @classmethod
    def from_api(cls, row):
        return cls(
            row["id"],
            str(row.get("payment") or ""),
            _money(row.get("amount")),
            row.get("reason") or "",
            row.get("status") or "",
            _datetime(row.get("completed_at")),
            row.get("inverse_transaction_reference") or "",
            row.get("payment_reference") or "",
            _money(row.get("payment_amount")),
            row.get("payment_method") or "",
            row.get("student_name") or "",
            row.get("currency") or "",
        )


@dataclass(frozen=True)
class Payment:
    id: str
    reference: str
    student_id: str
    student_name: str
    amount: object  # Decimal
    refunded: object  # Decimal
    currency: str
    method: str
    provider: str
    status: str
    initiated_at: datetime | None
    completed_at: datetime | None
    failure_reason: str = ""
    provider_reference: str = ""
    allocations: tuple = ()  # (invoice number, Decimal amount, is a refund)
    refunds: tuple = ()  # Refund
    replayed: bool = False

    @property
    def code(self):
        return self.reference

    @property
    def active(self):
        return self.status in ("SUCCEEDED", "PARTIALLY_REFUNDED")

    @property
    def failed(self):
        return self.status in FAILED_PAYMENTS

    @property
    def status_label(self):
        return PAYMENT_STATUSES.get(self.status, self.status)

    @property
    def refundable(self):
        """What the server would still accept to refund (display only)."""
        if not self.active or self.amount is None:
            return ZERO
        return self.amount - (self.refunded or ZERO)

    @classmethod
    def from_api(cls, row):
        return cls(
            row["id"],
            row.get("payment_reference") or "",
            str(row.get("student") or ""),
            row.get("student_name") or "",
            _money(row.get("amount")),
            _money(row.get("refunded_amount")) or ZERO,
            row.get("currency") or "",
            row.get("payment_method") or "",
            row.get("provider") or "",
            row.get("status") or "",
            _datetime(row.get("initiated_at")),
            _datetime(row.get("completed_at")),
            row.get("failure_reason") or "",
            row.get("provider_reference") or "",
            tuple(
                (a.get("invoice_number") or "", _money(a.get("amount")), bool(a.get("refund")))
                for a in row.get("allocations") or ()
            ),
            tuple(Refund.from_api(r) for r in row.get("refunds") or ()),
            bool(row.get("replayed")),
        )


@dataclass(frozen=True)
class Invoice:
    id: str
    number: str
    student_id: str
    student_name: str
    issue_date: date | None
    due_date: date | None
    status: str
    total: object  # Decimal
    paid: object
    balance: object
    currency: str
    cancelled_reason: str = ""
    lines: tuple = ()  # (label, Decimal total)

    @property
    def code(self):
        return self.number

    @property
    def active(self):
        return self.status in ("ISSUED", "PARTIALLY_PAID")

    @property
    def status_label(self):
        return INVOICE_STATUSES.get(self.status, self.status)

    def overdue(self, today):
        return self.active and self.due_date is not None and self.due_date < today

    @classmethod
    def from_api(cls, row):
        return cls(
            row["id"],
            row.get("invoice_number") or "",
            str(row.get("student") or ""),
            row.get("student_name") or "",
            _date(row.get("issue_date")),
            _date(row.get("due_date")),
            row.get("status") or "",
            _money(row.get("total_amount")),
            _money(row.get("amount_paid")),
            _money(row.get("balance_due")),
            row.get("currency") or "",
            row.get("cancelled_reason") or "",
            tuple(
                (line.get("description") or line.get("fee_type_code") or "", _money(line.get("total")))
                for line in row.get("lines") or ()
            ),
        )


@dataclass(frozen=True)
class Wallet:
    id: str
    owner_id: str
    owner_name: str
    provider: str
    identifier: str
    balance: object  # Decimal
    currency: str
    status: str
    behavior: str = "NORMAL"

    @property
    def code(self):
        return f"{self.provider} {self.masked}"

    @property
    def active(self):
        return self.status == "ACTIVE"

    @property
    def masked(self):
        """Only the last 4 characters of the account identifier are shown."""
        tail = self.identifier[-4:]
        return f"•••• {tail}" if len(self.identifier) > 4 else tail

    @classmethod
    def from_api(cls, row):
        return cls(
            row["id"],
            str(row.get("owner") or ""),
            row.get("owner_name") or "",
            row.get("provider_code") or "",
            row.get("wallet_identifier") or "",
            _money(row.get("balance")),
            row.get("currency") or "",
            row.get("status") or "",
            row.get("simulation_behavior") or "NORMAL",
        )


@dataclass(frozen=True)
class TreasuryEntry:
    id: str
    kind: str
    direction: str
    amount: object  # Decimal
    reference: str
    balance_after: object
    at: datetime | None

    @classmethod
    def from_api(cls, row):
        return cls(
            row["id"],
            row.get("transaction_type") or "",
            row.get("direction") or "",
            _money(row.get("amount")),
            row.get("reference") or "",
            _money(row.get("balance_after")),
            _datetime(row.get("created_at")),
        )


# --- payroll (backend payroll/api.py, ADR 0014 / 0022) ------------------------------

PAYROLL_STATUSES = {"CALCULATED": "Préparée", "APPROVED": "Approuvée", "PAID": "Payée", "CANCELLED": "Annulée"}
PAYOUT_METHODS = {"CASH": "Espèces / hors système", "WALLET": "Wallet (simulation)"}
PERIOD_STATUSES = {"OPEN": "Ouverte", "CLOSED": "Clôturée"}
LINE_KINDS = {
    "PROGRAMMED": "Séance programmée",
    "EARNED": "Séance validée (acquise)",
    "SALARY": "Salaire fixe",
    "ADJUSTMENT": "Correction",
}
EMPLOYEE_KINDS = {"TEACHER": "Enseignant", "STAFF": "Personnel"}


@dataclass(frozen=True)
class PayrollPeriod:
    id: str
    year_id: str
    name: str
    start: date | None
    end: date | None
    status: str

    @property
    def code(self):
        return self.name

    @property
    def active(self):
        return self.status == "OPEN"

    @classmethod
    def from_api(cls, row):
        return cls(
            row["id"],
            str(row.get("academic_year") or ""),
            row.get("name") or "",
            _date(row.get("start_date")),
            _date(row.get("end_date")),
            row.get("status") or "",
        )


@dataclass(frozen=True)
class PayrollLine:
    version: int
    kind: str
    session_date: date | None
    minutes: int | None
    rate: object  # Decimal
    amount: object
    late: bool

    @classmethod
    def from_api(cls, row):
        return cls(
            int(row.get("version") or 1),
            row.get("kind") or "",
            _date(row.get("session_date")),
            row.get("duration_minutes"),
            _money(row.get("rate")),
            _money(row.get("amount")),
            bool(row.get("late")),
        )


@dataclass(frozen=True)
class Payroll:
    id: str
    kind: str
    employee_id: str
    employee_name: str
    period_id: str
    period_name: str
    status: str
    version: int
    adjustments: object  # Decimal
    payable: object
    approved: object
    currency: str
    programmed: object = None
    earned: object = None
    base_salary: object = None
    scheduled_count: int = 0
    completed_count: int = 0
    payable_count: int = 0
    approved_at: datetime | None = None
    paid_at: datetime | None = None
    payout_method: str = ""
    payment_reference: str = ""
    cancelled_reason: str = ""
    lines: tuple = ()
    reconstructible: bool | None = None

    @property
    def code(self):
        return f"{self.employee_name} · {self.period_name}"

    @property
    def active(self):
        return self.status != "CANCELLED"

    @property
    def status_label(self):
        return PAYROLL_STATUSES.get(self.status, self.status)

    @classmethod
    def from_api(cls, row):
        return cls(
            row["id"],
            row.get("kind") or "",
            str(row.get("employee") or ""),
            row.get("employee_name") or "",
            str(row.get("period") or ""),
            row.get("period_name") or "",
            row.get("status") or "",
            int(row.get("version") or 1),
            _money(row.get("adjustments_amount")),
            _money(row.get("payable_amount")),
            _money(row.get("approved_amount")),
            row.get("currency") or "",
            _money(row.get("programmed_amount")),
            _money(row.get("earned_amount")),
            _money(row.get("base_salary")),
            int(row.get("scheduled_sessions_count") or 0),
            int(row.get("completed_sessions_count") or 0),
            int(row.get("payable_sessions_count") or 0),
            _datetime(row.get("approved_at")),
            _datetime(row.get("paid_at")),
            row.get("payout_method") or "",
            row.get("payment_reference") or "",
            row.get("cancelled_reason") or "",
            tuple(PayrollLine.from_api(line) for line in row.get("lines") or ()),
            row.get("reconstructible"),
        )


@dataclass(frozen=True)
class Adjustment:
    id: str
    employee_id: str
    amount: object  # Decimal, signed
    reason: str
    effective_date: date | None
    source: str
    settled: bool
    created_at: datetime | None

    @property
    def code(self):
        return self.reason

    @property
    def active(self):
        return not self.settled

    @classmethod
    def from_api(cls, row):
        return cls(
            row["id"],
            str(row.get("employee") or ""),
            _money(row.get("amount")),
            row.get("reason") or "",
            _date(row.get("effective_date")),
            row.get("source") or "",
            bool(row.get("settled_teacher_payroll") or row.get("settled_staff_payroll")),
            _datetime(row.get("created_at")),
        )
