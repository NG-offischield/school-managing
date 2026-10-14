"""Print what still prevents a production opening of the ISBREE site (ADR 0032).

    manage.py isbree_readiness --school ISBREE

Exit code 1 when blocking items remain (usable in a deployment checklist);
never changes anything.
"""

import sys

from django.core.management.base import BaseCommand, CommandError

from apps.core.models import School
from apps.website.readiness import readiness_report


class Command(BaseCommand):
    help = "Production readiness of the ISBREE site (read only)."

    def add_arguments(self, parser):
        parser.add_argument("--school", required=True, help="Public code of the school.")

    def handle(self, *args, **options):
        school = School.objects.filter(code=options["school"]).first()
        if school is None:
            raise CommandError("Unknown school code.")
        report = readiness_report(school)
        for item in report["items"]:
            count = f" ({item['count']})" if item["count"] else ""
            self.stdout.write(f"[{item['severity'].upper():8}] {item['message']}{count}")
        self.stdout.write("PRÊT pour la production" if report["ready"] else "NON PRÊT : éléments bloquants ci-dessus")
        if not report["ready"]:
            sys.exit(1)
