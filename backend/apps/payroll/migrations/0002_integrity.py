"""Payroll integrity (ADR 0014).

Composite keys (same school, plus the business invariants):
- a check-in's teacher is its session's teacher;
- a line's session / profile / check-in / payroll all concern the line's
  teacher and session;
- a settlement's line is a line of the same payroll and the same session.

Triggers:
- payroll_append_only: calculation lines and settlements are never changed;
- payroll_checkin_guard: a cancelled session can never be validated;
- payroll_session_frozen: a VALIDATED session cannot be changed (times,
  teacher, status...) until its validation is revoked;
- payroll_line_guard: an EARNED line only for a VALIDATED + COMPLETED
  session, a PROGRAMMED line never for a cancelled one, lines only into the
  current version of a CALCULATED payroll;
- payroll_payroll_guard: no deletion; CLOSED period = frozen; APPROVED
  freezes the amounts; PAID and CANCELLED are final;
- payroll_adjustment_guard / payroll_profile_guard / payroll_period_guard:
  history rows are never deleted and only progress in allowed ways;
- payroll_settlement_guard: a settlement only for a PAID payroll.
"""

from django.db import migrations

from common.migration_operations import EnforceSameValue


def _no_change_except(keys):
    """SQL expression: OLD and NEW are equal except for `keys`."""
    arr = ", ".join(f"'{k}'" for k in [*keys, "updated_at"])
    return f"(to_jsonb(NEW) - ARRAY[{arr}]) = (to_jsonb(OLD) - ARRAY[{arr}])"


