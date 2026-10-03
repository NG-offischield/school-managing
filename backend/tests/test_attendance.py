"""Attendance & QR: PostgreSQL guarantees and services (ADR 0011)."""

import re
from datetime import date, time, timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

from apps.academics.models import AcademicYear
from apps.attendance import services as att
from apps.attendance.models import (
    AttendancePolicy,
    DailyStatus,
    GuardianScan,
    QRStatus,
    ScanResult,
    StudentDailyAttendance,
    StudentQRCode,
)
from apps.audit.models import AuditLog
from apps.people import services as people
from apps.people.models import EnrollmentStatus, StudentEnrollment, VerificationMethod

from .attendance_world import MONDAY, at, make_attendance_world
from .conftest import DB
from .factories import ParentFactory, SchoolClassFactory, SchoolFactory, StudentFactory, admin_of, member_with_role

pytestmark = DB


@pytest.fixture
def w(school):
    return make_attendance_world(school)


def rejected():
    return pytest.raises(IntegrityError)


# =============================================================================
# QR codes
# =============================================================================


def test_token_is_opaque_random_and_unpredictable(w):
    tokens = [qr.token for qr in w.qr.values()]
    for qr, student in zip(w.qr.values(), w.students, strict=True):
        assert re.fullmatch(r"[A-Za-z0-9_-]{43}", qr.token)
        for leak in (student.student_number, student.last_name, str(student.pk)):
            assert leak not in qr.token
    assert len(set(tokens)) == len(tokens)


def test_token_format_is_a_database_guarantee(w):
    qr = next(iter(w.qr.values()))
    for bad in ("MAT00012-Awa-Elève", str(qr.student_id), "x" * 42):
        with rejected(), transaction.atomic():
            StudentQRCode.objects.filter(pk=qr.pk).update(token=bad)


def test_issue_is_idempotent_and_audited(w):
    s = w.students[0]
    assert att.issue_qr_code(s, actor=w.admin) == w.qr[s.pk]
    assert AuditLog.objects.filter(action="QR_ISSUED", entity_id=w.qr[s.pk].pk).count() == 1


def test_one_active_code_per_student_and_year_postgresql(w):
    s = w.students[0]
    with rejected(), transaction.atomic():
        StudentQRCode.objects.create(school=w.school, student=s, academic_year=w.year, token="A" * 43, version=2)


def test_reissue_revokes_and_keeps_history(w):
    s = w.students[0]
    old = w.qr[s.pk]
    new = att.reissue_qr_code(s, actor=w.admin, reason="Carte perdue")
    old.refresh_from_db()
    assert (old.status, old.revocation_reason, new.version, new.status) == (
        QRStatus.REVOKED,
        "Carte perdue",
        2,
        QRStatus.ACTIVE,
    )
    assert new.token != old.token
    assert att.scan(old.token, actor=w.guardian_member, at=at(7)).scan.result == ScanResult.REVOKED_TOKEN
    assert AuditLog.objects.filter(action="QR_REVOKED", entity_id=old.pk).exists()


def test_revocation_consistency_postgresql(w):
    qr = next(iter(w.qr.values()))
    with rejected(), transaction.atomic():
        StudentQRCode.objects.filter(pk=qr.pk).update(status=QRStatus.REVOKED)  # no revoked_at


def test_issue_rules(w):
    with pytest.raises(PermissionDenied):
        att.issue_qr_code(w.students[0], actor=w.tm_member)
    with pytest.raises(PermissionDenied):
        att.issue_qr_code(w.students[0], actor=admin_of(SchoolFactory()))
    with pytest.raises(ValidationError) as exc:
        att.issue_qr_code(StudentFactory(school=w.school), actor=w.admin)  # not enrolled
    assert exc.value.code == "student_not_enrolled"
    with pytest.raises(ValidationError):
        att.revoke_qr_code(w.qr[w.students[0].pk], actor=w.admin, reason=" ")


