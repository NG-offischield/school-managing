"""Database-enforced tenant consistency for the academic structure (ADR 0008).

Each operation adds a composite foreign key so PostgreSQL itself refuses a
relation between rows of two different schools (or, for periods, between two
different academic years).
"""

from django.db import migrations

from common.migration_operations import EnforceSameValue


class Migration(migrations.Migration):
    dependencies = [("academics", "0001_initial")]

    operations = [
        EnforceSameValue("academicperiod", "academic_year"),
        EnforceSameValue("academicperiod", "parent_period"),
        # A sub-period (Séquence 1) lives in the same year as its parent (Trimestre 1).
        EnforceSameValue("academicperiod", "parent_period", shared_field="academic_year"),
        EnforceSameValue("subject", "category"),
        EnforceSameValue("subjectcompatibilityrule", "pedagogical_category"),
        EnforceSameValue("subjectcompatibilityrule", "subject"),
        EnforceSameValue("subjectcompatibilityrule", "level"),
        EnforceSameValue("schoolclass", "level"),
        EnforceSameValue("schoolclass", "academic_year"),
    ]
