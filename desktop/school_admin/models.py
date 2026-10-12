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
    regime_id: str | None = None
    regime_label: str = ""

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
            row.get("regime"),
            row.get("regime_name") or "",
        )


@dataclass
class TimetableRegime:
    """Explicit time window of a school year (backend academics.TimetableRegime):
    lets a day class and an evening class share one default room."""

    id: str
    year_id: str
    name: str
    start: str  # "HH:MM"
    end: str
    active: bool

    @property
    def label(self):
        return f"{self.name} ({self.start}–{self.end})"

    @classmethod
    def from_api(cls, row):
        return cls(
            row["id"],
            row["academic_year"],
            row["name"],
            (row.get("start_time") or "")[:5],
            (row.get("end_time") or "")[:5],
            bool(row.get("active", True)),
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
    membership_id: str = ""  # account lifecycle (ADR 0024)
    account_state: str = ""  # ACTIVE | PENDING_ACTIVATION | NOT_ACTIVATED | DISABLED

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
            str(row.get("membership") or ""),
            row.get("account_state") or "",
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


# --- communication (backend communication/api.py, ADR 0015 / 0023) ------------------

NOTIFICATION_TYPES = {
    "ATTENDANCE_LATE": "Retard",
    "ATTENDANCE_ABSENT": "Absence",
    "CONVOCATION": "Convocation",
    "SCHEDULE_CHANGE": "Planning",
    "SUBSTITUTION": "Remplacement",
    "PAYMENT": "Paiement",
    "REFUND": "Remboursement",
    "PAYROLL": "Paie",
    "REPORT_CARD": "Bulletin",
    "MESSAGE": "Message",
    "ANNOUNCEMENT": "Annonce",
    "COMPLAINT": "Réclamation",
    "FORUM": "Forum",
    "PLAN": "Plan de l'établissement",
}
SEVERITIES = {"INFO": "Information", "WARNING": "Attention", "CRITICAL": "Important"}
CONVERSATION_TYPES = {
    "ADMINISTRATION": "Administration",
    "PARENT_TEACHER": "Parent – enseignant",
    "COMPLAINT": "Réclamation",
}
THREAD_STATUSES = {"OPEN": "Ouvert", "LOCKED": "Verrouillé", "ARCHIVED": "Archivé"}
THREAD_TYPES = {"GENERAL": "Discussion", "ANNOUNCEMENT": "Annonce"}
SPACE_AUDIENCES = {"SCHOOL": "Toute l'école (rôles choisis)", "CLASS": "Communauté d'une classe"}
FORUM_ROLES = {"TEACHER": "Enseignants", "PARENT": "Parents", "STAFF": "Personnel"}
COMPLAINT_STATUSES = {
    "DRAFT": "Brouillon",
    "OPEN": "Ouverte",
    "IN_PROGRESS": "En traitement",
    "RESOLVED": "Résolue",
    "CANCELLED": "Annulée",
    "CLOSED": "Clôturée",
}
COMPLAINT_CATEGORIES = {
    "PEDAGOGY": "Pédagogie",
    "BEHAVIOR": "Comportement",
    "ADMINISTRATIVE": "Administratif",
    "FINANCE": "Finance",
    "OTHER": "Autre",
}
COMPLAINT_PRIORITIES = {"LOW": "Basse", "NORMAL": "Normale", "HIGH": "Haute", "URGENT": "Urgente"}
# Status changes the administration may request (the server decides: 409 invalid_transition otherwise).
COMPLAINT_NEXT = {
    "OPEN": ("IN_PROGRESS", "RESOLVED"),
    "IN_PROGRESS": ("RESOLVED",),
    "RESOLVED": ("CLOSED", "IN_PROGRESS"),
}


@dataclass(frozen=True)
class Member:
    id: str
    name: str
    roles: tuple = ()

    @property
    def label(self):
        return f"{self.name} ({', '.join(self.roles)})" if self.roles else self.name

    @classmethod
    def from_api(cls, row):
        return cls(row["id"], row.get("name") or "", tuple(row.get("roles") or ()))


@dataclass(frozen=True)
class Attachment:
    """A private file: only its id, name, type and size travel; the download
    goes through the API (never a server path)."""

    id: str
    kind: str  # "message" | "complaint"
    name: str
    mime_type: str
    size_bytes: int

    @property
    def size_label(self):
        size = self.size_bytes or 0
        if size < 1024:
            return f"{size} o"
        return f"{size / 1024:.0f} Ko" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f} Mo"

    @classmethod
    def from_api(cls, row, kind):
        return cls(row["id"], kind, row.get("name") or "", row.get("mime_type") or "", int(row.get("size_bytes") or 0))


