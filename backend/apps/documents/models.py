"""Official documents (spec §6.12, ADR 0016).

    Document            one generated PDF of ONE source, with the snapshot of the data
                        it shows, its fingerprint, version and status
    DocumentDownload    who downloaded which document, when (append-only)

A document never owns business data: it renders what the source domain
already decided (gradebook ReportCard, finance Payment, payroll
Teacher/StaffPayroll, attendance StudentDailyAttendance) and keeps a frozen
copy of exactly what it printed (`content`).

    OFFICIAL      the source is final (validated report card, received payment,
                  paid payroll, finalised attendance): generated once, never
                  regenerated, never changed
    PROVISIONAL   the source can still change: watermarked "PROVISOIRE";
                  regenerating after a source change writes a new version and
                  marks the previous one SUPERSEDED
    SUPERSEDED    kept for history, no longer the current document

Files live in the private storage (no public route) under random names and
are streamed only after a permission check. Rows are never deleted.
"""

from django.db import models
from django.db.models import Q

from common.models import TenantModel


class DocumentKind(models.TextChoices):
    REPORT_CARD = "REPORT_CARD", "Bulletin scolaire"
    PAYMENT_RECEIPT = "PAYMENT_RECEIPT", "Reçu de paiement"
    PAYSLIP = "PAYSLIP", "Bulletin de paie"
    STUDENT_ATTENDANCE = "STUDENT_ATTENDANCE", "Relevé de présence d'un élève"
    CLASS_ATTENDANCE = "CLASS_ATTENDANCE", "Registre de présence d'une classe"
    STUDENT_CARD = "STUDENT_CARD", "Carte d'élève"
    TIMETABLE = "TIMETABLE", "Emploi du temps"


class DocumentStatus(models.TextChoices):
    OFFICIAL = "OFFICIAL", "Officiel"
    PROVISIONAL = "PROVISIONAL", "Provisoire"
    SUPERSEDED = "SUPERSEDED", "Remplacé"


# Which source column each kind uses (exactly these, nothing else).
KIND_SOURCES = {
    DocumentKind.REPORT_CARD: ("report_card",),
    DocumentKind.PAYMENT_RECEIPT: ("payment",),
    DocumentKind.PAYSLIP: ("teacher_payroll", "staff_payroll"),
    DocumentKind.STUDENT_ATTENDANCE: ("student",),
    DocumentKind.CLASS_ATTENDANCE: ("school_class",),
    DocumentKind.STUDENT_CARD: ("student",),
    DocumentKind.TIMETABLE: ("school_class", "teacher"),  # a class's, or a teacher's own
}
SOURCE_FIELDS = ("report_card", "payment", "teacher_payroll", "staff_payroll", "student", "school_class", "teacher")


def _kind_check(kind, allowed):
    """`kind` uses one of `allowed` source columns and leaves the others NULL."""
    options = Q()
    for chosen in allowed:
        cond = Q(**{f"{chosen}__isnull": False})
        for other in SOURCE_FIELDS:
            if other != chosen:
                cond &= Q(**{f"{other}__isnull": True})
        options |= cond
    return ~Q(kind=kind) | options


