"""System roles of the permission matrix (spec §8), as plain data.

Shared by the data migration (0002) and the test suite. It deliberately
contains no model import: migrations must work with *historical* models, so
the model class is passed in by the caller.
"""

SYSTEM_ROLES = [
    ("SUPER_ADMIN", "Super administrateur", "Contrôle total de l'établissement."),
    ("ADMIN", "Administrateur", "Administration courante de l'établissement."),
    ("TEACHER", "Enseignant", "Cours, notes, appels et planning de ses classes."),
    ("PARENT", "Parent / Tuteur", "Suivi des enfants rattachés après vérification."),
    ("GUARDIAN", "Gardien", "Scan des QR codes élèves à l'entrée."),
    ("STAFF", "Personnel", "Personnel administratif et technique."),
    ("CONTENT_MANAGER", "Gestionnaire de contenu", "Contenu du site public."),
]


def sync_system_roles(role_model):
    """Create or update every system role. Idempotent."""
    for code, name, description in SYSTEM_ROLES:
        role_model.objects.update_or_create(
            code=code, defaults={"name": name, "description": description, "system_role": True}
        )
