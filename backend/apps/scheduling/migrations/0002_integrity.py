"""Planning integrity (ADR 0012).

Composite keys keep every planning row inside one school AND consistent with
its course: a slot / session carries the course's class, teacher (planned),
subject and year, and PostgreSQL refuses any divergence. ScheduleChange is
append-only except for the notification fields.
"""

from django.db import migrations

from common.migration_operations import EnforceSameValue

CHANGE_LOG_IMMUTABLE = """
CREATE OR REPLACE FUNCTION scheduling_change_is_append_only() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'schedule_change_immutable: planning history cannot be deleted'
            USING ERRCODE = 'check_violation';
    END IF;
    -- Only the notification dispatcher may update a row (status / date), and
    -- ON DELETE SET NULL of the author.
    IF (NEW.id, NEW.created_at, NEW.school_id, NEW.change_type, NEW.schedule_slot_id, NEW.session_id,
        NEW.school_class_id, NEW.teacher_ids, NEW.old_data, NEW.new_data, NEW.reason, NEW.changed_at)
       IS DISTINCT FROM
       (OLD.id, OLD.created_at, OLD.school_id, OLD.change_type, OLD.schedule_slot_id, OLD.session_id,
        OLD.school_class_id, OLD.teacher_ids, OLD.old_data, OLD.new_data, OLD.reason, OLD.changed_at)
       OR (NEW.changed_by_id IS DISTINCT FROM OLD.changed_by_id AND NEW.changed_by_id IS NOT NULL) THEN
        RAISE EXCEPTION 'schedule_change_immutable: planning history cannot be modified'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER scheduling_change_append_only
    BEFORE UPDATE OR DELETE ON scheduling_schedulechange
    FOR EACH ROW EXECUTE FUNCTION scheduling_change_is_append_only();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("scheduling", "0001_initial"),
        ("academics", "0007_room_same_school"),
        ("gradebook", "0005_class_principal_same_school"),
    ]

    operations = [
        # Slots: same school, and equal to their course.
        *[EnforceSameValue("scheduleslot", f) for f in ("course", "teacher", "school_class", "academic_year", "room", "created_by")],
        EnforceSameValue("scheduleslot", "course", shared_field="teacher"),
        EnforceSameValue("scheduleslot", "course", shared_field="school_class"),
        EnforceSameValue("scheduleslot", "course", shared_field="academic_year"),
        # Sessions: same school, equal to their course (planned teacher = course
        # teacher), same course as their slot, period of the same year.
        *[
            EnforceSameValue("teachingsession", f)
            for f in (
                "schedule_slot", "course", "school_class", "subject", "academic_year", "academic_period",
                "planned_teacher", "teacher", "room", "created_by",
            )
        ],
        EnforceSameValue("teachingsession", "course", shared_field="school_class"),
        EnforceSameValue("teachingsession", "course", shared_field="subject"),
        EnforceSameValue("teachingsession", "course", shared_field="academic_year"),
        EnforceSameValue("teachingsession", "course", shared_field="planned_teacher", target_field="teacher"),
        EnforceSameValue("teachingsession", "schedule_slot", shared_field="course"),
        EnforceSameValue("teachingsession", "academic_period", shared_field="academic_year"),
        # Availability, breaks, history.
        EnforceSameValue("teacheravailability", "teacher"),
        EnforceSameValue("teacheravailabilityexception", "teacher"),
        EnforceSameValue("teacheravailabilityexception", "requested_by"),
        EnforceSameValue("teacheravailabilityexception", "decided_by"),
        EnforceSameValue("schoolbreak", "academic_year"),
        *[EnforceSameValue("schedulechange", f) for f in ("schedule_slot", "session", "school_class", "changed_by")],
        migrations.RunSQL(
            CHANGE_LOG_IMMUTABLE,
            reverse_sql="DROP TRIGGER IF EXISTS scheduling_change_append_only ON scheduling_schedulechange; "
            "DROP FUNCTION IF EXISTS scheduling_change_is_append_only();",
        ),
    ]
