"""Documents integrity (ADR 0016): every source inside the document's school
(composite keys); a document is never deleted nor rewritten — the only
change allowed is PROVISIONAL -> SUPERSEDED; download traces are append-only."""

from django.db import migrations

from common.migration_operations import EnforceSameValue

SQL = """
CREATE OR REPLACE FUNCTION documents_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'document_immutable: documents are never deleted' USING ERRCODE = 'check_violation';
    END IF;
    IF NOT (OLD.status = 'PROVISIONAL' AND NEW.status = 'SUPERSEDED'
            AND (to_jsonb(NEW) - ARRAY['status', 'updated_at']) = (to_jsonb(OLD) - ARRAY['status', 'updated_at'])) THEN
        RAISE EXCEPTION 'document_immutable: a document only goes from PROVISIONAL to SUPERSEDED'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER documents_document_guard BEFORE UPDATE OR DELETE ON documents_document
    FOR EACH ROW EXECUTE FUNCTION documents_guard();

CREATE OR REPLACE FUNCTION documents_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'document_history_immutable: download traces cannot change' USING ERRCODE = 'check_violation';
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER documents_download_append_only BEFORE UPDATE OR DELETE ON documents_documentdownload
    FOR EACH ROW EXECUTE FUNCTION documents_append_only();
"""

REVERSE = """
DROP TRIGGER IF EXISTS documents_download_append_only ON documents_documentdownload;
DROP TRIGGER IF EXISTS documents_document_guard ON documents_document;
DROP FUNCTION IF EXISTS documents_append_only();
DROP FUNCTION IF EXISTS documents_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("documents", "0001_initial"),
        ("gradebook", "0005_class_principal_same_school"),
        ("finance", "0003_ledger_payroll"),
        ("payroll", "0002_integrity"),
        ("people", "0002_same_school_constraints"),
        ("academics", "0007_room_same_school"),
    ]

    operations = [
        *[
            EnforceSameValue("document", f)
            for f in (
                "report_card",
                "payment",
                "teacher_payroll",
                "staff_payroll",
                "student",
                "school_class",
                "generated_by",
            )
        ],
        EnforceSameValue("documentdownload", "document"),
        EnforceSameValue("documentdownload", "actor"),
        migrations.RunSQL(SQL, reverse_sql=REVERSE),
    ]
