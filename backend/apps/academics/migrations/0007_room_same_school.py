from django.db import migrations

from common.migration_operations import EnforceSameValue


class Migration(migrations.Migration):
    dependencies = [("academics", "0006_rooms")]

    operations = [EnforceSameValue("schoolclass", "main_room")]