@dataclass(frozen=True)
class Notification:
    id: str
    kind: str
    severity: str
    title: str
    message: str
    is_read: bool
    created_at: datetime | None
    read_at: datetime | None = None

    @property
    def code(self):
        return self.title

    @property
    def active(self):
        return not self.is_read

    @property
    def kind_label(self):
        return NOTIFICATION_TYPES.get(self.kind, self.kind)

    @classmethod
    def from_api(cls, row):
        return cls(
            row["id"],
            row.get("notification_type") or "",
            row.get("severity") or "INFO",
            row.get("title") or "",
            row.get("message") or "",
            bool(row.get("is_read")),
            _datetime(row.get("created_at")),
            _datetime(row.get("read_at")),
        )


@dataclass(frozen=True)
class Conversation:
    id: str
    kind: str
    title: str
    student_id: str
    active: bool
    last_message_at: datetime | None
    participants: tuple = ()  # (member id, name, active)
    unread: int = 0
    is_participant: bool = True

    @property
    def code(self):
        return self.label

    @property
    def label(self):
        names = ", ".join(name for _, name, _ in self.participants)
        return self.title or names or "Conversation"

    @classmethod
    def from_api(cls, row):
        return cls(
            row["id"],
            row.get("conversation_type") or "",
            row.get("title") or "",
            str(row.get("student") or ""),
            bool(row.get("active", True)),
            _datetime(row.get("last_message_at")),
            tuple(
                (p["member"], p.get("name") or "", bool(p.get("active", True))) for p in row.get("participants") or ()
            ),
            int(row.get("unread_count") or 0),
            bool(row.get("is_participant", True)),
        )


@dataclass(frozen=True)
class ChatMessage:
    id: str
    conversation_id: str
    sender_id: str
    sender_name: str
    body: str | None
    created_at: datetime | None
    deleted: bool = False
    attachments: tuple = ()
    client_id: str = ""

    @classmethod
    def from_api(cls, row):
        return cls(
            row["id"],
            str(row.get("conversation") or ""),
            str(row.get("sender") or ""),
            row.get("sender_name") or "",
            row.get("body"),
            _datetime(row.get("created_at")),
            bool(row.get("deleted_at")),
            tuple(Attachment.from_api(a, "message") for a in row.get("attachments") or ()),
            row.get("client_id") or "",
        )


@dataclass(frozen=True)
class ForumSpace:
    id: str
    name: str
    description: str
    audience: str
    roles: tuple
    class_id: str
    announcements_only: bool
    active: bool

    @property
    def code(self):
        return self.name

    @classmethod
    def from_api(cls, row):
        return cls(
            row["id"],
            row.get("name") or "",
            row.get("description") or "",
            row.get("audience") or "",
            tuple(row.get("roles") or ()),
            str(row.get("school_class") or ""),
            bool(row.get("announcements_only")),
            bool(row.get("active", True)),
        )


@dataclass(frozen=True)
class Thread:
    id: str
    space_id: str
    title: str
    kind: str
    status: str
    status_reason: str
    author_name: str
    created_at: datetime | None
    last_post_at: datetime | None

    @property
    def code(self):
        return self.title

    @property
    def active(self):
        return self.status == "OPEN"

    @classmethod
    def from_api(cls, row):
        return cls(
            row["id"],
            str(row.get("space") or ""),
            row.get("title") or "",
            row.get("thread_type") or "GENERAL",
            row.get("status") or "OPEN",
            row.get("status_reason") or "",
            row.get("author_name") or "",
            _datetime(row.get("created_at")),
            _datetime(row.get("last_post_at")),
        )


@dataclass(frozen=True)
class Post:
    id: str
    author_name: str
    kind: str
    body: str | None
    created_at: datetime | None
    deleted: bool
    deletion_reason: str = ""

    @classmethod
    def from_api(cls, row):
        return cls(
            row["id"],
            row.get("author_name") or "",
            row.get("post_type") or "MESSAGE",
            row.get("body"),
            _datetime(row.get("created_at")),
            bool(row.get("deleted_at")),
            row.get("deletion_reason") or "",
        )


