from django.db import migrations

from common.migration_operations import EnforceSameValue


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0003_scan_teaching_session"),
        ("scheduling", "0002_integrity"),
    ]

    operations = [EnforceSameValue("guardianscan", "teaching_session")]
