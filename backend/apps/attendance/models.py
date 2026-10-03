"""Student attendance and annual QR codes (spec §4.5, ADR 0011).

    AttendancePolicy      lateness / absence rules per day of the week
    StudentQRCode         ONE active opaque token per student and school year
      └── GuardianScan    immutable log of EVERY scan (accepted or refused)
    StudentDailyAttendance  PRESENT / LATE / ABSENT / EXCUSED per student and day
    Convocation           parent meeting (graduated alerts, admin decision)

Session call-sheets (StudentSessionAttendance) and teacher attendance depend
on TeachingSession → ScheduleSlot (scheduling phase): not built here.
"""

from decimal import Decimal

from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from common.models import TenantModel

# =============================================================================
# Policy
# =============================================================================


class DayAbsenceTrigger(models.TextChoices):
    # No accepted scan and no manual record at finalisation -> ABSENT.
    NO_ARRIVAL = "NO_ARRIVAL", "Absence si aucune arrivée"
    # Absences are only recorded manually that day.
    MANUAL = "MANUAL", "Saisie manuelle uniquement"


class AttendancePolicy(TenantModel):
    """Attendance rules of one school day (ISO weekday: 1 = Monday).

    A weekday without an ACTIVE policy is not a school day: nothing is
    finalised as absent that day.

    Deviation (ADR 0011): the spec declares `school` as OneToOne AND
    UNIQUE(school, day_of_week); a OneToOne would allow a single day, so
    `school` is a ForeignKey. `absence_hours` (hours counted for a full-day
    absence) is an addition: without timetables (scheduling phase) the
    daily absence weight must be configured.
    """

    day_of_week = models.PositiveSmallIntegerField()
    late_after_time = models.TimeField()
    morning_absence_cutoff = models.TimeField()
    day_absence_trigger = models.CharField(
        max_length=30, choices=DayAbsenceTrigger.choices, default=DayAbsenceTrigger.NO_ARRIVAL
    )
    absence_hours = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("8.00"))
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["day_of_week"]
        verbose_name_plural = "attendance policies"
        constraints = [
            models.UniqueConstraint(fields=["school", "day_of_week"], name="attendance_policy_school_day_unique"),
            models.CheckConstraint(
                condition=Q(day_of_week__gte=1, day_of_week__lte=7), name="attendance_policy_day_valid"
            ),
            models.CheckConstraint(
                condition=Q(late_after_time__lte=F("morning_absence_cutoff")), name="attendance_policy_times_ordered"
            ),
            models.CheckConstraint(
                condition=Q(absence_hours__gt=0, absence_hours__lte=24), name="attendance_policy_hours_valid"
            ),
            models.CheckConstraint(
                condition=Q(day_absence_trigger__in=DayAbsenceTrigger.values), name="attendance_policy_trigger_valid"
            ),
        ]

    def __str__(self):
        return f"Politique jour {self.day_of_week}"


# =============================================================================
# QR codes
# =============================================================================


class QRStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Actif"
    REVOKED = "REVOKED", "Révoqué"


# 32 random bytes, URL-safe base64 without padding = exactly 43 characters of
# [A-Za-z0-9_-]. The CHECK below makes the spec's "token does not contain
# PII" a database guarantee: a token can only be such a random string, never
# a name, a matricule or a UUID-with-dashes-and-meaning.
QR_TOKEN_REGEX = r"^[A-Za-z0-9_-]{43}$"  # noqa: S105 - a format, not a secret


class StudentQRCode(TenantModel):
    """The student's permanent QR identity for ONE academic year.

    - persistent for the year (printed on the student card), NOT regenerated
      at each login;
    - opaque and unpredictable (secrets.token_urlsafe(32), 256 bits);
    - exactly one ACTIVE code per student and year (partial unique index);
      a lost card is handled by revoking and issuing version n+1: revoked
      codes stay in the table, so old scans keep their history and a revoked
      token can never come back (UNIQUE on token).

    Deviation (ADR 0011): the spec's UNIQUE(student, academic_year) becomes
    UNIQUE(student, academic_year) WHERE status = ACTIVE, plus
    UNIQUE(student, academic_year, version), to keep revoked versions.
    """

    student = models.ForeignKey("people.Student", on_delete=models.PROTECT, related_name="qr_codes")
    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT, related_name="qr_codes")
    token = models.CharField(max_length=128, unique=True)
    version = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=QRStatus.choices, default=QRStatus.ACTIVE, db_index=True)
    issued_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(blank=True, null=True)
    generated_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )
    revoked_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )
    revocation_reason = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["-issued_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "academic_year"], condition=Q(status=QRStatus.ACTIVE), name="qr_one_active_per_year"
            ),
            models.UniqueConstraint(fields=["student", "academic_year", "version"], name="qr_version_unique"),
            models.CheckConstraint(condition=Q(token__regex=QR_TOKEN_REGEX), name="qr_token_opaque_format"),
            models.CheckConstraint(condition=Q(version__gte=1), name="qr_version_positive"),
            models.CheckConstraint(condition=Q(status__in=QRStatus.values), name="qr_status_valid"),
            models.CheckConstraint(
                condition=(Q(status=QRStatus.ACTIVE) & Q(revoked_at__isnull=True))
                | (Q(status=QRStatus.REVOKED) & Q(revoked_at__isnull=False)),
                name="qr_revocation_consistent",
            ),
        ]

    def __str__(self):
        return f"QR v{self.version} {self.student} ({self.academic_year})"