def test_issue_class_codes(w):
    new_student = StudentFactory(school=w.school)
    people.enroll_student(new_student, w.klass)
    codes = att.issue_class_qr_codes(w.klass, actor=w.admin)
    assert len(codes) == 4 and StudentQRCode.objects.filter(student=new_student, status=QRStatus.ACTIVE).exists()


# =============================================================================
# Scanning
# =============================================================================


def token(w, i=0):
    return w.qr[w.students[i].pk].token


def test_on_time_arrival_then_already_present(w):
    first = att.scan(token(w), actor=w.guardian_member, at=at(7, 20))
    assert first.scan.result == ScanResult.ACCEPTED and first.scan.guardian == w.guardian
    assert (first.attendance.status, first.attendance.late_minutes) == (DailyStatus.PRESENT, 0)
    second = att.scan(token(w), actor=w.guardian_member, at=at(7, 40))
    assert second.scan.result == ScanResult.ALREADY_PRESENT
    assert StudentDailyAttendance.objects.get(student=w.students[0]).arrival_time == at(7, 20)


def test_late_arrival_minutes_from_policy(w):
    outcome = att.scan(token(w), actor=w.guardian_member, at=at(8, 5))
    assert (outcome.attendance.status, outcome.attendance.late_minutes) == (DailyStatus.LATE, 35)


def test_day_without_policy_counts_present(w):
    tuesday = MONDAY + timedelta(days=1)
    outcome = att.scan(token(w), actor=w.guardian_member, at=at(9, 0, day=tuesday))
    assert (outcome.attendance.status, outcome.attendance.late_minutes) == (DailyStatus.PRESENT, 0)


def test_unknown_token_is_logged_without_storing_it(w):
    outcome = att.scan("not-a-real-token", actor=w.guardian_member, at=at(7))
    assert (outcome.scan.result, outcome.attendance, outcome.scan.student) == (ScanResult.UNKNOWN_TOKEN, None, None)
    assert "not-a-real-token" not in str(outcome.scan.metadata)


def test_token_of_another_school_is_unknown_and_creates_nothing(w):
    other = make_attendance_world(SchoolFactory())
    outcome = att.scan(token(other), actor=w.guardian_member, at=at(7))
    assert outcome.scan.result == ScanResult.UNKNOWN_TOKEN and outcome.scan.school == w.school
    assert not StudentDailyAttendance.objects.filter(student__school=other.school).exists()


def test_token_of_a_past_year_is_expired(w):
    past = AcademicYear.objects.create(
        school=w.school, name="2024-2025", start_date=date(2024, 9, 1), end_date=date(2025, 7, 31)
    )
    s = w.students[0]
    StudentEnrollment.objects.create(
        school=w.school,
        student=s,
        academic_year=past,
        enrollment_date=date(2024, 9, 2),
        school_class=SchoolClassFactory(school=w.school, academic_year=past),
    )
    old_qr = StudentQRCode.objects.create(
        school=w.school, student=s, academic_year=past, token="B" * 43, issued_at=at(7)
    )
    assert att.scan(old_qr.token, actor=w.guardian_member, at=at(7)).scan.result == ScanResult.EXPIRED_TOKEN


def test_withdrawn_student_is_refused(w):
    StudentEnrollment.objects.filter(student=w.students[0]).update(status=EnrollmentStatus.WITHDRAWN)
    assert att.scan(token(w), actor=w.guardian_member, at=at(7)).scan.result == ScanResult.STUDENT_NOT_ENROLLED


def test_who_may_scan(w):
    for role in ("PARENT", "TEACHER", "CONTENT_MANAGER"):
        with pytest.raises(PermissionDenied):
            att.scan(token(w), actor=member_with_role(w.school, role), at=at(7))
    assert att.scan(token(w), actor=member_with_role(w.school, "STAFF"), at=at(7)).scan.result == ScanResult.ACCEPTED
    assert att.scan(token(w, 1), actor=w.admin, at=at(7)).scan.result == ScanResult.ACCEPTED
    w.guardian.status = "SUSPENDED"
    w.guardian.save()
    with pytest.raises(PermissionDenied):
        att.scan(token(w, 2), actor=w.guardian_member, at=at(7))