class Document(TenantModel):
    kind = models.CharField(max_length=30, choices=DocumentKind.choices, db_index=True)
    status = models.CharField(max_length=20, choices=DocumentStatus.choices, db_index=True)
    title = models.CharField(max_length=200)
    # --- source (exactly one, by kind) ---
    report_card = models.ForeignKey(
        "gradebook.ReportCard", on_delete=models.PROTECT, blank=True, null=True, related_name="documents"
    )
    payment = models.ForeignKey(
        "finance.Payment", on_delete=models.PROTECT, blank=True, null=True, related_name="documents"
    )
    teacher_payroll = models.ForeignKey(
        "payroll.TeacherPayroll", on_delete=models.PROTECT, blank=True, null=True, related_name="documents"
    )
    staff_payroll = models.ForeignKey(
        "payroll.StaffPayroll", on_delete=models.PROTECT, blank=True, null=True, related_name="documents"
    )
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT, blank=True, null=True, related_name="+")
    school_class = models.ForeignKey(
        "academics.SchoolClass", on_delete=models.PROTECT, blank=True, null=True, related_name="+"
    )
    teacher = models.ForeignKey(
        "people.TeacherProfile", on_delete=models.PROTECT, blank=True, null=True, related_name="+"
    )
    # Extra parameters of the source (date range of an attendance statement...).
    params = models.JSONField(default=dict)
    params_key = models.CharField(max_length=120, default="")
    # --- what was printed ---
    content = models.JSONField()  # frozen snapshot of the rendered data
    fingerprint = models.CharField(max_length=64)  # sha256 of `content`
    version = models.PositiveIntegerField(default=1)
    verification_code = models.CharField(max_length=32, unique=True)
    # --- file (private storage) ---
    storage_path = models.TextField()
    file_name = models.CharField(max_length=200)
    size_bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)
    generated_by = models.ForeignKey("accounts.SchoolMembership", on_delete=models.PROTECT, related_name="+")
    generated_at = models.DateTimeField()

    class Meta:
        ordering = ["-generated_at"]
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=DocumentKind.values), name="document_kind_valid"),
            models.CheckConstraint(condition=Q(status__in=DocumentStatus.values), name="document_status_valid"),
            models.CheckConstraint(condition=Q(size_bytes__gt=0), name="document_size_positive"),
            models.UniqueConstraint(fields=["storage_path"], name="document_path_unique"),
            *[
                models.CheckConstraint(condition=_kind_check(kind, allowed), name=f"document_{kind.lower()}_source")
                for kind, allowed in KIND_SOURCES.items()
            ],
            # One CURRENT document per source and parameters (+ one official).
            models.UniqueConstraint(
                fields=["kind", *SOURCE_FIELDS, "params_key"],
                condition=~Q(status=DocumentStatus.SUPERSEDED),
                name="document_one_current",
                nulls_distinct=False,
            ),
            models.UniqueConstraint(
                fields=["kind", *SOURCE_FIELDS, "params_key", "version"],
                name="document_version_unique",
                nulls_distinct=False,
            ),
        ]


class DocumentDownload(TenantModel):
    """Access trace of a document (append-only)."""

    document = models.ForeignKey(Document, on_delete=models.PROTECT, related_name="downloads")
    actor = models.ForeignKey("accounts.SchoolMembership", on_delete=models.PROTECT, related_name="+")
    downloaded_at = models.DateTimeField()

    class Meta:
        ordering = ["-downloaded_at"]


# =============================================================================
# School plans (2D maps of the premises, drawn elsewhere, imported here)
# =============================================================================
#
# NOT the Document registry above (documents GENERATED from business data):
# a plan is a file an architect produced; the school imports it, publishes a
# version and chooses who may see it. Files live in the private storage and
# are only streamed after a permission check (plans.py, plans_api.py).


class PlanStatus(models.TextChoices):
    DRAFT = "DRAFT", "Brouillon"
    PUBLISHED = "PUBLISHED", "Publié"
    WITHDRAWN = "WITHDRAWN", "Retiré"


class PlanDistribution(models.TextChoices):
    AUTO = "AUTO", "Automatique (parents vérifiés et enseignants de l'école)"
    MANUAL = "MANUAL", "Manuelle (publics choisis)"


class PlanVersionStatus(models.TextChoices):
    DRAFT = "DRAFT", "Importée, jamais publiée"
    PUBLISHED = "PUBLISHED", "Publiée (version courante)"
    SUPERSEDED = "SUPERSEDED", "Remplacée"


class SchoolPlan(TenantModel):
    """One plan of the school (a building, a floor, the whole site...).
    Building and floor are optional: a small school has a single plan."""

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    building = models.CharField(max_length=100, blank=True, default="")
    floor = models.CharField(max_length=60, blank=True, default="")
    display_order = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=PlanStatus.choices, default=PlanStatus.DRAFT, db_index=True)
    distribution = models.CharField(max_length=10, choices=PlanDistribution.choices, default=PlanDistribution.AUTO)
    current_version = models.ForeignKey(
        "SchoolPlanVersion", on_delete=models.PROTECT, blank=True, null=True, related_name="+"
    )
    created_by = models.ForeignKey("accounts.SchoolMembership", on_delete=models.PROTECT, related_name="+")
    published_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.PROTECT, blank=True, null=True, related_name="+"
    )
    published_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["display_order", "building", "floor", "title"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=PlanStatus.values), name="plan_status_valid"),
            models.CheckConstraint(
                condition=Q(distribution__in=PlanDistribution.values), name="plan_distribution_valid"
            ),
            # Published = a current version and a publication date (never a published empty plan).
            models.CheckConstraint(
                condition=~Q(status=PlanStatus.PUBLISHED)
                | Q(current_version__isnull=False, published_at__isnull=False),
                name="plan_published_has_version",
            ),
        ]

    def __str__(self):
        return self.title


