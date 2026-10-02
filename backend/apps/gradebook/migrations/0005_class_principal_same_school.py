from django.db import migrations

from common.migration_operations import EnforceSameValue


class Migration(migrations.Migration):
    dependencies = [("gradebook", "0004_class_principal")]

    operations = [
        EnforceSameValue("classprincipalassignment", "school_class"),
        EnforceSameValue("classprincipalassignment", "teacher"),
        EnforceSameValue("classprincipalassignment", "assigned_by"),
    ]