SQL = f"""
CREATE OR REPLACE FUNCTION payroll_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'payroll_history_immutable: % rows cannot be modified or deleted', TG_TABLE_NAME
        USING ERRCODE = 'check_violation';
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER payroll_payrollline_append_only BEFORE UPDATE OR DELETE ON payroll_payrollline
    FOR EACH ROW EXECUTE FUNCTION payroll_append_only();
CREATE TRIGGER payroll_payrollsettlement_append_only BEFORE UPDATE OR DELETE ON payroll_payrollsettlement
    FOR EACH ROW EXECUTE FUNCTION payroll_append_only();

-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION payroll_checkin_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'checkin_immutable: check-ins are never deleted' USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.verified_status = 'VALIDATED' AND EXISTS (
        SELECT 1 FROM scheduling_teachingsession s WHERE s.id = NEW.teaching_session_id AND s.status = 'CANCELLED'
    ) THEN
        RAISE EXCEPTION 'session_not_payable: a cancelled session cannot be validated'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER payroll_checkin_guard BEFORE INSERT OR UPDATE OR DELETE ON payroll_teachersessioncheckin
    FOR EACH ROW EXECUTE FUNCTION payroll_checkin_guard();

-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION payroll_session_frozen() RETURNS trigger AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM payroll_teachersessioncheckin c
        WHERE c.teaching_session_id = OLD.id AND c.verified_status = 'VALIDATED'
    ) AND (NEW.status, NEW.teacher_id, NEW.course_id, NEW.date, NEW.scheduled_start, NEW.scheduled_end,
           NEW.actual_start, NEW.actual_end)
          IS DISTINCT FROM
          (OLD.status, OLD.teacher_id, OLD.course_id, OLD.date, OLD.scheduled_start, OLD.scheduled_end,
           OLD.actual_start, OLD.actual_end) THEN
        RAISE EXCEPTION 'session_validated_frozen: revoke the validation before changing this session'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER payroll_session_frozen BEFORE UPDATE ON scheduling_teachingsession
    FOR EACH ROW EXECUTE FUNCTION payroll_session_frozen();

-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION payroll_line_guard() RETURNS trigger AS $$
DECLARE
    p_status text;
    p_version integer;
BEGIN
    IF NEW.teacher_payroll_id IS NOT NULL THEN
        SELECT status, version INTO p_status, p_version FROM payroll_teacherpayroll WHERE id = NEW.teacher_payroll_id;
    ELSE
        SELECT status, version INTO p_status, p_version FROM payroll_staffpayroll WHERE id = NEW.staff_payroll_id;
    END IF;
    IF p_status IS DISTINCT FROM 'CALCULATED' OR p_version IS DISTINCT FROM NEW.version THEN
        RAISE EXCEPTION 'payroll_line_rejected: lines only go into the current calculation of a prepared payroll'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.kind = 'EARNED' AND NOT EXISTS (
        SELECT 1 FROM payroll_teachersessioncheckin c
        JOIN scheduling_teachingsession s ON s.id = c.teaching_session_id
        WHERE c.id = NEW.check_in_id AND c.teaching_session_id = NEW.teaching_session_id
          AND c.verified_status = 'VALIDATED' AND s.status = 'COMPLETED'
    ) THEN
        RAISE EXCEPTION 'session_not_payable: only an administratively validated, completed session is payable'
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.kind = 'PROGRAMMED' AND EXISTS (
        SELECT 1 FROM scheduling_teachingsession s WHERE s.id = NEW.teaching_session_id AND s.status = 'CANCELLED'
    ) THEN
        RAISE EXCEPTION 'session_not_payable: a cancelled session is not programmed remuneration'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER payroll_line_guard BEFORE INSERT ON payroll_payrollline
    FOR EACH ROW EXECUTE FUNCTION payroll_line_guard();

-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION payroll_payroll_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'payroll_immutable: payrolls are never deleted' USING ERRCODE = 'check_violation';
    END IF;
    IF EXISTS (SELECT 1 FROM payroll_payrollperiod p WHERE p.id = NEW.payroll_period_id AND p.status = 'CLOSED') THEN
        RAISE EXCEPTION 'period_closed: the payroll period is closed' USING ERRCODE = 'check_violation';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'CALCULATED' THEN
            RAISE EXCEPTION 'payroll_immutable: a payroll starts CALCULATED' USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.status IN ('PAID', 'CANCELLED') THEN
        RAISE EXCEPTION 'payroll_immutable: a % payroll is final', OLD.status USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status = 'CALCULATED' AND NEW.status NOT IN ('CALCULATED', 'APPROVED', 'CANCELLED') THEN
        RAISE EXCEPTION 'payroll_immutable: a prepared payroll must be approved before payment'
            USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status = 'APPROVED' AND (
        NEW.status NOT IN ('APPROVED', 'PAID', 'CANCELLED')
        OR NOT {_no_change_except(["status", "paid_at", "paid_by_id", "payout_method", "wallet_id",
                                   "payment_reference", "cancelled_reason"])}
    ) THEN
        RAISE EXCEPTION 'payroll_immutable: an approved payroll can only be paid or cancelled'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER payroll_teacherpayroll_guard BEFORE INSERT OR UPDATE OR DELETE ON payroll_teacherpayroll
    FOR EACH ROW EXECUTE FUNCTION payroll_payroll_guard();
CREATE TRIGGER payroll_staffpayroll_guard BEFORE INSERT OR UPDATE OR DELETE ON payroll_staffpayroll
    FOR EACH ROW EXECUTE FUNCTION payroll_payroll_guard();

-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION payroll_settlement_guard() RETURNS trigger AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM payroll_teacherpayroll p WHERE p.id = NEW.teacher_payroll_id AND p.status = 'PAID') THEN
        RAISE EXCEPTION 'settlement_rejected: only a paid payroll settles sessions' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER payroll_settlement_guard BEFORE INSERT ON payroll_payrollsettlement
    FOR EACH ROW EXECUTE FUNCTION payroll_settlement_guard();

-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION payroll_adjustment_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'adjustment_immutable: corrections are never deleted' USING ERRCODE = 'check_violation';
    END IF;
    IF NOT {_no_change_except(["settled_teacher_payroll_id", "settled_staff_payroll_id"])}
       OR OLD.settled_teacher_payroll_id IS NOT NULL OR OLD.settled_staff_payroll_id IS NOT NULL
       OR NOT EXISTS (
           SELECT 1 FROM payroll_teacherpayroll p WHERE p.id = NEW.settled_teacher_payroll_id AND p.status = 'PAID'
           UNION ALL
           SELECT 1 FROM payroll_staffpayroll p WHERE p.id = NEW.settled_staff_payroll_id AND p.status = 'PAID'
       ) THEN
        RAISE EXCEPTION 'adjustment_immutable: a correction is only settled once, by a paid payroll'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER payroll_adjustment_guard BEFORE UPDATE OR DELETE ON payroll_salaryadjustment
    FOR EACH ROW EXECUTE FUNCTION payroll_adjustment_guard();

-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION payroll_profile_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'rate_immutable: rates are never deleted' USING ERRCODE = 'check_violation';
    END IF;
    -- A rate is never edited: only closed (effective_to) or deactivated.
    IF NOT {_no_change_except(["effective_to", "active"])}
       OR (OLD.effective_to IS NOT NULL AND NEW.effective_to IS DISTINCT FROM OLD.effective_to)
       OR (NOT OLD.active AND NEW.active) THEN
        RAISE EXCEPTION 'rate_immutable: change a rate by ending it and creating a new one'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER payroll_teacherrate_guard BEFORE UPDATE OR DELETE ON payroll_teachercompensationprofile
    FOR EACH ROW EXECUTE FUNCTION payroll_profile_guard();
CREATE TRIGGER payroll_staffsalary_guard BEFORE UPDATE OR DELETE ON payroll_staffcompensationprofile
    FOR EACH ROW EXECUTE FUNCTION payroll_profile_guard();

-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION payroll_period_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'period_immutable: payroll periods are never deleted' USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status = 'CLOSED' THEN
        RAISE EXCEPTION 'period_closed: the payroll period is closed' USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.status = 'CLOSED' AND EXISTS (
        SELECT 1 FROM payroll_teacherpayroll p WHERE p.payroll_period_id = NEW.id AND p.status IN ('CALCULATED', 'APPROVED')
        UNION ALL
        SELECT 1 FROM payroll_staffpayroll p WHERE p.payroll_period_id = NEW.id AND p.status IN ('CALCULATED', 'APPROVED')
    ) THEN
        RAISE EXCEPTION 'period_not_settled: every payroll must be paid or cancelled before closing'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER payroll_period_guard BEFORE UPDATE OR DELETE ON payroll_payrollperiod
    FOR EACH ROW EXECUTE FUNCTION payroll_period_guard();
"""