@dataclass(frozen=True)
class Complaint:
    id: str
    author_id: str
    student_id: str
    category: str
    subject: str
    description: str
    priority: str
    status: str
    assigned_to: str
    created_at: datetime | None
    submitted_at: datetime | None = None
    history: tuple = ()  # (old status, new status, changed_by id, comment, at)
    attachments: tuple = ()

    @property
    def code(self):
        return self.subject

    @property
    def active(self):
        return self.status in ("OPEN", "IN_PROGRESS", "RESOLVED")

    @property
    def status_label(self):
        return COMPLAINT_STATUSES.get(self.status, self.status)

    @classmethod
    def from_api(cls, row):
        return cls(
            row["id"],
            str(row.get("author") or ""),
            str(row.get("student") or ""),
            row.get("category") or "",
            row.get("subject") or "",
            row.get("description") or "",
            row.get("priority") or "NORMAL",
            row.get("status") or "",
            str(row.get("assigned_to") or ""),
            _datetime(row.get("created_at")),
            _datetime(row.get("submitted_at")),
            tuple(
                (
                    h.get("old_status") or "",
                    h.get("new_status") or "",
                    str(h.get("changed_by") or ""),
                    h.get("comment") or "",
                    _datetime(h.get("at")),
                )
                for h in row.get("history") or ()
            ),
            tuple(Attachment.from_api(a, "complaint") for a in row.get("attachments") or ()),
        )


# --- documents (backend documents/api.py, ADR 0016 / 0023) ---------------------------

DOCUMENT_KINDS = {
    "REPORT_CARD": "Bulletin scolaire",
    "STUDENT_CARD": "Carte d'élève",
    "TIMETABLE": "Emploi du temps",
    "PAYMENT_RECEIPT": "Reçu de paiement",
    "PAYSLIP": "Bulletin de paie",
    "STUDENT_ATTENDANCE": "Relevé de présence (élève)",
    "CLASS_ATTENDANCE": "Registre de présence (classe)",
}
DOCUMENT_STATUSES = {"OFFICIAL": "Officiel", "PROVISIONAL": "Provisoire", "SUPERSEDED": "Remplacé"}


@dataclass(frozen=True)
class Document:
    id: str
    kind: str
    status: str
    title: str
    version: int
    file_name: str
    size_bytes: int
    sha256: str
    verification_code: str
    generated_at: datetime | None
    params: dict = field(default_factory=dict, compare=False, hash=False)

    @property
    def code(self):
        return self.title

    @property
    def active(self):
        return self.status != "SUPERSEDED"

    @property
    def status_label(self):
        return DOCUMENT_STATUSES.get(self.status, self.status)

    @property
    def kind_label(self):
        return DOCUMENT_KINDS.get(self.kind, self.kind)

    @classmethod
    def from_api(cls, row):
        return cls(
            row["id"],
            row.get("kind") or "",
            row.get("status") or "",
            row.get("title") or "",
            int(row.get("version") or 1),
            row.get("file_name") or "",
            int(row.get("size_bytes") or 0),
            row.get("sha256") or "",
            row.get("verification_code") or "",
            _datetime(row.get("generated_at")),
            dict(row.get("params") or {}),
        )


# --- account lifecycle (backend accounts/activation_api.py, ADR 0024) ----------------

ACCOUNT_STATES = {
    "ACTIVE": "Compte activé",
    "PENDING_ACTIVATION": "En attente d'activation",
    "NOT_ACTIVATED": "Non activé",
    "DISABLED": "Compte suspendu",
}


@dataclass(frozen=True)
class AccountSummary:
    """What the administration may know about an account — never a code."""

    membership_id: str
    name: str
    login: str
    state: str
    last_login: datetime | None = None
    pending_expires_at: datetime | None = None
    last_issued_at: datetime | None = None
    activated_at: datetime | None = None

    @property
    def state_label(self):
        return ACCOUNT_STATES.get(self.state, self.state)

    @classmethod
    def from_api(cls, row):
        return cls(
            row["membership"],
            row.get("name") or "",
            row.get("login") or "",
            row.get("state") or "",
            _datetime(row.get("last_login")),
            _datetime(row.get("pending_expires_at")),
            _datetime(row.get("last_issued_at")),
            _datetime(row.get("activated_at")),
        )


