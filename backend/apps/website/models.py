"""ISBREE web content (ADR 0032): what the public site and the Espace ISBREE
portal show, administered from the PySide6 desktop through the API.

Typed models, not one generic "content" table:
- SiteProfile: the school's public presentation (complements core.School,
  which already holds name, address, phone, e-mail, mission, vision...);
- SiteLocation: campuses / annexes (a demonstration one is flagged is_demo);
- Page: institutional and regulatory pages (about, pedagogy, legal notice...);
- FaqEntry, NewsArticle, ContentImage (gallery and illustrations);
- RoleResource: what one role needs (supplies lists, programmes, instructions,
  missions, procedures...), optionally scoped to a level, a class, a school
  year or a staff function;
- MobileAppRelease: the downloadable Android applications (signed release
  builds only; a debug build is refused at upload).

Audience: PUBLIC (anyone, public site) or role codes of the school
(PARENT, TEACHER, STAFF, GUARDIAN). The SERVER filters by audience and by the
caller's roles: a client never receives content it may not see.

Every editable text can be flagged `to_validate` (provisional wording the
school must confirm) or `is_demo` (fictitious demonstration content): both
are shown as such and listed by the production readiness check.

Files (images, PDF, APK) live in the private storage: no public URL; views
stream them after checking publication and audience.
"""

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q

from common.models import TenantModel

PUBLIC = "PUBLIC"
PORTAL_ROLES = ("PARENT", "TEACHER", "STAFF", "GUARDIAN")
AUDIENCES = (PUBLIC, *PORTAL_ROLES)


class PublicationStatus(models.TextChoices):
    DRAFT = "DRAFT", "Brouillon"
    PUBLISHED = "PUBLISHED", "Publié"
    ARCHIVED = "ARCHIVED", "Archivé"


def _audiences_field(**kwargs):
    return ArrayField(models.CharField(max_length=20), default=list, **kwargs)


def _audience_constraint(prefix, allowed=AUDIENCES):
    return models.CheckConstraint(
        condition=Q(audiences__contained_by=list(allowed)) & ~Q(audiences=[]),
        name=f"{prefix}_audiences_valid",
    )


def _status_constraint(prefix):
    return models.CheckConstraint(condition=Q(status__in=PublicationStatus.values), name=f"{prefix}_status_valid")


class Editorial(TenantModel):
    """Shared editorial fields."""

    status = models.CharField(
        max_length=20, choices=PublicationStatus.choices, default=PublicationStatus.DRAFT, db_index=True
    )
    to_validate = models.BooleanField(default=False)  # provisional wording, to be confirmed by the school
    is_demo = models.BooleanField(default=False)  # fictitious demonstration content
    order = models.PositiveIntegerField(default=0)

    class Meta:
        abstract = True


class SiteProfile(TenantModel):
    """Public presentation of the school, one per school (core.School keeps
    the identity: name, address, city, phone, e-mail, mission, vision, history)."""

    tagline = models.CharField(max_length=200, blank=True)
    presentation = models.TextField(blank=True)
    values = models.TextField(blank=True)  # one value per line
    pedagogy = models.TextField(blank=True)
    location_details = models.CharField(max_length=200, blank=True)  # e.g. "Etoug-Ebe, Yaoundé"
    office_hours = models.CharField(max_length=200, blank=True)
    address_confirmed = models.BooleanField(default=False)  # the exact address is validated by the school
    to_validate = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["school"], name="site_profile_one_per_school")]


class SiteLocation(Editorial):
    """A campus or annex. A demonstration location (is_demo) is shown as
    fictitious and never with coordinates or a map link."""

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    address_text = models.CharField(max_length=200, blank=True)
    is_main = models.BooleanField(default=False)

    class Meta:
        ordering = ["order", "name"]
        constraints = [_status_constraint("site_location")]


class PageKind(models.TextChoices):
    ABOUT = "ABOUT", "À propos"
    PEDAGOGY = "PEDAGOGY", "Approche pédagogique"
    ORGANIZATION = "ORGANIZATION", "Organisation scolaire"
    SCHOOL_LIFE = "SCHOOL_LIFE", "Vie scolaire"
    ADMISSIONS = "ADMISSIONS", "Admissions"
    PRACTICAL = "PRACTICAL", "Informations pratiques"
    TEACHING_POLICY = "TEACHING_POLICY", "Politique d'enseignement"
    LEGAL_NOTICE = "LEGAL_NOTICE", "Mentions légales"
    PRIVACY = "PRIVACY", "Politique de confidentialité"
    TERMS = "TERMS", "Conditions d'utilisation"
    RULES = "RULES", "Règlement"
    OTHER = "OTHER", "Autre"