# =============================================================================
# Scans
# =============================================================================


class ScanResult(models.TextChoices):
    ACCEPTED = "ACCEPTED", "Accepté (arrivée enregistrée)"
    ALREADY_PRESENT = "ALREADY_PRESENT", "Accepté (déjà présent)"
    UNKNOWN_TOKEN = "UNKNOWN_TOKEN", "QR inconnu"
    REVOKED_TOKEN = "REVOKED_TOKEN", "QR révoqué"
    EXPIRED_TOKEN = "EXPIRED_TOKEN", "QR d'une autre année scolaire"
    STUDENT_NOT_ENROLLED = "STUDENT_NOT_ENROLLED", "Élève non inscrit / inactif"


ACCEPTED_RESULTS = [ScanResult.ACCEPTED, ScanResult.ALREADY_PRESENT]


class GuardianScan(TenantModel):
    """Immutable log of one QR scan at the school gate (spec §4.5).

    Every scan is kept, refused ones included (attempts with unknown or
    revoked tokens are what an administrator needs to see). A trigger refuses
    UPDATE and DELETE.

    Deviation (ADR 0011): the spec has `guardian` NOT NULL, but its permission
    matrix lets STAFF and administrators scan too. The scanner is therefore
    `scanned_by` (membership, NOT NULL); `guardian` is set when the scanner is
    a guardian.

    Database guarantees: an accepted scan has a student, a QR code and a year;
    the QR code belongs to that student and that year (composite FKs); all
    rows belong to the scan's school.
    """

    scanned_by = models.ForeignKey("accounts.SchoolMembership", on_delete=models.PROTECT, related_name="+")
    guardian = models.ForeignKey(
        "people.GuardianProfile", on_delete=models.PROTECT, blank=True, null=True, related_name="scans"
    )
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT, blank=True, null=True, related_name="scans")
    qr_code = models.ForeignKey(StudentQRCode, on_delete=models.PROTECT, blank=True, null=True, related_name="scans")
    academic_year = models.ForeignKey(
        "academics.AcademicYear", on_delete=models.PROTECT, blank=True, null=True, related_name="+"
    )
    device = models.ForeignKey(
        "accounts.UserDevice", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )
    scanned_at = models.DateTimeField(default=timezone.now, db_index=True)
    result = models.CharField(max_length=30, choices=ScanResult.choices, db_index=True)
    # Never the raw presented token: only a short hash prefix (investigations).
    metadata = models.JSONField(default=dict)

    class Meta:
        ordering = ["-scanned_at"]
        constraints = [
            models.CheckConstraint(condition=Q(result__in=ScanResult.values), name="scan_result_valid"),
            models.CheckConstraint(
                condition=~Q(result__in=ACCEPTED_RESULTS)
                | (Q(student__isnull=False) & Q(qr_code__isnull=False) & Q(academic_year__isnull=False)),
                name="scan_accepted_is_complete",
            ),
        ]

    def __str__(self):
        return f"Scan {self.result} {self.scanned_at:%Y-%m-%d %H:%M}"


# =============================================================================
# Daily attendance
# =============================================================================


class DailyStatus(models.TextChoices):
    PENDING = "PENDING", "En attente"
    PRESENT = "PRESENT", "Présent"
    LATE = "LATE", "En retard"
    ABSENT = "ABSENT", "Absent"
    EXCUSED = "EXCUSED", "Absence justifiée"


class AttendanceSource(models.TextChoices):
    SYSTEM = "SYSTEM", "Système (clôture)"
    QR = "QR", "Scan QR"
    MANUAL = "MANUAL", "Saisie administrative"


