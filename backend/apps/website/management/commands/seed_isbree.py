"""Initial ISBREE content and demonstration accounts (apps/website/isbree_seed.py).

    # contents only (school, contacts, first version of the pages and FAQ — all "to validate")
    docker compose exec -e ISBREE_DEMO_PASSWORD -e ISBREE_CONTACT_EMAIL web python manage.py seed_isbree
    # + fictitious demonstration data and accounts, + illustration images
    docker compose exec -e ISBREE_DEMO_PASSWORD web python manage.py seed_isbree --demo --images /app/seed-images

The password (ISBREE_DEMO_PASSWORD) and the contact e-mail
(ISBREE_CONTACT_EMAIL) come from the environment only: never stored in the
repository, never printed. Refused with the production settings.
"""

import os

from django.core.management.base import BaseCommand

from apps.website.isbree_seed import seed


class Command(BaseCommand):
    help = "Create or complete the ISBREE school contents (idempotent; never deletes)."

    def add_arguments(self, parser):
        parser.add_argument("--demo", action="store_true", help="Also create the fictitious demonstration data.")
        parser.add_argument("--images", help="Folder of illustration images (1.jpg … 10.webp).")

    def handle(self, *args, **options):
        result = seed(
            password=os.environ.get("ISBREE_DEMO_PASSWORD"),
            demo=options["demo"],
            images=options["images"],
            contact_email=os.environ.get("ISBREE_CONTACT_EMAIL") or None,
            contact_phone=os.environ.get("ISBREE_CONTACT_PHONE") or None,
        )
        for line in result.created or ["rien de nouveau : tout existait déjà"]:
            self.stdout.write(f"- {line}")
