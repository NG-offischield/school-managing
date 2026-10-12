"""Load (or complete) the demonstration dataset — docs/demo-data.md.

    docker compose exec -e DEMO_PASSWORD web python manage.py seed_demo
    docker compose exec web python manage.py seed_demo --refill-wallets

- DEMO_PASSWORD (environment) is the password of the demo accounts created by
  this run (admin + parents). Needed only when an account must be created;
  never accepted as an argument, never printed, never stored in the repository.
- Safe to run again: missing objects are added, existing ones are kept
  (no duplicate); seeded payments are replayed through their idempotency keys.
- --refill-wallets: tops the demo wallets back up to their dataset balance
  after a demonstration (Finance FUNDING entries; nothing is deleted).
- Refused with the production settings.
"""

import os

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.demo import dataset
from apps.demo.seed import refill_wallets, seed

PASSWORD_ENV_VAR = "DEMO_PASSWORD"  # noqa: S105 - variable name, not a secret


class Command(BaseCommand):
    help = "Create or complete the demonstration dataset (school DEMO). Idempotent."

    def add_arguments(self, parser):
        parser.add_argument(
            "--refill-wallets",
            action="store_true",
            help="Top the demo wallets up to their dataset balance, then stop.",
        )

    def handle(self, *args, **opts):
        try:
            if opts["refill_wallets"]:
                refilled = refill_wallets()
                for owner, amount in refilled:
                    self.stdout.write(f"wallet du parent {owner} : +{amount} XAF")
                self.stdout.write(self.style.SUCCESS(f"{len(refilled)} wallet(s) rechargé(s)."))
                return
            world = seed(password=os.environ.get(PASSWORD_ENV_VAR))
        except (ImproperlyConfigured, ValidationError) as exc:
            raise CommandError(" ".join(getattr(exc, "messages", [str(exc)]))) from exc
        for line in world.created:
            self.stdout.write(f"+ {line}")
        if not world.created:
            self.stdout.write("Rien à créer : le jeu de démonstration est déjà complet.")
        self.stdout.write(
            self.style.SUCCESS(
                f"Établissement {world.school.code} prêt : {len(world.students)} élèves, {len(world.parents)} parents, "
                f"{len(world.invoices)} factures, {len(world.wallets)} wallets, 1 gardien."
            )
        )
        for spec in dataset.PARENTS:
            wallet = world.wallets[spec["key"]]
            wallet.refresh_from_db()
            self.stdout.write(f"  parent {spec['key']} {spec['email']} : wallet {wallet} = {wallet.balance} XAF")
        self.stdout.write(
            f"  gardien {dataset.GUARDIAN['username']} ({dataset.GUARDIAN['email']}), "
            f"{len(world.qr_codes)} QR codes élèves actifs (cartes : Documents → Carte élève)"
        )