class StudentDailyAttendance(TenantModel):
    """Daily attendance of a student: the basis of yearly absence totals and
    of graduated parent alerts (SchoolConfiguration yellow / orange / red).

    `academic_year` is an addition (ADR 0011): attendance is isolated per
    school AND per year (composite FKs); the date lying inside the year and the
    student being enrolled are checked by the services.

    Rules enforced by PostgreSQL:
    - one row per student and date;
    - PRESENT / LATE have an arrival time; ABSENT / EXCUSED do not;
    - LATE has late_minutes > 0, other statuses have 0;
    - only ABSENT / EXCUSED carry absence hours.
    """

    student = models.ForeignKey("people.Student", on_delete=models.PROTECT, related_name="daily_attendance")
    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT, related_name="+")
    date = models.DateField(db_index=True)
    status = models.CharField(max_length=20, choices=DailyStatus.choices, default=DailyStatus.PENDING, db_index=True)
    arrival_time = models.DateTimeField(blank=True, null=True)
    late_minutes = models.PositiveIntegerField(default=0)
    absence_hours = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0.00"))
    source = models.CharField(max_length=20, choices=AttendanceSource.choices, default=AttendanceSource.SYSTEM)
    finalized_at = models.DateTimeField(blank=True, null=True)
    finalized_by = models.ForeignKey(
        "accounts.SchoolMembership", on_delete=models.SET_NULL, blank=True, null=True, related_name="+"
    )
    note = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(fields=["student", "date"], name="daily_attendance_student_date_unique"),
            models.CheckConstraint(condition=Q(status__in=DailyStatus.values), name="daily_attendance_status_valid"),
            models.CheckConstraint(
                condition=Q(source__in=AttendanceSource.values), name="daily_attendance_source_valid"
            ),
            models.CheckConstraint(
                condition=~Q(status__in=[DailyStatus.PRESENT, DailyStatus.LATE]) | Q(arrival_time__isnull=False),
                name="daily_attendance_arrival_when_present",
            ),
            models.CheckConstraint(
                condition=~Q(status__in=[DailyStatus.ABSENT, DailyStatus.EXCUSED]) | Q(arrival_time__isnull=True),
                name="daily_attendance_no_arrival_when_absent",
            ),
            models.CheckConstraint(
                condition=(Q(status=DailyStatus.LATE) & Q(late_minutes__gt=0))
                | (~Q(status=DailyStatus.LATE) & Q(late_minutes=0)),
                name="daily_attendance_late_minutes_consistent",
            ),
            models.CheckConstraint(
                condition=Q(absence_hours__gte=0)
                & (Q(status__in=[DailyStatus.ABSENT, DailyStatus.EXCUSED]) | Q(absence_hours=0)),
                name="daily_attendance_hours_only_when_absent",
            ),
        ]

    def __str__(self):
        return f"{self.student} {self.date}: {self.status}"


# =============================================================================
# Convocations
# =============================================================================


class ConvocationStatus(models.TextChoices):
    SCHEDULED = "SCHEDULED", "Programmée"
    HELD = "HELD", "Tenue"
    MISSED = "MISSED", "Parent absent"
    CANCELLED = "CANCELLED", "Annulée"


class AlertLevel(models.TextChoices):
    NONE = "NONE", "Aucune"
    YELLOW = "YELLOW", "Jaune"
    ORANGE = "ORANGE", "Orange"
    RED = "RED", "Rouge"


class Convocation(TenantModel):
    """Meeting with a parent, created by an administrator — typically when a
    student reaches the RED absence level (spec §15: "red alerts can create
    scheduled convocations"; the decision stays human).

    `alert_level` (addition, ADR 0011) records the level that motivated it
    (NONE = purely administrative convocation).
    """

    student = models.ForeignKey("people.Student", on_delete=models.PROTECT, related_name="convocations")
    parent = models.ForeignKey("people.ParentProfile", on_delete=models.PROTECT, related_name="convocations")
    created_by = models.ForeignKey("accounts.SchoolMembership", on_delete=models.PROTECT, related_name="+")
    scheduled_start = models.DateTimeField()
    scheduled_end = models.DateTimeField()
    reason = models.TextField()
    alert_level = models.CharField(max_length=10, choices=AlertLevel.choices, default=AlertLevel.NONE)
    status = models.CharField(
        max_length=20, choices=ConvocationStatus.choices, default=ConvocationStatus.SCHEDULED, db_index=True
    )
    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["-scheduled_start"]
        constraints = [
            models.CheckConstraint(
                condition=Q(scheduled_end__gt=F("scheduled_start")), name="convocation_times_ordered"
            ),
            models.CheckConstraint(condition=~Q(reason=""), name="convocation_reason_required"),
            models.CheckConstraint(condition=Q(status__in=ConvocationStatus.values), name="convocation_status_valid"),
            models.CheckConstraint(condition=Q(alert_level__in=AlertLevel.values), name="convocation_level_valid"),
        ]

    def __str__(self):
        return f"Convocation {self.student} {self.scheduled_start:%Y-%m-%d}"
