"""Communication integrity (ADR 0015).

Composite keys: every reference inside the row's school, and
    message(conversation, sender) -> participant(conversation, membership):
a message can only be written by a participant of its conversation.

Triggers:
- comm_no_delete: nothing in this domain is ever deleted (history, retention
  policy of spec §10 will purge through a dedicated, audited procedure);
- comm_append_only: status history and attachments never change;
- notification: only unread -> read, once;
- message / forum post: never edited, only hidden once (soft delete);
- complaint: content frozen once submitted, CANCELLED / CLOSED final.
"""

from django.db import migrations

from common.migration_operations import EnforceSameValue


def _no_change_except(keys):
    arr = ", ".join(f"'{k}'" for k in [*keys, "updated_at"])
    return f"(to_jsonb(NEW) - ARRAY[{arr}]) = (to_jsonb(OLD) - ARRAY[{arr}])"


NO_DELETE_TABLES = [
    "communication_notification",
    "communication_notificationdelivery",
    "communication_conversation",
    "communication_conversationparticipant",
    "communication_message",
    "communication_forumspace",
    "communication_forumthread",
    "communication_forumpost",
    "communication_complaint",
]
APPEND_ONLY_TABLES = [
    "communication_complaintstatushistory",
    "communication_messageattachment",
    "communication_complaintattachment",
]

SQL = f"""
CREATE OR REPLACE FUNCTION comm_no_delete() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'communication_history_immutable: % rows are never deleted', TG_TABLE_NAME
        USING ERRCODE = 'check_violation';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION comm_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'communication_history_immutable: % rows cannot be modified or deleted', TG_TABLE_NAME
        USING ERRCODE = 'check_violation';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION comm_notification_guard() RETURNS trigger AS $$
BEGIN
    IF NOT {_no_change_except(["is_read", "read_at"])}
       OR (OLD.is_read AND (NOT NEW.is_read OR NEW.read_at IS DISTINCT FROM OLD.read_at)) THEN
        RAISE EXCEPTION 'notification_immutable: a notification only goes from unread to read'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER comm_notification_guard BEFORE UPDATE ON communication_notification
    FOR EACH ROW EXECUTE FUNCTION comm_notification_guard();

CREATE OR REPLACE FUNCTION comm_soft_delete_guard() RETURNS trigger AS $$
BEGIN
    -- Only the deletion columns may be set, and only once.
    IF NOT {_no_change_except(["deleted_at", "deleted_by_id", "deletion_reason"])}
       OR OLD.deleted_at IS NOT NULL THEN
        RAISE EXCEPTION 'content_immutable: % rows are never edited, only hidden once', TG_TABLE_NAME
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER comm_message_guard BEFORE UPDATE ON communication_message
    FOR EACH ROW EXECUTE FUNCTION comm_soft_delete_guard();
CREATE TRIGGER comm_forumpost_guard BEFORE UPDATE ON communication_forumpost
    FOR EACH ROW EXECUTE FUNCTION comm_soft_delete_guard();

CREATE OR REPLACE FUNCTION comm_complaint_guard() RETURNS trigger AS $$
BEGIN
    IF OLD.status IN ('CANCELLED', 'CLOSED') THEN
        RAISE EXCEPTION 'complaint_final: a % complaint cannot change any more', OLD.status
            USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status <> 'DRAFT' AND (
        NEW.author_id, NEW.student_id, NEW.concerned_member_id, NEW.include_administration, NEW.category,
        NEW.subject, NEW.description, NEW.submitted_at
    ) IS DISTINCT FROM (
        OLD.author_id, OLD.student_id, OLD.concerned_member_id, OLD.include_administration, OLD.category,
        OLD.subject, OLD.description, OLD.submitted_at
    ) THEN
        RAISE EXCEPTION 'complaint_content_frozen: a submitted complaint is never rewritten'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER comm_complaint_guard BEFORE UPDATE ON communication_complaint
    FOR EACH ROW EXECUTE FUNCTION comm_complaint_guard();

-- A message's sender is a participant of its conversation.
ALTER TABLE communication_message ADD CONSTRAINT communication_message_sender_is_participant
    FOREIGN KEY (conversation_id, sender_id)
    REFERENCES communication_conversationparticipant (conversation_id, membership_id)
    DEFERRABLE INITIALLY DEFERRED;
""" + "".join(
    f"CREATE TRIGGER {t}_no_delete BEFORE DELETE ON {t} FOR EACH ROW EXECUTE FUNCTION comm_no_delete();\n"
    for t in NO_DELETE_TABLES
) + "".join(
    f"CREATE TRIGGER {t}_append_only BEFORE UPDATE OR DELETE ON {t} FOR EACH ROW EXECUTE FUNCTION comm_append_only();\n"
    for t in APPEND_ONLY_TABLES
)

REVERSE = (
    "ALTER TABLE communication_message DROP CONSTRAINT IF EXISTS communication_message_sender_is_participant;\n"
    + "".join(f"DROP TRIGGER IF EXISTS {t}_no_delete ON {t};\n" for t in NO_DELETE_TABLES)
    + "".join(f"DROP TRIGGER IF EXISTS {t}_append_only ON {t};\n" for t in APPEND_ONLY_TABLES)
    + """
DROP TRIGGER IF EXISTS comm_complaint_guard ON communication_complaint;
DROP TRIGGER IF EXISTS comm_forumpost_guard ON communication_forumpost;
DROP TRIGGER IF EXISTS comm_message_guard ON communication_message;
DROP TRIGGER IF EXISTS comm_notification_guard ON communication_notification;
DROP FUNCTION IF EXISTS comm_complaint_guard();
DROP FUNCTION IF EXISTS comm_soft_delete_guard();
DROP FUNCTION IF EXISTS comm_notification_guard();
DROP FUNCTION IF EXISTS comm_append_only();
DROP FUNCTION IF EXISTS comm_no_delete();
"""
)


class Migration(migrations.Migration):
    dependencies = [
        ("communication", "0001_initial"),
        ("people", "0002_same_school_constraints"),
        ("academics", "0007_room_same_school"),
    ]

    operations = [
        EnforceSameValue("notification", "recipient"),
        EnforceSameValue("notificationpreference", "membership"),
        EnforceSameValue("notificationdelivery", "notification"),
        *[EnforceSameValue("conversation", f) for f in ("student", "created_by")],
        *[EnforceSameValue("conversationparticipant", f) for f in ("conversation", "membership", "last_read_message")],
        *[EnforceSameValue("message", f) for f in ("conversation", "sender", "deleted_by")],
        *[EnforceSameValue("messageattachment", f) for f in ("message", "uploaded_by")],
        *[EnforceSameValue("forumspace", f) for f in ("school_class", "created_by")],
        *[EnforceSameValue("forumthread", f) for f in ("space", "created_by")],
        *[EnforceSameValue("forumpost", f) for f in ("thread", "author", "deleted_by")],
        *[
            EnforceSameValue("complaint", f)
            for f in ("author", "student", "concerned_member", "assigned_to", "conversation")
        ],
        *[EnforceSameValue("complaintstatushistory", f) for f in ("complaint", "changed_by")],
        *[EnforceSameValue("complaintattachment", f) for f in ("complaint", "uploaded_by")],
        migrations.RunSQL(SQL, reverse_sql=REVERSE),
    ]
