"""Attendance & QR services (ADR 0011).

Security model of the gate scan
-------------------------------
- The QR image carries only the opaque token (43 random chars). It reveals
  nothing; knowing it only allows "this student arrived" to be recorded by a
  scanner of the SAME school.
- The token is looked up inside the scanner's school only: a token of another
  school is answered exactly like a non-existent one (UNKNOWN_TOKEN).
- Every scan, accepted or refused, is logged (GuardianScan, append-only).
- The scan answer exposes the minimum (name, class, arrival status).

Audit: QR issuance / revocation, attendance corrections, day finalisation,
policies and convocations write an AuditLog row (BUSINESS / ADMINISTRATIVE)
in the same transaction. Individual scans are their own immutable log.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max, Sum
from django.utils import timezone

from apps.academics.models import AcademicYear, AcademicYearStatus
from apps.audit.models import AuditLayer
from apps.audit.services import record_audit, snapshot
from apps.people.models import EnrollmentStatus, ParentStudent, StudentEnrollment, StudentStatus
from common.permissions import ADMIN_ROLES, membership_has_role, require_role

from .models import (
    AlertLevel,
    AttendancePolicy,
    AttendanceSource,
    Convocation,
    ConvocationStatus,
    DailyStatus,
    GuardianScan,
    QRStatus,
    ScanResult,
    StudentDailyAttendance,
    StudentQRCode,
)

SCANNER_ROLES = frozenset({"GUARDIAN", "STAFF", *ADMIN_ROLES})


def _school_tz(school):
    return ZoneInfo(school.timezone)


def current_year(school):
    year = AcademicYear.objects.filter(school=school, is_current=True).first()
    if year is None:
        raise ValidationError("The school has no current academic year.", code="no_current_year")
    return year


def _enrolled(student, year):
    return (
        StudentEnrollment.objects.filter(student=student, academic_year=year)
        .exclude(status=EnrollmentStatus.WITHDRAWN)
        .exists()
    )


# =============================================================================
# Policies
# =============================================================================

POLICY_FIELDS = [
    "day_of_week",
    "late_after_time",
    "morning_absence_cutoff",
    "day_absence_trigger",
    "absence_hours",
    "active",
]


@transaction.atomic
def set_policy(
    school,
    day_of_week,
    *,
    actor,
    late_after_time,
    morning_absence_cutoff,
    absence_hours=Decimal("8.00"),
    day_absence_trigger="NO_ARRIVAL",
    active=True,
):
    """Create or replace the rules of one weekday (1 = Monday ... 7 = Sunday)."""
    require_role(actor, ADMIN_ROLES, school=school)
    policy = AttendancePolicy.objects.select_for_update().filter(school=school, day_of_week=day_of_week).first()
    old = snapshot(policy, POLICY_FIELDS) if policy else {}
    if policy is None:
        policy = AttendancePolicy(school=school, day_of_week=day_of_week)
    policy.late_after_time = late_after_time
    policy.morning_absence_cutoff = morning_absence_cutoff
    policy.absence_hours = absence_hours
    policy.day_absence_trigger = day_absence_trigger
    policy.active = active
    policy.save()
    record_audit(
        "ATTENDANCE_POLICY_SET",
        actor=actor,
        entity=policy,
        old=old,
        new=snapshot(policy, POLICY_FIELDS),
        layer=AuditLayer.ADMINISTRATIVE,
    )
    return policy


def policy_for(school, day):
    return AttendancePolicy.objects.filter(school=school, day_of_week=day.isoweekday(), active=True).first()


# =============================================================================
# QR codes
# =============================================================================

QR_FIELDS = ["student", "academic_year", "version", "status", "revocation_reason"]


def _new_token():
    import secrets

    return secrets.token_urlsafe(32)  # 43 chars, 256 bits of randomness


def _issue(student, year, actor, version):
    qr = StudentQRCode.objects.create(
        school=student.school,
        student=student,
        academic_year=year,
        token=_new_token(),
        version=version,
        generated_by=actor,
    )
    record_audit("QR_ISSUED", actor=actor, entity=qr, new=snapshot(qr, QR_FIELDS))
    return qr


@transaction.atomic
def issue_qr_code(student, *, actor, academic_year=None):
    """Issue the student's QR code for the year (default: current year).
    Idempotent: returns the existing ACTIVE code if there is one."""
    require_role(actor, ADMIN_ROLES, school=student.school)
    year = academic_year or current_year(student.school)
    if year.school_id != student.school_id:
        raise PermissionDenied("This academic year belongs to another school.")
    if year.status in (AcademicYearStatus.CLOSED, AcademicYearStatus.ARCHIVED):
        raise ValidationError("No QR code can be issued for a closed year.", code="year_closed")
    if student.status != StudentStatus.ACTIVE or not _enrolled(student, year):
        raise ValidationError("The student is not actively enrolled this year.", code="student_not_enrolled")
    existing = StudentQRCode.objects.filter(student=student, academic_year=year, status=QRStatus.ACTIVE).first()
    if existing:
        return existing
    last = StudentQRCode.objects.filter(student=student, academic_year=year).aggregate(v=Max("version"))["v"] or 0
    return _issue(student, year, actor, last + 1)


@transaction.atomic
def revoke_qr_code(qr, *, actor, reason):
    require_role(actor, ADMIN_ROLES, school=qr.school)
    if not reason or not reason.strip():
        raise ValidationError("A reason is required to revoke a QR code.", code="reason_required")
    qr = StudentQRCode.objects.select_for_update().get(pk=qr.pk)
    if qr.status == QRStatus.REVOKED:
        raise ValidationError("This QR code is already revoked.", code="qr_already_revoked")
    old = snapshot(qr, QR_FIELDS)
    qr.status = QRStatus.REVOKED
    qr.revoked_at = timezone.now()
    qr.revoked_by = actor
    qr.revocation_reason = reason.strip()
    qr.save()
    record_audit("QR_REVOKED", actor=actor, entity=qr, old=old, new=snapshot(qr, QR_FIELDS))
    return qr


@transaction.atomic
def reissue_qr_code(student, *, actor, reason, academic_year=None):
    """Lost / stolen card: revoke the active code and issue version n+1."""
    year = academic_year or current_year(student.school)
    active = StudentQRCode.objects.filter(student=student, academic_year=year, status=QRStatus.ACTIVE).first()
    if active:
        revoke_qr_code(active, actor=actor, reason=reason)
    return issue_qr_code(student, actor=actor, academic_year=year)


@transaction.atomic
def issue_class_qr_codes(school_class, *, actor):
    """Issue the missing codes of every enrolled student of a class."""
    require_role(actor, ADMIN_ROLES, school=school_class.school)
    enrollments = (
        StudentEnrollment.objects.filter(school_class=school_class)
        .exclude(status=EnrollmentStatus.WITHDRAWN)
        .select_related("student")
    )
    return [
        issue_qr_code(e.student, actor=actor, academic_year=school_class.academic_year)
        for e in enrollments
        if e.student.status == StudentStatus.ACTIVE
    ]


# =============================================================================
# Scanning
# =============================================================================


@dataclass
class ScanOutcome:
    scan: GuardianScan
    attendance: StudentDailyAttendance | None


def _late_minutes(arrival_local, policy):
    if policy is None:
        return 0
    limit = datetime.combine(arrival_local.date(), policy.late_after_time, tzinfo=arrival_local.tzinfo)
    delta = arrival_local - limit
    return max(0, int(delta.total_seconds() // 60))


def _record_arrival(student, year, at, policy):
    """Upsert today's attendance for an accepted scan. Returns
    (record, newly_arrived)."""
    local = at.astimezone(_school_tz(student.school))
    day = local.date()
    late = _late_minutes(local, policy)
    status = DailyStatus.LATE if late > 0 else DailyStatus.PRESENT
    try:
        with transaction.atomic():
            record = StudentDailyAttendance.objects.select_for_update().filter(student=student, date=day).first()
            if record is None:
                record = StudentDailyAttendance.objects.create(
                    school=student.school,
                    student=student,
                    academic_year=year,
                    date=day,
                    status=status,
                    arrival_time=at,
                    late_minutes=late,
                    source=AttendanceSource.QR,
                )
                return record, True
    except IntegrityError:
        # Two scans of the same student at the same instant: the other one won.
        record = StudentDailyAttendance.objects.select_for_update().get(student=student, date=day)
    if record.status in (DailyStatus.PRESENT, DailyStatus.LATE, DailyStatus.EXCUSED):
        return record, False
    # PENDING, or ABSENT already finalised and the student finally arrives.
    record.status, record.arrival_time, record.late_minutes = status, at, late
    record.absence_hours = Decimal("0.00")
    record.source = AttendanceSource.QR
    record.save()
    return record, True


@transaction.atomic
def scan(token, *, actor, device=None, at=None):
    """Process one gate scan. Never raises for a bad token: the refusal is
    returned AND logged (so it is committed). Raises PermissionDenied only if
    the actor may not scan at all."""
    school = actor.school
    if not membership_has_role(actor, SCANNER_ROLES):
        raise PermissionDenied("Only guardians, staff and administrators can scan QR codes.")
    guardian = getattr(actor, "guardian_profile", None) if membership_has_role(actor, {"GUARDIAN"}) else None
    if guardian is not None and guardian.status != "ACTIVE":
        raise PermissionDenied("This guardian is not active.")
    at = at or timezone.now()
    token = (token or "").strip()
    meta = {"token_sha256_prefix": hashlib.sha256(token.encode()).hexdigest()[:12]}

    def log(result, qr=None, year=None):
        return GuardianScan.objects.create(
            school=school,
            scanned_by=actor,
            guardian=guardian,
            device=device,
            scanned_at=at,
            result=result,
            student=qr.student if qr else None,
            qr_code=qr,
            academic_year=year,
            metadata=meta,
        )

    # Scoped to the scanner's school: another school's token is "unknown".
    qr = StudentQRCode.objects.select_related("student", "academic_year").filter(school=school, token=token).first()
    if qr is None:
        return ScanOutcome(log(ScanResult.UNKNOWN_TOKEN), None)
    if qr.status == QRStatus.REVOKED:
        return ScanOutcome(log(ScanResult.REVOKED_TOKEN), None)
    year = qr.academic_year
    if not year.is_current:
        return ScanOutcome(log(ScanResult.EXPIRED_TOKEN), None)
    if qr.student.status != StudentStatus.ACTIVE or not _enrolled(qr.student, year):
        return ScanOutcome(log(ScanResult.STUDENT_NOT_ENROLLED), None)

    local_day = at.astimezone(_school_tz(school)).date()
    record, arrived = _record_arrival(qr.student, year, at, policy_for(school, local_day))
    result = ScanResult.ACCEPTED if arrived else ScanResult.ALREADY_PRESENT
    return ScanOutcome(log(result, qr=qr, year=year), record)


# =============================================================================
# Finalisation & corrections
# =============================================================================


@transaction.atomic
def finalize_day(school, day, *, actor):
    """Close a school day: enrolled students with no arrival become ABSENT
    (policy NO_ARRIVAL), and every record of the day is marked finalised.
    Idempotent. Not for future days, nor days outside the current year."""
    require_role(actor, ADMIN_ROLES, school=school)
    year = current_year(school)
    if not (year.start_date <= day <= year.end_date):
        raise ValidationError("This day is outside the current academic year.", code="day_outside_year")
    if day > timezone.localdate(timezone=_school_tz(school)):
        raise ValidationError("A future day cannot be finalised.", code="day_in_future")
    policy = policy_for(school, day)
    now = timezone.now()
    created = 0
    if policy is not None and policy.day_absence_trigger == "NO_ARRIVAL":
        enrolled = StudentEnrollment.objects.filter(
            academic_year=year, status=EnrollmentStatus.ACTIVE, student__status=StudentStatus.ACTIVE
        ).values_list("student_id", flat=True)
        recorded = set(
            StudentDailyAttendance.objects.filter(school=school, date=day).values_list("student_id", flat=True)
        )
        missing = [sid for sid in enrolled if sid not in recorded]
        StudentDailyAttendance.objects.bulk_create(
            StudentDailyAttendance(
                school=school,
                student_id=sid,
                academic_year=year,
                date=day,
                status=DailyStatus.ABSENT,
                absence_hours=policy.absence_hours,
                source=AttendanceSource.SYSTEM,
            )
            for sid in missing
        )
        created = len(missing)
        StudentDailyAttendance.objects.filter(school=school, date=day, status=DailyStatus.PENDING).update(
            status=DailyStatus.ABSENT, absence_hours=policy.absence_hours, source=AttendanceSource.SYSTEM
        )
    finalized = StudentDailyAttendance.objects.filter(school=school, date=day, finalized_at__isnull=True).update(
        finalized_at=now, finalized_by=actor
    )
    record_audit(
        "ATTENDANCE_DAY_FINALIZED",
        actor=actor,
        entity=year,
        school=school,
        new={
            "date": day,
            "absences_created": created,
            "records_finalized": finalized,
            "school_day": policy is not None,
        },
    )
    return {"date": day, "absences_created": created, "records_finalized": finalized, "school_day": policy is not None}


ATTENDANCE_FIELDS = ["status", "arrival_time", "late_minutes", "absence_hours", "source", "note"]


@transaction.atomic
def correct_attendance(record, *, actor, status, reason, arrival_time=None):
    """Administrative correction (e.g. justify an absence -> EXCUSED). Reason
    mandatory, audited with before/after values."""
    require_role(actor, ADMIN_ROLES, school=record.school)
    if not reason or not reason.strip():
        raise ValidationError("A reason is required to correct attendance.", code="reason_required")
    if status not in DailyStatus.values or status == DailyStatus.PENDING:
        raise ValidationError("Invalid target status.", code="invalid_status")
    record = StudentDailyAttendance.objects.select_for_update().get(pk=record.pk)
    old = snapshot(record, ATTENDANCE_FIELDS)
    policy = policy_for(record.school, record.date)
    full_day = policy.absence_hours if policy else Decimal("8.00")
    if status in (DailyStatus.PRESENT, DailyStatus.LATE):
        arrival = arrival_time or record.arrival_time
        if arrival is None:
            raise ValidationError("An arrival time is required.", code="arrival_required")
        late = _late_minutes(arrival.astimezone(_school_tz(record.school)), policy)
        record.status = DailyStatus.LATE if late > 0 else DailyStatus.PRESENT
        record.arrival_time, record.late_minutes, record.absence_hours = arrival, late, Decimal("0.00")
    else:  # ABSENT / EXCUSED
        hours = record.absence_hours if record.absence_hours > 0 else full_day
        record.status, record.arrival_time, record.late_minutes, record.absence_hours = status, None, 0, hours
    record.source = AttendanceSource.MANUAL
    record.note = reason.strip()
    record.save()
    record_audit("ATTENDANCE_CORRECTED", actor=actor, entity=record, old=old, new=snapshot(record, ATTENDANCE_FIELDS))
    return record


# =============================================================================
# Graduated alerts
# =============================================================================


def absence_summary(student, year):
    """Unexcused absence hours of the year and the alert level, using
    SchoolConfiguration thresholds (yellow / orange / red hours). EXCUSED
    absences are counted separately and never raise the level."""
    config = student.school.configuration
    rows = StudentDailyAttendance.objects.filter(student=student, academic_year=year)
    unexcused = rows.filter(status=DailyStatus.ABSENT).aggregate(h=Sum("absence_hours"))["h"] or Decimal("0.00")
    excused = rows.filter(status=DailyStatus.EXCUSED).aggregate(h=Sum("absence_hours"))["h"] or Decimal("0.00")
    if unexcused >= config.notification_red_hours:
        level = AlertLevel.RED
    elif unexcused >= config.notification_orange_hours:
        level = AlertLevel.ORANGE
    elif unexcused >= config.notification_yellow_hours:
        level = AlertLevel.YELLOW
    else:
        level = AlertLevel.NONE
    return {
        "unexcused_absence_hours": unexcused,
        "excused_absence_hours": excused,
        "late_count": rows.filter(status=DailyStatus.LATE).count(),
        "alert_level": level,
        # Parents are to be notified from this threshold (delivery: communication phase).
        "parent_notification_due": unexcused >= config.notification_absence_threshold_hours,
        "thresholds": {
            "yellow": config.notification_yellow_hours,
            "orange": config.notification_orange_hours,
            "red": config.notification_red_hours,
        },
    }


# =============================================================================
# Convocations
# =============================================================================

CONVOCATION_FIELDS = [
    "student",
    "parent",
    "scheduled_start",
    "scheduled_end",
    "reason",
    "alert_level",
    "status",
    "notes",
]


@transaction.atomic
def create_convocation(student, parent, *, actor, scheduled_start, scheduled_end, reason):
    """Convene a parent (administrators only). The parent must have an ACTIVE
    and VERIFIED link with the student. The current alert level is recorded."""
    require_role(actor, ADMIN_ROLES, school=student.school)
    if not reason or not reason.strip():
        raise ValidationError("A reason is required.", code="reason_required")
    if not ParentStudent.objects.filter(parent=parent, student=student, active=True, identity_verified=True).exists():
        raise ValidationError("This parent has no verified link with the student.", code="parent_not_linked")
    if scheduled_end <= scheduled_start:
        raise ValidationError("The meeting must end after it starts.", code="invalid_schedule")
    level = absence_summary(student, current_year(student.school))["alert_level"]
    convocation = Convocation.objects.create(
        school=student.school,
        student=student,
        parent=parent,
        created_by=actor,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        reason=reason.strip(),
        alert_level=level,
    )
    record_audit("CONVOCATION_CREATED", actor=actor, entity=convocation, new=snapshot(convocation, CONVOCATION_FIELDS))
    return convocation


@transaction.atomic
def set_convocation_status(convocation, status, *, actor, notes=None):
    require_role(actor, ADMIN_ROLES, school=convocation.school)
    if status not in ConvocationStatus.values or status == ConvocationStatus.SCHEDULED:
        raise ValidationError("Invalid target status.", code="invalid_status")
    convocation = Convocation.objects.select_for_update().get(pk=convocation.pk)
    if convocation.status != ConvocationStatus.SCHEDULED:
        raise ValidationError("This convocation is already closed.", code="convocation_closed")
    old = snapshot(convocation, CONVOCATION_FIELDS)
    convocation.status, convocation.notes = status, notes
    convocation.save()
    record_audit(
        "CONVOCATION_UPDATED", actor=actor, entity=convocation, old=old, new=snapshot(convocation, CONVOCATION_FIELDS)
    )
    return convocation


def day_window(school, day):
    """[start, end) of a local school day, as aware datetimes."""
    tz = _school_tz(school)
    start = datetime.combine(day, time.min, tzinfo=tz)
    return start, start + timedelta(days=1)
