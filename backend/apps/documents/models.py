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
