"""Replay the notification projectors over a time window (after an outage,
or to rebuild a missed dispatch). Idempotent: nothing is notified twice."""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.communication import events
from apps.core.models import School


class Command(BaseCommand):
    help = "Re-project business events into notifications (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--school", required=True, help="School code")
        parser.add_argument("--days", type=int, default=2, help="Window in days (default 2)")

    def handle(self, *args, school, days, **options):
        target = School.objects.get(code=school)
        created = events.replay(target, timezone.now() - timedelta(days=days))
        self.stdout.write(f"{created} notification(s) created")
