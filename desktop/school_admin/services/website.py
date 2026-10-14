"""Site ISBREE (backend apps/website/admin_api.py and apps/admissions/admin_api.py,
ADR 0032). Thin client: the server validates every content, decides the
publication, re-encodes images, checks PDFs and refuses unsigned / debug APKs,
controls the pre-enrollment transitions and issues the invitation codes. The
desktop sends the chosen file's NAME and BYTES only (never a local path).

    GET  admin/pre-enrollments/?status=&search=      GET admin/pre-enrollments/{id}/
    POST admin/pre-enrollments/{id}/status/ {status, note, message_to_family}
    POST admin/pre-enrollments/{id}/invite/          -> {code, link, expires_at} shown ONCE
    GET/POST admin/website/{kind}/   GET/PATCH admin/website/{kind}/{id}/
         kind = pages | faq | news | locations | resources | images
    POST admin/website/images/upload/ (multipart)    GET admin/website/images/{id}/file/
    POST admin/website/resources/{id}/document/ (multipart PDF)
    GET/PATCH admin/website/profile/                 GET admin/website/readiness/
    GET/POST admin/website/releases/ (multipart APK) POST admin/website/releases/{id}/status/
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from ..api.errors import ValidationFailed
from ..i18n import Labels, tr

PRE_ENROLLMENT_STATUSES = Labels(
    {
        "RECEIVED": "Reçue",
        "UNDER_REVIEW": "En examen",
        "INFO_REQUESTED": "Informations demandées",
        "ACCEPTED": "Acceptée",
        "REJECTED": "Refusée",
    }
)
PUBLICATION_STATUSES = Labels({"DRAFT": "Brouillon", "PUBLISHED": "Publié", "ARCHIVED": "Archivé"})
RELEASE_STATUSES = Labels({"DRAFT": "Brouillon", "PUBLISHED": "Publiée", "WITHDRAWN": "Retirée"})
INVITATION_STATES = Labels(
    {
        "NONE": "Aucune invitation",
        "PENDING": "Invitation en attente d'activation",
        "EXPIRED": "Invitation expirée",
        "REVOKED": "Invitation remplacée",
        "USED": "Compte activé",
    }
)
AUDIENCES = Labels(
    {
        "PUBLIC": "Site public",
        "PARENT": "Parents",
        "TEACHER": "Enseignants",
        "STAFF": "Personnel",
        "GUARDIAN": "Gardiens",
    }
)
APPS = Labels(
    {
        "PARENT": "Application Parent",
        "TEACHER": "Application Enseignant",
        "STAFF": "Application Personnel",
        "GUARDIAN": "Application Gardien",
    }
)
PAGE_KINDS = Labels(
    {
        "ABOUT": "À propos",
        "PEDAGOGY": "Approche pédagogique",
        "ORGANIZATION": "Organisation",
        "SCHOOL_LIFE": "Vie scolaire",
        "ADMISSIONS": "Admissions",
        "PRACTICAL": "Informations pratiques",
        "TEACHING_POLICY": "Politique pédagogique (enseignants)",
        "LEGAL_NOTICE": "Mentions légales",
        "PRIVACY": "Confidentialité",
        "TERMS": "Conditions d'utilisation",
        "RULES": "Règlement intérieur",
        "OTHER": "Autre page",
    }
)
FAQ_CATEGORIES = Labels(
    {
        "ADMISSIONS": "Admissions",
        "PREENROLLMENT": "Préinscription",
        "ORGANIZATION": "Organisation scolaire",
        "DOCUMENTS": "Documents",
        "ACTIVATION": "Activation du compte",
        "PORTAL": "Espace ISBREE",
        "CONTACT": "Contacts",
        "PRACTICAL": "Informations pratiques",
        "TEACHING": "Enseignement",
        "WORK": "Vie professionnelle",
    }
)
NEWS_CATEGORIES = Labels(
    {"NEWS": "Actualité", "EVENT": "Événement", "SCHOOL_LIFE": "Vie scolaire", "ANNOUNCEMENT": "Annonce"}
)
RESOURCE_KINDS = Labels(
    {
        "SUPPLIES": "Fournitures",
        "PROGRAMME": "Programme",
        "PRACTICAL_INFO": "Informations pratiques",
        "CALENDAR": "Calendrier",
        "INSTRUCTION": "Consignes",
        "PROCEDURE": "Procédure",
        "MISSION": "Mission",
        "DOCUMENT": "Document",
    }
)
IMAGE_CATEGORIES = Labels(
    {
        "CLASSROOMS": "Salles de classe",
        "CAMPUS": "Établissement",
        "SPORTS": "Sport",
        "ACTIVITIES": "Activités",
        "EVENTS": "Événements",
        "OTHER": "Autre",
    }
)
# Readiness codes (apps/website/readiness.py): shown in the desktop's language;
# an unknown code falls back to the server's own message.
READINESS = Labels(
    {
        "contact_email": "Adresse e-mail de contact non renseignée.",
        "contact_phone": "Numéro de téléphone de contact non renseigné.",
        "profile_missing": "Présentation de l'établissement absente.",
        "profile_to_validate": "Présentation de l'établissement encore à valider.",
        "address_unconfirmed": "Adresse exacte de l'établissement non confirmée.",
        "page_legal_notice": "Page « Mentions légales » non publiée.",
        "page_privacy": "Page « Confidentialité » non publiée.",
        "page_terms": "Page « Conditions d'utilisation » non publiée.",
        "page_to_validate": "Pages publiées avec un texte à valider.",
        "faqentry_to_validate": "Questions de la FAQ publiées avec un texte à valider.",
        "newsarticle_to_validate": "Actualités publiées avec un texte à valider.",
        "roleresource_to_validate": "Ressources publiées avec un texte à valider.",
        "page_demo": "Contenus de démonstration publiés (pages).",
        "faqentry_demo": "Contenus de démonstration publiés (questions).",
        "newsarticle_demo": "Contenus de démonstration publiés (actualités).",
        "roleresource_demo": "Contenus de démonstration publiés (ressources).",
        "sitelocation_demo": "Contenus de démonstration publiés (lieux).",
        "contentimage_demo": "Contenus de démonstration publiés (images).",
        "illustrations": "Images d'illustration publiées (ce ne sont pas des photos de l'établissement).",
        "pre_enrollment_closed": "Aucun niveau ou aucune année ouverte : la préinscription est fermée.",
        "app_parent": "Application Parent : aucune version Release signée publiée.",
        "app_teacher": "Application Enseignant : aucune version Release signée publiée.",
        "app_staff": "Application Personnel : aucune version Release signée publiée.",
        "app_guardian": "Application Gardien : aucune version Release signée publiée.",
    }
)
IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
IMAGE_FILTER = "Images (*.jpg *.jpeg *.png *.webp)"
PDF_FILTER = "PDF (*.pdf)"
APK_FILTER = "Application Android (*.apk)"


def _moment(value):
    return datetime.fromisoformat(value) if value else None


def _day(value):
    return date.fromisoformat(value) if value else None


def read_file(path, types=None, default="application/octet-stream"):
    """(bare name, bytes, declared type) of a chosen file: the server decides
    the real type from the content."""
    local = Path(path)
    return local.name, local.read_bytes(), (types or {}).get(local.suffix.lower(), default)


@dataclass
class PreEnrollment:
    id: str
    reference: str
    guardian: str
    guardian_phone: str
    guardian_email: str
    relationship: str
    child: str
    child_birth_date: date | None
    level: str
    year: str
    previous_school: str
    comment: str
    status: str
    submitted_at: datetime | None
    decided_at: datetime | None
    message_to_family: str
    has_account: bool
    consent_at: datetime | None = None
    consent_version: str = ""
    events: list = field(default_factory=list)
    invitation: dict = field(default_factory=dict)
    allowed: list = field(default_factory=list)

    @property
    def status_label(self):
        return PRE_ENROLLMENT_STATUSES.get(self.status, self.status)

    @property
    def active(self):  # list pages expect it
        return True

    @classmethod
    def from_api(cls, row):
        return cls(
            id=row["id"],
            reference=row["reference"],
            guardian=f"{row['guardian_first_name']} {row['guardian_last_name']}".strip(),
            guardian_phone=row.get("guardian_phone", ""),
            guardian_email=row.get("guardian_email", ""),
            relationship=row.get("relationship_label") or row.get("relationship", ""),
            child=f"{row['child_first_name']} {row['child_last_name']}".strip(),
            child_birth_date=_day(row.get("child_birth_date")),
            level=row.get("requested_level", ""),
            year=row.get("requested_year", ""),
            previous_school=row.get("previous_school", ""),
            comment=row.get("comment", ""),
            status=row["status"],
            submitted_at=_moment(row.get("submitted_at")),
            decided_at=_moment(row.get("decided_at")),
            message_to_family=row.get("message_to_family") or "",
            has_account=bool(row.get("has_account")),
            consent_at=_moment(row.get("consent_at")),
            consent_version=row.get("consent_version", ""),
            events=row.get("events", []),
            invitation=row.get("invitation", {}),
            allowed=row.get("allowed", []),
        )


@dataclass
class Content:
    """A row of an editorial table (page, question, article, location, resource, image)."""

    kind: str
    id: str
    data: dict

    @property
    def status(self):
        return self.data.get("status", "DRAFT")

    @property
    def status_label(self):
        return PUBLICATION_STATUSES.get(self.status, self.status)

    @property
    def active(self):
        return True

    @property
    def title(self):
        d = self.data
        return d.get("title") or d.get("question") or d.get("name") or d.get("alt_text") or ""

    @property
    def updated_at(self):
        return _moment(self.data.get("updated_at"))

    @property
    def audience_label(self):
        return ", ".join(AUDIENCES.get(a, a) for a in self.data.get("audiences", []))


@dataclass
class Release:
    id: str
    app: str
    version_name: str
    version_code: int
    release_notes: str
    min_android: str
    file_name: str
    size: int
    sha256: str
    status: str
    published_at: datetime | None

    @property
    def app_label(self):
        return APPS.get(self.app, self.app)

    @property
    def status_label(self):
        return RELEASE_STATUSES.get(self.status, self.status)

    @property
    def active(self):
        return True

    @classmethod
    def from_api(cls, row):
        return cls(
            id=row["id"],
            app=row["app"],
            version_name=row["version_name"],
            version_code=int(row["version_code"]),
            release_notes=row.get("release_notes", ""),
            min_android=row.get("min_android", ""),
            file_name=row.get("file_name", ""),
            size=int(row.get("size") or 0),
            sha256=row.get("sha256", ""),
            status=row["status"],
            published_at=_moment(row.get("published_at")),
        )


class WebsiteService:
    PAGE_SIZE = 50
    KINDS = ("pages", "faq", "news", "locations", "resources", "images")

    def __init__(self, api):
        self.api = api

    # --- pre-enrollments (administrators) --------------------------------------------
    def pre_enrollments(self, *, page=1, status=None, search=None):
        rows, total = self.api.page(
            "admin/pre-enrollments/",
            page=page,
            page_size=self.PAGE_SIZE,
            status=status or None,
            search=(search or "").strip() or None,
        )
        return [PreEnrollment.from_api(r) for r in rows], total

    def pre_enrollment(self, request_id):
        return PreEnrollment.from_api(self.api.get(f"admin/pre-enrollments/{request_id}/"))

    def change_status(self, request_id, status, *, note="", message_to_family=None):
        if status in ("REJECTED", "INFO_REQUESTED") and not (note or "").strip():
            raise ValidationFailed("Formulaire incomplet.", details={"note": [tr("Obligatoire.")]})
        payload = {"status": status, "note": (note or "").strip()}
        if message_to_family is not None:
            payload["message_to_family"] = message_to_family.strip()
        return PreEnrollment.from_api(self.api.post(f"admin/pre-enrollments/{request_id}/status/", payload))

    def invite(self, request_id):
        """{code, link, expires_at}: the ONLY time the code is visible. Nothing is e-mailed."""
        result = self.api.post(f"admin/pre-enrollments/{request_id}/invite/")
        return {**result, "expires_at": _moment(result.get("expires_at"))}

    # --- editorial contents (administrators and content managers) -------------------------
    def contents(self, kind, *, status=None):
        assert kind in self.KINDS, kind
        rows = self.api.get(f"admin/website/{kind}/", status=status or None) or []
        return [Content(kind, row["id"], row) for row in rows]

    def save(self, kind, values, content_id=None):
        assert kind in self.KINDS, kind
        if content_id:
            row = self.api.patch(f"admin/website/{kind}/{content_id}/", values)
        else:
            row = self.api.post(f"admin/website/{kind}/", values)
        return Content(kind, row["id"], row)

    def set_status(self, content, status):
        return self.save(content.kind, {"status": status}, content.id)

    def upload_image(self, path, values):
        """Runs in the worker thread. The server re-encodes the picture (no EXIF kept)."""
        name, content, content_type = read_file(path, IMAGE_TYPES)
        fields = {
            k: ("true" if v else "false") if isinstance(v, bool) else str(v)
            for k, v in values.items()
            if k != "audiences"
        }
        fields["audiences"] = list(values.get("audiences") or ["PUBLIC"])  # one multipart field per audience
        row = self.api.post_multipart("admin/website/images/upload/", fields, [("file", (name, content, content_type))])
        return Content("images", row["id"], row)

    def image_file(self, image_id):
        return self.api.get_bytes(f"admin/website/images/{image_id}/file/")

    def attach_document(self, resource_id, path):
        name, content, _ = read_file(path)
        row = self.api.post_multipart(
            f"admin/website/resources/{resource_id}/document/", {}, [("file", (name, content, "application/pdf"))]
        )
        return Content("resources", row["id"], row)

    # --- profile and readiness ----------------------------------------------------------
    def profile(self):
        return self.api.get("admin/website/profile/")

    def save_profile(self, values):
        return self.api.patch("admin/website/profile/", values)

    def readiness(self):
        """{ready, items[{code, severity, message, count}]}: what still prevents an opening."""
        return self.api.get("admin/website/readiness/")

    # --- mobile applications ------------------------------------------------------------
    def releases(self):
        return [Release.from_api(r) for r in self.api.get("admin/website/releases/") or []]

    def add_release(self, path, *, app, version_name, version_code, release_notes="", min_android=""):
        """Runs in the worker thread (an APK weighs up to 300 MB). The server refuses
        an unsigned or debug-signed APK and a version code already used."""
        if not (version_name or "").strip() or not str(version_code or "").strip():
            raise ValidationFailed(
                "Formulaire incomplet.",
                details={
                    k: [tr("Obligatoire.")]
                    for k, v in (("version_name", version_name), ("version_code", version_code))
                    if not str(v or "").strip()
                },
            )
        name, content, _ = read_file(path)
        fields = {
            "app": app,
            "version_name": version_name.strip(),
            "version_code": str(int(version_code)),
            "release_notes": (release_notes or "").strip(),
            "min_android": (min_android or "").strip(),
        }
        row = self.api.post_multipart(
            "admin/website/releases/", fields, [("file", (name, content, "application/vnd.android.package-archive"))]
        )
        return Release.from_api(row)

    def set_release_status(self, release_id, status):
        return Release.from_api(self.api.post(f"admin/website/releases/{release_id}/status/", {"status": status}))