class SchoolPlanVersion(TenantModel):
    """One imported file of a plan. Never edited nor deleted: a new file is a
    new version; publishing it supersedes the previous published one."""

    plan = models.ForeignKey(SchoolPlan, on_delete=models.PROTECT, related_name="versions")
    number = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20, choices=PlanVersionStatus.choices, default=PlanVersionStatus.DRAFT, db_index=True
    )
    original_name = models.CharField(max_length=255)  # metadata only (never a path)
    stored_name = models.CharField(max_length=80)  # random
    storage_path = models.TextField()  # private storage, never sent to clients
    mime_type = models.CharField(max_length=50)
    size_bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)
    width = models.PositiveIntegerField(blank=True, null=True)  # images
    height = models.PositiveIntegerField(blank=True, null=True)
    page_count = models.PositiveIntegerField(blank=True, null=True)  # PDF
    uploaded_by = models.ForeignKey("accounts.SchoolMembership", on_delete=models.PROTECT, related_name="+")
    published_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["plan", "-number"]
        constraints = [
            models.UniqueConstraint(fields=["plan", "number"], name="plan_version_number_unique"),
            models.UniqueConstraint(fields=["storage_path"], name="plan_version_path_unique"),
            models.UniqueConstraint(
                fields=["plan"],
                condition=Q(status=PlanVersionStatus.PUBLISHED),
                name="plan_one_published_version",
            ),
            models.CheckConstraint(condition=Q(status__in=PlanVersionStatus.values), name="plan_version_status_valid"),
            models.CheckConstraint(
                condition=Q(mime_type__in=["application/pdf", "image/png", "image/jpeg"]),
                name="plan_version_mime_allowed",
            ),
            models.CheckConstraint(condition=Q(size_bytes__gt=0), name="plan_version_size_positive"),
            models.CheckConstraint(condition=Q(number__gte=1), name="plan_version_number_positive"),
        ]

    def __str__(self):
        return f"{self.plan} — v{self.number}"


class PlanAudienceTarget(models.TextChoices):
    SCHOOL_PARENTS = "SCHOOL_PARENTS", "Tous les parents vérifiés de l'école"
    SCHOOL_TEACHERS = "SCHOOL_TEACHERS", "Tous les enseignants actifs de l'école"
    CLASS_PARENTS = "CLASS_PARENTS", "Parents vérifiés des élèves d'une classe"
    CLASS_TEACHERS = "CLASS_TEACHERS", "Enseignants d'une classe"


CLASS_TARGETS = (PlanAudienceTarget.CLASS_PARENTS, PlanAudienceTarget.CLASS_TEACHERS)


class SchoolPlanAudience(TenantModel):
    """MANUAL distribution: who may see the plan, as relations the school
    already has (classes, roles) — never a free list of people or e-mails.
    Resolved at each read by plans.can_view."""

    plan = models.ForeignKey(SchoolPlan, on_delete=models.CASCADE, related_name="audience")
    target = models.CharField(max_length=30, choices=PlanAudienceTarget.choices)
    school_class = models.ForeignKey(
        "academics.SchoolClass", on_delete=models.PROTECT, blank=True, null=True, related_name="+"
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(target__in=PlanAudienceTarget.values), name="plan_audience_target_valid"
            ),
            models.CheckConstraint(
                condition=(Q(target__in=CLASS_TARGETS) & Q(school_class__isnull=False))
                | (~Q(target__in=CLASS_TARGETS) & Q(school_class__isnull=True)),
                name="plan_audience_class_when_needed",
            ),
            models.UniqueConstraint(
                fields=["plan", "target", "school_class"], name="plan_audience_unique", nulls_distinct=False
            ),
        ]
