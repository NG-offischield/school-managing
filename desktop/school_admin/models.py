"""Plain data objects built from API payloads (no business rule here)."""

from dataclasses import dataclass, field
from datetime import date, datetime

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

    @property
    def label(self):
        places = f" · {self.capacity} places" if self.capacity else ""
        return f"{self.code} — {self.name}{places}"

    @classmethod
    def from_api(cls, row):
        return cls(row["id"], row["code"], row["name"], row.get("capacity"), bool(row.get("active")))


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
