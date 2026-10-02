"""PostgreSQL triggers protecting grades (ADR 0009).

1. Grades can only be inserted, updated or deleted while BOTH their
   assessment and its academic period are OPEN. Services check it too (clear
   error message); the trigger guarantees it for every code path.
2. GradeChangeLog is append-only: UPDATE and DELETE are refused.
   (TRUNCATE, used by the test suite to reset the database, is not a row
   operation and does not fire these triggers.)
"""

from django.db import migrations

GRADE_OPEN_PERIOD = """
CREATE OR REPLACE FUNCTION gradebook_grade_requires_open_period() RETURNS trigger AS $$
DECLARE
    v_assessment_id uuid;
    v_assessment_status text;
    v_period_status text;
BEGIN
    v_assessment_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.assessment_id ELSE NEW.assessment_id END;
    SELECT a.status, p.status INTO v_assessment_status, v_period_status
      FROM gradebook_assessment a
      JOIN academics_academicperiod p ON p.id = a.academic_period_id
     WHERE a.id = v_assessment_id;
    IF v_assessment_status IS DISTINCT FROM 'OPEN' OR v_period_status IS DISTINCT FROM 'OPEN' THEN
        RAISE EXCEPTION 'grade_period_closed: grades of assessment % cannot be changed (assessment %, period %)',
            v_assessment_id, v_assessment_status, v_period_status
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER gradebook_grade_open_period
    BEFORE INSERT OR UPDATE OR DELETE ON gradebook_grade
    FOR EACH ROW EXECUTE FUNCTION gradebook_grade_requires_open_period();
"""

CHANGE_LOG_IMMUTABLE = """
CREATE OR REPLACE FUNCTION gradebook_change_log_is_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'grade_change_log_immutable: grade history cannot be modified or deleted'
        USING ERRCODE = 'check_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER gradebook_change_log_immutable
    BEFORE UPDATE OR DELETE ON gradebook_gradechangelog
    FOR EACH ROW EXECUTE FUNCTION gradebook_change_log_is_immutable();
"""


class Migration(migrations.Migration):
    dependencies = [("gradebook", "0002_same_school_constraints")]

    operations = [
        migrations.RunSQL(
            GRADE_OPEN_PERIOD,
            reverse_sql="DROP TRIGGER IF EXISTS gradebook_grade_open_period ON gradebook_grade; "
            "DROP FUNCTION IF EXISTS gradebook_grade_requires_open_period();",
        ),
        migrations.RunSQL(
            CHANGE_LOG_IMMUTABLE,
            reverse_sql="DROP TRIGGER IF EXISTS gradebook_change_log_immutable ON gradebook_gradechangelog; "
            "DROP FUNCTION IF EXISTS gradebook_change_log_is_immutable();",
        ),
    ]
