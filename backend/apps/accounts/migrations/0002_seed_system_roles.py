"""Seed the system roles of the permission matrix (spec §8).

Roles are data, but code relies on their codes (`RoleCode`), so they must
exist in every database from the start. A data migration guarantees that,
unlike a fixture someone might forget to load.
"""

from django.db import migrations

from apps.accounts.system_roles import SYSTEM_ROLES, sync_system_roles


def seed_roles(apps, schema_editor):
    sync_system_roles(apps.get_model("accounts", "Role"))


def unseed_roles(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Role.objects.filter(code__in=[code for code, _, _ in SYSTEM_ROLES]).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]

    operations = [migrations.RunPython(seed_roles, unseed_roles)]
