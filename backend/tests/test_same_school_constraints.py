"""The composite "same school / same year" keys really exist in PostgreSQL (ADR 0008)."""

from django.db import connection

from .conftest import DB

pytestmark = DB


def composite_keys():
    """Two-column foreign keys, as PostgreSQL stores them. Matched on width,
    not on name: long names are truncated (with a hash) to 63 characters."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.conrelid::regclass::text, a1.attname, a2.attname
            FROM pg_constraint c
            JOIN pg_attribute a1 ON a1.attrelid = c.conrelid AND a1.attnum = c.conkey[1]
            JOIN pg_attribute a2 ON a2.attrelid = c.conrelid AND a2.attnum = c.conkey[2]
            WHERE c.contype = 'f' AND array_length(c.conkey, 1) = 2
            """
        )
        return set(cursor.fetchall())


def test_all_composite_keys_are_present():
    keys = composite_keys()
    # academics: 9 (0002) + 1 (0005) + 1 (0007) ; people: 25 (0002) ; gradebook: 22 (0002) + 3 (0005) ;
    # attendance: 17 (0002) + 1 (0004) ; scheduling: 34 (0002).
    assert len(keys) == 113
    assert {shared for _, _, shared in keys} == {
        "school_id",
        "academic_year_id",
        "max_score",
        "student_id",
        # planning copies kept equal to their course (ADR 0012)
        "course_id",
        "teacher_id",
        "planned_teacher_id",
        "school_class_id",
        "subject_id",
    }


def test_enrollment_guards_school_and_year():
    keys = composite_keys()
    assert ("people_studentenrollment", "school_class_id", "academic_year_id") in keys
    assert ("people_studentenrollment", "student_id", "school_id") in keys
    assert ("academics_academicperiod", "parent_period_id", "academic_year_id") in keys
    assert ("gradebook_grade", "assessment_id", "max_score") in keys
    assert ("gradebook_assessment", "academic_period_id", "academic_year_id") in keys
    assert ("attendance_guardianscan", "qr_code_id", "student_id") in keys
    assert ("scheduling_teachingsession", "course_id", "planned_teacher_id") in keys
    assert ("scheduling_scheduleslot", "course_id", "teacher_id") in keys
