"""Seed the system roles of the permission matrix (spec §8).

Roles are data, but code relies on their codes (`RoleCode`), so they must
exist in every database — including the test database — from the start.
A data migration guarantees that, unlike a fixture someone might forget to load.
"""

from django.db import migrations

SYSTEM_ROLES = [
    ("SUPER_ADMIN", "Super administrateur", "Contrôle total de l'établissement."),
    ("ADMIN", "Administrateur", "Administration courante de l'établissement."),
    ("TEACHER", "Enseignant", "Cours, notes, appels et planning de ses classes."),
    ("PARENT", "Parent / Tuteur", "Suivi des enfants rattachés après vérification."),
    ("GUARDIAN", "Gardien", "Scan des QR codes élèves à l'entrée."),
    ("STAFF", "Personnel", "Personnel administratif et technique."),
    ("CONTENT_MANAGER", "Gestionnaire de contenu", "Contenu du site public."),
]


def seed_roles(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    for code, name, description in SYSTEM_ROLES:
        # update_or_create: re-running the migration logic is harmless.
        Role.objects.update_or_create(
            code=code, defaults={"name": name, "description": description, "system_role": True}
        )


def unseed_roles(apps, schema_editor):
    Role = apps.get_model("accounts", "Role")
    Role.objects.filter(code__in=[code for code, _, _ in SYSTEM_ROLES]).delete()


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]

    operations = [migrations.RunPython(seed_roles, unseed_roles)]