REVERSE = """
DROP TRIGGER IF EXISTS payroll_period_guard ON payroll_payrollperiod;
DROP TRIGGER IF EXISTS payroll_staffsalary_guard ON payroll_staffcompensationprofile;
DROP TRIGGER IF EXISTS payroll_teacherrate_guard ON payroll_teachercompensationprofile;
DROP TRIGGER IF EXISTS payroll_adjustment_guard ON payroll_salaryadjustment;
DROP TRIGGER IF EXISTS payroll_settlement_guard ON payroll_payrollsettlement;
DROP TRIGGER IF EXISTS payroll_staffpayroll_guard ON payroll_staffpayroll;
DROP TRIGGER IF EXISTS payroll_teacherpayroll_guard ON payroll_teacherpayroll;
DROP TRIGGER IF EXISTS payroll_line_guard ON payroll_payrollline;
DROP TRIGGER IF EXISTS payroll_session_frozen ON scheduling_teachingsession;
DROP TRIGGER IF EXISTS payroll_checkin_guard ON payroll_teachersessioncheckin;
DROP TRIGGER IF EXISTS payroll_payrollsettlement_append_only ON payroll_payrollsettlement;
DROP TRIGGER IF EXISTS payroll_payrollline_append_only ON payroll_payrollline;
DROP FUNCTION IF EXISTS payroll_period_guard();
DROP FUNCTION IF EXISTS payroll_profile_guard();
DROP FUNCTION IF EXISTS payroll_adjustment_guard();
DROP FUNCTION IF EXISTS payroll_settlement_guard();
DROP FUNCTION IF EXISTS payroll_payroll_guard();
DROP FUNCTION IF EXISTS payroll_line_guard();
DROP FUNCTION IF EXISTS payroll_session_frozen();
DROP FUNCTION IF EXISTS payroll_checkin_guard();
DROP FUNCTION IF EXISTS payroll_append_only();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0001_initial"),
        ("finance", "0003_ledger_payroll"),
        ("scheduling", "0002_integrity"),
        ("people", "0002_same_school_constraints"),
        ("academics", "0007_room_same_school"),
    ]

    operations = [
        # Check-ins: same school, and the check-in's teacher IS the session's teacher.
        *[EnforceSameValue("teachersessioncheckin", f) for f in ("teaching_session", "teacher", "verified_by")],
        EnforceSameValue("teachersessioncheckin", "teaching_session", shared_field="teacher"),
        # Rates.
        EnforceSameValue("teachercompensationprofile", "teacher"),
        EnforceSameValue("teachercompensationprofile", "academic_year"),
        EnforceSameValue("staffcompensationprofile", "staff"),
        # Periods and payrolls.
        EnforceSameValue("payrollperiod", "academic_year"),
        *[EnforceSameValue("teacherpayroll", f) for f in ("teacher", "payroll_period", "wallet", "approved_by")],
        *[EnforceSameValue("staffpayroll", f) for f in ("staff", "payroll_period", "wallet", "approved_by")],
        # Corrections.
        *[
            EnforceSameValue("salaryadjustment", f)
            for f in ("employee", "teaching_session", "settled_teacher_payroll", "settled_staff_payroll")
        ],
        # Lines: same school, and every reference concerns the line's teacher / session.
        *[
            EnforceSameValue("payrollline", f)
            for f in (
                "teacher_payroll",
                "staff_payroll",
                "teacher",
                "teaching_session",
                "check_in",
                "teacher_profile",
                "staff_profile",
                "adjustment",
            )
        ],
        EnforceSameValue("payrollline", "teacher_payroll", shared_field="teacher"),
        EnforceSameValue("payrollline", "teaching_session", shared_field="teacher"),
        EnforceSameValue("payrollline", "teacher_profile", shared_field="teacher"),
        EnforceSameValue("payrollline", "check_in", shared_field="teaching_session"),
        # Settlements: the line paid is a line of this payroll for this session.
        *[EnforceSameValue("payrollsettlement", f) for f in ("teaching_session", "teacher_payroll", "line")],
        EnforceSameValue("payrollsettlement", "line", shared_field="teaching_session"),
        EnforceSameValue("payrollsettlement", "line", shared_field="teacher_payroll"),
        migrations.RunSQL(SQL, reverse_sql=REVERSE),
    ]
