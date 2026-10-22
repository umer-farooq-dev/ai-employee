"""SUB-03: trial reminders and ends, overdue subscriptions after the grace days, cancelled periods ending and the
next invoice for companies billed by invoice. Run daily (hourly is fine) from cron."""

from django.core.management.base import BaseCommand

from apps.billing.services import run


class Command(BaseCommand):
    help = "Move subscriptions through trial, renewal, overdue and hold"

    def handle(self, **options):
        self.stdout.write(self.style.SUCCESS(f"{run()} billing change(s)"))
