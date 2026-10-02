"""Database-enforced tenant consistency for people (ADR 0008).

Every relation between two school-owned rows is doubled by a composite
foreign key `(fk, school_id) -> target(id, school_id)`: a profile, link,
enrollment or qualification can never mix two schools, whatever code path
writes it. Optional relations (NULL) are not checked (MATCH SIMPLE).
"""

from django.db import migrations

from common.migration_operations import EnforceSameValue


class Migration(migrations.Migration):
    dependencies = [
        ("people", "0001_initial"),
        ("academics", "0002_same_school_constraints"),
    ]

    operations = [
        # Profiles <-> the membership they extend.
        EnforceSameValue("parentprofile", "membership"),
        EnforceSameValue("guardianprofile", "membership"),
        EnforceSameValue("employeeprofile", "membership"),
        EnforceSameValue("teacherprofile", "employee"),
        EnforceSameValue("staffprofile", "employee"),
        # Teacher <-> academic catalogue.
        EnforceSameValue("teacherprofile", "pedagogical_category"),
        EnforceSameValue("teacherprofile", "primary_subject"),
        EnforceSameValue("teachersubjectqualification", "teacher"),
        EnforceSameValue("teachersubjectqualification", "subject"),
        EnforceSameValue("teachersubjectqualification", "verified_by"),
        EnforceSameValue("compatibilityoverride", "teacher"),
        EnforceSameValue("compatibilityoverride", "subject"),
        EnforceSameValue("compatibilityoverride", "level"),
        EnforceSameValue("compatibilityoverride", "approved_by"),
        # Staff functions.
        EnforceSameValue("stafffunctionassignment", "staff"),
        EnforceSameValue("stafffunctionassignment", "function"),
        EnforceSameValue("stafffunctionassignment", "assigned_by"),
        # Enrollment: student, year and class of the same school, and the
        # class belongs to the enrollment's year.
        EnforceSameValue("studentenrollment", "student"),
        EnforceSameValue("studentenrollment", "academic_year"),
        EnforceSameValue("studentenrollment", "school_class"),
        EnforceSameValue("studentenrollment", "school_class", shared_field="academic_year"),
        EnforceSameValue("studentenrollment", "decision_by"),
        # Parent links.
        EnforceSameValue("parentstudent", "parent"),
        EnforceSameValue("parentstudent", "student"),
        EnforceSameValue("parentstudent", "verified_by"),
    ]
