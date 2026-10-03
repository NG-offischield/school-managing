"""Attendance & QR integrity (ADR 0011): same school / same year / same
student guarantees, and an append-only scan log."""

from django.db import migrations

from common.migration_operations import EnforceSameValue

SCAN_APPEND_ONLY = """
CREATE OR REPLACE FUNCTION attendance_scan_is_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'scan_log_immutable: QR scans cannot be modified or deleted'
        USING ERRCODE = 'check_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER attendance_scan_append_only
    BEFORE UPDATE OR DELETE ON attendance_guardianscan
    FOR EACH ROW EXECUTE FUNCTION attendance_scan_is_append_only();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0001_initial"),
        ("people", "0002_same_school_constraints"),
        ("academics", "0005_grading_scale_integrity_and_defaults"),
    ]

    operations = [
        EnforceSameValue("studentqrcode", "student"),
        EnforceSameValue("studentqrcode", "academic_year"),
        EnforceSameValue("studentqrcode", "generated_by"),
        EnforceSameValue("studentqrcode", "revoked_by"),
        EnforceSameValue("guardianscan", "scanned_by"),
        EnforceSameValue("guardianscan", "guardian"),
        EnforceSameValue("guardianscan", "student"),
        EnforceSameValue("guardianscan", "qr_code"),
        EnforceSameValue("guardianscan", "academic_year"),
        # The scanned QR code is THIS student's code for THIS year.
        EnforceSameValue("guardianscan", "qr_code", shared_field="student"),
        EnforceSameValue("guardianscan", "qr_code", shared_field="academic_year"),
        EnforceSameValue("studentdailyattendance", "student"),
        EnforceSameValue("studentdailyattendance", "academic_year"),
        EnforceSameValue("studentdailyattendance", "finalized_by"),
        EnforceSameValue("convocation", "student"),
        EnforceSameValue("convocation", "parent"),
        EnforceSameValue("convocation", "created_by"),
        migrations.RunSQL(
            SCAN_APPEND_ONLY,
            reverse_sql="DROP TRIGGER IF EXISTS attendance_scan_append_only ON attendance_guardianscan; "
            "DROP FUNCTION IF EXISTS attendance_scan_is_append_only();",
        ),
    ]