def test_scan_log_is_append_only_postgresql(w):
    scan = att.scan(token(w), actor=w.guardian_member, at=at(7)).scan
    with rejected(), transaction.atomic():
        GuardianScan.objects.filter(pk=scan.pk).update(result=ScanResult.UNKNOWN_TOKEN)
    with rejected(), transaction.atomic():
        GuardianScan.objects.filter(pk=scan.pk).delete()


def test_accepted_scan_must_match_its_qr_student_postgresql(w):
    """Composite key (qr_code, student): a scan cannot attribute student A's
    QR code to student B."""
    with rejected(), transaction.atomic():
        GuardianScan.objects.create(
            school=w.school,
            scanned_by=w.admin,
            student=w.students[1],
            qr_code=w.qr[w.students[0].pk],
            academic_year=w.year,
            result=ScanResult.ACCEPTED,
        )
    with rejected(), transaction.atomic():  # accepted without a student
        GuardianScan.objects.create(school=w.school, scanned_by=w.admin, result=ScanResult.ACCEPTED)


# =============================================================================
# Daily attendance: database rules
# =============================================================================


@pytest.mark.parametrize(
    "fields",
    [
        {"status": DailyStatus.PRESENT},  # no arrival time
        {"status": DailyStatus.LATE, "arrival_time": "now", "late_minutes": 0},
        {"status": DailyStatus.PRESENT, "arrival_time": "now", "absence_hours": Decimal(2)},
        {"status": DailyStatus.ABSENT, "arrival_time": "now"},
    ],
)
def test_daily_attendance_checks(w, fields):
    if fields.get("arrival_time") == "now":
        fields = {**fields, "arrival_time": at(8)}
    with rejected(), transaction.atomic():
        StudentDailyAttendance.objects.create(
            school=w.school, student=w.students[0], academic_year=w.year, date=MONDAY, **fields
        )


def test_attendance_cannot_mix_schools_postgresql(w):
    with rejected(), transaction.atomic():
        StudentDailyAttendance.objects.create(
            school=w.school, student=StudentFactory(school=SchoolFactory()), academic_year=w.year, date=MONDAY
        )


def test_policy_checks_postgresql(w):
    with rejected(), transaction.atomic():
        AttendancePolicy.objects.create(
            school=w.school, day_of_week=8, late_after_time=time(7), morning_absence_cutoff=time(9)
        )
    with rejected(), transaction.atomic():
        AttendancePolicy.objects.create(
            school=w.school, day_of_week=2, late_after_time=time(10), morning_absence_cutoff=time(9)
        )


# =============================================================================
# Finalisation, corrections, alerts
# =============================================================================


def test_finalize_marks_absents_and_is_idempotent(w):
    att.scan(token(w), actor=w.guardian_member, at=at(7))
    result = att.finalize_day(w.school, MONDAY, actor=w.admin)
    assert (result["absences_created"], result["records_finalized"]) == (2, 3)
    absent = StudentDailyAttendance.objects.get(student=w.students[1], date=MONDAY)
    assert (absent.status, absent.absence_hours, absent.finalized_by) == (DailyStatus.ABSENT, Decimal("8.00"), w.admin)
    again = att.finalize_day(w.school, MONDAY, actor=w.admin)
    assert (again["absences_created"], again["records_finalized"]) == (0, 0)
    assert AuditLog.objects.filter(action="ATTENDANCE_DAY_FINALIZED").count() == 2


def test_finalize_rules(w):
    with pytest.raises(PermissionDenied):
        att.finalize_day(w.school, MONDAY, actor=w.tm_member)
    with pytest.raises(ValidationError) as exc:
        att.finalize_day(w.school, date(2030, 1, 7), actor=w.admin)
    assert exc.value.code == "day_outside_year"