# =============================================================================
# Parent registrations and verified links (backend people/parent_workflow_api.py, ADR 0026)
# =============================================================================

REGISTRATION_STATUSES = {"PENDING": "En attente", "APPROVED": "Validée", "REJECTED": "Refusée"}
LINK_REQUEST_STATUSES = {"PENDING": "En cours", "APPROVED": "Validée", "REJECTED": "Refusée", "CANCELLED": "Annulée"}
IDENTITY_STATUSES = {"PENDING": "À vérifier", "VERIFIED": "Vérifiée", "REJECTED": "Refusée"}
IDENTITY_METHODS = {"ID_DOCUMENT": "Pièce d'identité", "SPONSOR_2FA": "Parrainage (code à usage unique)"}
STUDENT_APPROVALS = {
    "PENDING": "À confirmer par l'élève",
    "APPROVED": "Confirmée par l'élève",
    "REJECTED": "Refusée par l'élève",
    "NOT_REQUIRED": "Non requise",
}
IDENTITY_DOCUMENTS = {
    "CNI": "Carte nationale d'identité",
    "PASSPORT": "Passeport",
    "RESIDENCE_PERMIT": "Titre de séjour",
    "OTHER": "Autre pièce officielle",
}
RELATIONSHIPS = {
    "MOTHER": "Mère",
    "FATHER": "Père",
    "LEGAL_GUARDIAN": "Tuteur légal",
    "TUTOR": "Tuteur",
    "OTHER": "Autre",
}


@dataclass(frozen=True)
class ParentRegistration:
    """A parent account created from the app, waiting for the school."""

    id: str
    status: str
    applicant_name: str
    email: str
    phone: str
    submitted_at: datetime | None = None
    reviewed_at: datetime | None = None
    rejection_reason: str = ""

    @property
    def status_label(self):
        return REGISTRATION_STATUSES.get(self.status, self.status)

    @property
    def active(self):  # list pages: "still to decide"
        return self.status == "PENDING"

    @classmethod
    def from_api(cls, row):
        return cls(
            row["id"],
            row.get("status") or "",
            row.get("applicant_name") or "",
            row.get("applicant_email") or "",
            row.get("applicant_phone") or "",
            _datetime(row.get("submitted_at")),
            _datetime(row.get("reviewed_at")),
            row.get("rejection_reason") or "",
        )


@dataclass(frozen=True)
class LinkRequest:
    """« This is my child »: what the administration needs to decide —
    never the identity document number (the server keeps an HMAC only)."""

    id: str
    student_id: str
    student_name: str
    student_number: str
    class_name: str
    parent_name: str
    parent_email: str
    parent_phone: str
    relationship_type: str
    status: str
    identity_status: str
    identity_method: str
    document_type: str
    identity_failed_checks: int
    student_approval_status: str
    student_approval_note: str
    sponsored: bool
    sponsor_name: str
    created_at: datetime | None = None
    decision_reason: str = ""

    @property
    def status_label(self):
        return LINK_REQUEST_STATUSES.get(self.status, self.status)

    @property
    def identity_label(self):
        label = IDENTITY_STATUSES.get(self.identity_status, self.identity_status)
        return f"{label} ({IDENTITY_METHODS.get(self.identity_method, self.identity_method).lower()})"

    @property
    def approval_label(self):
        return STUDENT_APPROVALS.get(self.student_approval_status, self.student_approval_status)

    @property
    def relationship_label(self):
        return RELATIONSHIPS.get(self.relationship_type, self.relationship_type)

    @property
    def pending(self):
        return self.status == "PENDING"

    active = pending  # list pages: "still to decide"

    @property
    def ready(self):
        """What the server requires before approving (it re-checks)."""
        return (
            self.pending
            and self.identity_status == "VERIFIED"
            and self.student_approval_status in ("APPROVED", "NOT_REQUIRED")
        )

    @classmethod
    def from_api(cls, row):
        student = row.get("student") or {}
        parent = row.get("parent") or {}
        return cls(
            row["id"],
            student.get("id") or "",
            student.get("name") or "",
            student.get("student_number") or "",
            row.get("class_name") or "",
            parent.get("name") or "",
            parent.get("email") or "",
            parent.get("phone") or "",
            row.get("relationship_type") or "",
            row.get("status") or "",
            row.get("identity_status") or "",
            row.get("identity_method") or "",
            row.get("document_type") or "",
            int(row.get("identity_failed_checks") or 0),
            row.get("student_approval_status") or "",
            row.get("student_approval_note") or "",
            bool(row.get("sponsored")),
            row.get("sponsor_name") or "",
            _datetime(row.get("created_at")),
            row.get("decision_reason") or "",
        )