class Page(Editorial):
    """Institutional or regulatory page. `body` is plain text with a minimal
    markup (blank line = paragraph, "## " = heading, "- " = list item),
    rendered as text by the clients — never as HTML."""

    kind = models.CharField(max_length=30, choices=PageKind.choices)
    slug = models.SlugField(max_length=80)
    title = models.CharField(max_length=200)
    summary = models.CharField(max_length=400, blank=True)
    body = models.TextField(blank=True)
    audiences = _audiences_field()

    class Meta:
        ordering = ["order", "title"]
        constraints = [
            models.UniqueConstraint(fields=["school", "slug"], name="page_slug_unique"),
            models.CheckConstraint(condition=Q(kind__in=PageKind.values), name="page_kind_valid"),
            _audience_constraint("page"),
            _status_constraint("page"),
        ]


class FaqCategory(models.TextChoices):
    ADMISSIONS = "ADMISSIONS", "Admissions"
    PREENROLLMENT = "PREENROLLMENT", "Préinscription"
    ORGANIZATION = "ORGANIZATION", "Organisation scolaire"
    DOCUMENTS = "DOCUMENTS", "Documents"
    ACTIVATION = "ACTIVATION", "Activation du compte"
    PORTAL = "PORTAL", "Espace ISBREE"
    CONTACT = "CONTACT", "Contacts"
    PRACTICAL = "PRACTICAL", "Informations pratiques"
    TEACHING = "TEACHING", "Enseignement"
    WORK = "WORK", "Vie professionnelle"


class FaqEntry(Editorial):
    category = models.CharField(max_length=30, choices=FaqCategory.choices)
    question = models.CharField(max_length=300)
    answer = models.TextField()
    audiences = _audiences_field()

    class Meta:
        ordering = ["category", "order", "question"]
        constraints = [
            models.CheckConstraint(condition=Q(category__in=FaqCategory.values), name="faq_category_valid"),
            _audience_constraint("faq"),
            _status_constraint("faq"),
        ]


class ImageCategory(models.TextChoices):
    CLASSROOMS = "CLASSROOMS", "Salles de classe"
    CAMPUS = "CAMPUS", "Établissement"
    SPORTS = "SPORTS", "Sport"
    ACTIVITIES = "ACTIVITIES", "Activités"
    EVENTS = "EVENTS", "Événements"
    OTHER = "OTHER", "Autre"


class ContentImage(Editorial):
    """An image of the gallery or an illustration (news cover...). Stored
    re-encoded (EXIF / GPS removed). `is_illustration`: not a photograph of the
    school itself (stock or provided illustration) — always said so; photographs
    of pupils need the families' authorisation before publication."""

    storage_path = models.CharField(max_length=300)
    mime_type = models.CharField(max_length=40)
    size = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    alt_text = models.CharField(max_length=250)
    caption = models.CharField(max_length=300, blank=True)
    credit = models.CharField(max_length=200, blank=True)
    category = models.CharField(max_length=30, choices=ImageCategory.choices, default=ImageCategory.OTHER)
    in_gallery = models.BooleanField(default=True)
    is_illustration = models.BooleanField(default=True)
    audiences = _audiences_field()

    class Meta:
        ordering = ["order", "-created_at"]
        constraints = [
            models.CheckConstraint(condition=~Q(alt_text=""), name="content_image_alt_required"),
            models.CheckConstraint(condition=Q(category__in=ImageCategory.values), name="content_image_category_valid"),
            _audience_constraint("content_image"),
            _status_constraint("content_image"),
        ]


class NewsCategory(models.TextChoices):
    NEWS = "NEWS", "Actualité"
    EVENT = "EVENT", "Événement"
    SCHOOL_LIFE = "SCHOOL_LIFE", "Vie scolaire"
    ANNOUNCEMENT = "ANNOUNCEMENT", "Annonce"


class NewsArticle(Editorial):
    slug = models.SlugField(max_length=120)
    title = models.CharField(max_length=200)
    summary = models.CharField(max_length=400)
    body = models.TextField(blank=True)
    category = models.CharField(max_length=30, choices=NewsCategory.choices, default=NewsCategory.NEWS)
    event_date = models.DateField(blank=True, null=True)
    cover = models.ForeignKey(ContentImage, on_delete=models.SET_NULL, blank=True, null=True, related_name="+")
    audiences = _audiences_field()
    published_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["-published_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["school", "slug"], name="news_slug_unique"),
            models.CheckConstraint(condition=Q(category__in=NewsCategory.values), name="news_category_valid"),
            models.CheckConstraint(
                condition=~Q(status=PublicationStatus.PUBLISHED) | Q(published_at__isnull=False),
                name="news_published_has_date",
            ),
            _audience_constraint("news"),
            _status_constraint("news"),
        ]


