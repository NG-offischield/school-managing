"""Database-enforced consistency of the academic core (ADR 0009)."""

from django.db import migrations

from common.migration_operations import EnforceSameValue


class Migration(migrations.Migration):
    dependencies = [
        ("gradebook", "0001_initial"),
        ("academics", "0005_grading_scale_integrity_and_defaults"),
        ("people", "0002_same_school_constraints"),
    ]

    operations = [
        # Course: everything in the same school; the class in the course's year.
        EnforceSameValue("course", "school_class"),
        EnforceSameValue("course", "school_class", shared_field="academic_year"),
        EnforceSameValue("course", "subject"),
        EnforceSameValue("course", "teacher"),
        EnforceSameValue("course", "academic_year"),
        EnforceSameValue("course", "grading_scale"),
        # Assessment: course and period of the same school AND the same year.
        EnforceSameValue("assessment", "course"),
        EnforceSameValue("assessment", "course", shared_field="academic_year"),
        EnforceSameValue("assessment", "academic_period"),
        EnforceSameValue("assessment", "academic_period", shared_field="academic_year"),
        EnforceSameValue("assessment", "created_by"),
        # Grade: same school, and max_score always equal to the assessment's
        # (ON UPDATE CASCADE) so that CHECK score <= max_score is meaningful.
        EnforceSameValue("grade", "assessment"),
        EnforceSameValue("grade", "assessment", shared_field="max_score", on_update="CASCADE"),
        EnforceSameValue("grade", "student"),
        EnforceSameValue("grade", "entered_by"),
        EnforceSameValue("gradechangelog", "grade"),
        EnforceSameValue("gradechangelog", "changed_by"),
        # Report cards.
        EnforceSameValue("reportcard", "student"),
        EnforceSameValue("reportcard", "academic_period"),
        EnforceSameValue("reportcard", "validated_by"),
        EnforceSameValue("reportcardline", "report_card"),
        EnforceSameValue("reportcardline", "subject"),
    ]