# =============================================================================
# School plans (backend documents/plans_api.py)
# =============================================================================

PLAN_STATUSES = {"DRAFT": "Brouillon", "PUBLISHED": "Publié", "WITHDRAWN": "Retiré"}
PLAN_VERSION_STATUSES = {"DRAFT": "Importée", "PUBLISHED": "Publiée (courante)", "SUPERSEDED": "Remplacée"}
PLAN_DISTRIBUTIONS = {"AUTO": "Automatique", "MANUAL": "Manuelle"}
PLAN_AUDIENCE_TARGETS = {
    "SCHOOL_PARENTS": "Tous les parents vérifiés de l'école",
    "SCHOOL_TEACHERS": "Tous les enseignants en activité de l'école",
    "CLASS_PARENTS": "Parents vérifiés des élèves de la classe",
    "CLASS_TEACHERS": "Enseignants de la classe",
}
PLAN_FORMATS = {"application/pdf": "PDF", "image/png": "PNG", "image/jpeg": "JPEG"}


def _size_label(size):
    if size is None:
        return "—"
    return f"{size / 1024 / 1024:.1f} Mo" if size >= 1024 * 1024 else f"{max(1, round(size / 1024))} Ko"


@dataclass
class PlanVersion:
    id: str
    number: int
    status: str
    original_name: str
    mime_type: str
    size_bytes: int
    width: int | None
    height: int | None
    page_count: int | None
    uploaded_by: str
    uploaded_at: datetime | None
    published_at: datetime | None
    is_current: bool

    @property
    def code(self):
        return f"v{self.number}"

    @property
    def is_image(self):
        return self.mime_type.startswith("image/")

    @property
    def status_label(self):
        return PLAN_VERSION_STATUSES.get(self.status, self.status)

    @property
    def details(self):
        """« PDF · 2 pages · 1.2 Mo » / « PNG · 4000×3000 px · 850 Ko »."""
        parts = [PLAN_FORMATS.get(self.mime_type, self.mime_type)]
        if self.page_count:
            parts.append(f"{self.page_count} page{'s' if self.page_count > 1 else ''}")
        if self.width and self.height:
            parts.append(f"{self.width}×{self.height} px")
        parts.append(_size_label(self.size_bytes))
        return " · ".join(parts)

    @classmethod
    def from_api(cls, row):
        return cls(
            row["id"],
            int(row["number"]),
            row["status"],
            row.get("original_name") or "",
            row["mime_type"],
            int(row.get("size_bytes") or 0),
            row.get("width"),
            row.get("height"),
            row.get("page_count"),
            row.get("uploaded_by_name") or "",
            _datetime(row.get("uploaded_at")),
            _datetime(row.get("published_at")),
            bool(row.get("is_current")),
        )


@dataclass
class SchoolPlan:
    id: str
    title: str
    description: str
    building: str
    floor: str
    display_order: int
    status: str
    distribution: str
    current_version: PlanVersion | None
    published_at: datetime | None
    published_by: str
    versions_count: int
    audience: list = field(default_factory=list)  # [{"target", "school_class", "school_class_name"}]

    @property
    def code(self):
        return self.title

    @property
    def active(self):
        return self.status == "PUBLISHED"

    @property
    def status_label(self):
        return PLAN_STATUSES.get(self.status, self.status)

    @property
    def distribution_label(self):
        return PLAN_DISTRIBUTIONS.get(self.distribution, self.distribution)

    @property
    def location(self):
        return " · ".join(part for part in (self.building, self.floor) if part) or "—"

    @classmethod
    def from_api(cls, row):
        current = row.get("current_version")
        return cls(
            row["id"],
            row["title"],
            row.get("description") or "",
            row.get("building") or "",
            row.get("floor") or "",
            int(row.get("display_order") or 0),
            row["status"],
            row.get("distribution") or "AUTO",
            PlanVersion.from_api(current) if current else None,
            _datetime(row.get("published_at")),
            row.get("published_by_name") or "",
            int(row.get("versions_count") or 0),
            list(row.get("audience") or []),
        )