def test_late_arrival_after_finalisation_turns_absence_into_late(w):
    att.finalize_day(w.school, MONDAY, actor=w.admin)
    outcome = att.scan(token(w), actor=w.guardian_member, at=at(11, 0))
    assert (outcome.attendance.status, outcome.attendance.absence_hours) == (DailyStatus.LATE, Decimal("0.00"))


def test_correction_excuses_with_audit(w):
    att.finalize_day(w.school, MONDAY, actor=w.admin)
    record = StudentDailyAttendance.objects.get(student=w.students[0], date=MONDAY)
    with pytest.raises(PermissionDenied):
        att.correct_attendance(record, actor=w.tm_member, status=DailyStatus.EXCUSED, reason="x")
    with pytest.raises(ValidationError):
        att.correct_attendance(record, actor=w.admin, status=DailyStatus.EXCUSED, reason="")
    att.correct_attendance(record, actor=w.admin, status=DailyStatus.EXCUSED, reason="Certificat médical")
    record.refresh_from_db()
    assert (record.status, record.source, record.note) == (DailyStatus.EXCUSED, "MANUAL", "Certificat médical")
    log = AuditLog.objects.get(action="ATTENDANCE_CORRECTED")
    assert (log.old_data["status"], log.new_data["status"]) == ("ABSENT", "EXCUSED")


def absent_days(w, student, n, excused=0):
    for i in range(n):
        day = MONDAY + timedelta(weeks=i)
        StudentDailyAttendance.objects.create(
            school=w.school,
            student=student,
            academic_year=w.year,
            date=day,
            status=DailyStatus.EXCUSED if i < excused else DailyStatus.ABSENT,
            absence_hours=Decimal("8.00"),
        )


@pytest.mark.parametrize(
    "days,excused,level", [(1, 0, "NONE"), (2, 0, "YELLOW"), (3, 0, "ORANGE"), (4, 0, "RED"), (4, 3, "NONE")]
)
def test_graduated_alert_levels(w, days, excused, level):
    """8 h per absent day; thresholds 10 / 20 / 30 h (SchoolConfiguration).
    Excused absences never raise the level."""
    s = w.students[0]
    absent_days(w, s, days, excused)
    summary = att.absence_summary(s, w.year)
    assert summary["alert_level"] == level
    assert summary["excused_absence_hours"] == Decimal(8 * excused)


# =============================================================================
# Convocations
# =============================================================================


def verified_parent(w, student):
    parent = ParentFactory(school=w.school)
    link = people.link_parent(parent, student, relationship_type="MOTHER")
    people.verify_parent_link(link, actor=w.admin, method=VerificationMethod.ADMIN_IN_PERSON)
    return parent


def test_convocation_records_alert_level_and_needs_verified_parent(w):
    s = w.students[0]
    absent_days(w, s, 4)
    parent = verified_parent(w, s)
    start = at(15)
    conv = att.create_convocation(
        s,
        parent,
        actor=w.admin,
        scheduled_start=start,
        scheduled_end=start + timedelta(hours=1),
        reason="Absences répétées",
    )
    assert conv.alert_level == "RED" and AuditLog.objects.filter(action="CONVOCATION_CREATED").exists()
    stranger = ParentFactory(school=w.school)
    with pytest.raises(ValidationError) as exc:
        att.create_convocation(
            s, stranger, actor=w.admin, scheduled_start=start, scheduled_end=start + timedelta(hours=1), reason="x"
        )
    assert exc.value.code == "parent_not_linked"
    with pytest.raises(PermissionDenied):
        att.create_convocation(
            s, parent, actor=w.tm_member, scheduled_start=start, scheduled_end=start + timedelta(hours=1), reason="x"
        )
    att.set_convocation_status(conv, "HELD", actor=w.admin, notes="Engagement des parents")
    with pytest.raises(ValidationError):
        att.set_convocation_status(conv, "CANCELLED", actor=w.admin)