class ResourceKind(models.TextChoices):
    SUPPLIES = "SUPPLIES", "Liste de fournitures"
    PROGRAMME = "PROGRAMME", "Programme / progression"
    PRACTICAL_INFO = "PRACTICAL_INFO", "Information pratique"
    CALENDAR = "CALENDAR", "Calendrier"
    INSTRUCTION = "INSTRUCTION", "Consigne"
    PROCEDURE = "PROCEDURE", "Procédure"
    MISSION = "MISSION", "Mission du poste"
    DOCUMENT = "DOCUMENT", "Document"


class RoleResource(Editorial):
    """What one role needs. Optional scope (all must match when set):
    level / class / school year (supplies, programmes for a parent's child or
    a teacher's classes), staff function (missions of a post). An empty scope
    means "every member of the audience"."""

    kind = models.CharField(max_length=30, choices=ResourceKind.choices)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    audiences = _audiences_field()
    level = models.ForeignKey("academics.Level", on_delete=models.PROTECT, blank=True, null=True, related_name="+")
    school_class = models.ForeignKey(
        "academics.SchoolClass", on_delete=models.PROTECT, blank=True, null=True, related_name="+"
    )
    academic_year = models.ForeignKey(
        "academics.AcademicYear", on_delete=models.PROTECT, blank=True, null=True, related_name="+"
    )
    staff_function = models.ForeignKey(
        "people.StaffFunction", on_delete=models.PROTECT, blank=True, null=True, related_name="+"
    )
    visible_from = models.DateField(blank=True, null=True)
    visible_until = models.DateField(blank=True, null=True)
    # Optional PDF (private storage, streamed after the same checks).
    document_path = models.CharField(max_length=300, blank=True)
    document_name = models.CharField(max_length=200, blank=True)
    document_size = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["kind", "order", "title"]
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=ResourceKind.values), name="role_resource_kind_valid"),
            _audience_constraint("role_resource", PORTAL_ROLES),
            _status_constraint("role_resource"),
            models.CheckConstraint(
                condition=Q(visible_from__isnull=True)
                | Q(visible_until__isnull=True)
                | Q(visible_until__gte=models.F("visible_from")),
                name="role_resource_window_ordered",
            ),
        ]


class MobileApp(models.TextChoices):
    PARENT = "PARENT", "Application Parent"
    TEACHER = "TEACHER", "Application Enseignant"
    STAFF = "STAFF", "Application Personnel"
    GUARDIAN = "GUARDIAN", "Application Gardien"


# The Android package of each application (mobile/apps/*/android/app/build.gradle.kts).
ANDROID_PACKAGES = {
    MobileApp.PARENT: "cm.schoolmanaging.school_parent",
    MobileApp.TEACHER: "cm.schoolmanaging.school_teacher",
    MobileApp.STAFF: "cm.schoolmanaging.school_staff",
    MobileApp.GUARDIAN: "cm.schoolmanaging.school_guardian",
}


class ReleaseStatus(models.TextChoices):
    DRAFT = "DRAFT", "Brouillon"
    PUBLISHED = "PUBLISHED", "Publiée"
    WITHDRAWN = "WITHDRAWN", "Retirée"


class MobileAppRelease(TenantModel):
    """One downloadable version of an application. Only a SIGNED RELEASE APK
    is accepted at upload (website.files.check_apk refuses unsigned and
    debug-signed builds); the role of the application is the role allowed to
    download it (the server checks it at each download)."""

    app = models.CharField(max_length=20, choices=MobileApp.choices)
    version_name = models.CharField(max_length=40)
    version_code = models.PositiveIntegerField()
    release_notes = models.TextField(blank=True)
    min_android = models.CharField(max_length=60, default="Android 10 (API 29) ou plus récent")
    storage_path = models.CharField(max_length=300)
    file_name = models.CharField(max_length=200)
    size = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    status = models.CharField(max_length=20, choices=ReleaseStatus.choices, default=ReleaseStatus.DRAFT)
    published_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["app", "-version_code"]
        constraints = [
            models.CheckConstraint(condition=Q(app__in=MobileApp.values), name="app_release_app_valid"),
            models.CheckConstraint(condition=Q(status__in=ReleaseStatus.values), name="app_release_status_valid"),
            models.UniqueConstraint(fields=["school", "app", "version_code"], name="app_release_version_unique"),
            models.CheckConstraint(
                condition=~Q(status=ReleaseStatus.PUBLISHED) | Q(published_at__isnull=False),
                name="app_release_published_has_date",
            ),
        ]
