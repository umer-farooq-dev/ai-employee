"""CP-03: usage alerts to company admins at the levels in System Settings → Team alerts. Run hourly from cron."""

from django.core.management.base import BaseCommand

from apps.billing.usage import send_usage_alerts


class Command(BaseCommand):
    help = "Alert company admins when the monthly plan limits pass the alert levels"

    def handle(self, **options):
        self.stdout.write(self.style.SUCCESS(f"{send_usage_alerts()} usage alert(s)"))
