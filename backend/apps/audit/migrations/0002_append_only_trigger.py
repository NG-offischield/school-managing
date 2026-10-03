"""AuditLog is append-only (ADR 0010).

DELETE is refused. UPDATE is refused too, with one exception: setting
`school_id` / `actor_id` to NULL, which is what ON DELETE SET NULL does when
the referenced school or membership disappears — the history row survives.
"""

from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION audit_log_is_append_only() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'audit_log_immutable: audit rows cannot be deleted' USING ERRCODE = 'check_violation';
    END IF;
    IF (NEW.id, NEW.created_at, NEW.layer, NEW.action, NEW.entity_type, NEW.entity_id,
        NEW.old_data, NEW.new_data, NEW.ip_address, NEW.user_agent, NEW.correlation_id)
       IS DISTINCT FROM
       (OLD.id, OLD.created_at, OLD.layer, OLD.action, OLD.entity_type, OLD.entity_id,
        OLD.old_data, OLD.new_data, OLD.ip_address, OLD.user_agent, OLD.correlation_id)
       OR (NEW.school_id IS DISTINCT FROM OLD.school_id AND NEW.school_id IS NOT NULL)
       OR (NEW.actor_id IS DISTINCT FROM OLD.actor_id AND NEW.actor_id IS NOT NULL) THEN
        RAISE EXCEPTION 'audit_log_immutable: audit rows cannot be modified' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_log_append_only
    BEFORE UPDATE OR DELETE ON audit_auditlog
    FOR EACH ROW EXECUTE FUNCTION audit_log_is_append_only();
"""


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]

    operations = [
        migrations.RunSQL(
            SQL,
            reverse_sql="DROP TRIGGER IF EXISTS audit_log_append_only ON audit_auditlog; "
            "DROP FUNCTION IF EXISTS audit_log_is_append_only();",
        )
    ]
