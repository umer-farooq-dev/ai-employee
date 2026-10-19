from django.core.management.base import BaseCommand

from apps.campaigns import services as campaigns
from apps.voice import handoff, services


class Command(BaseCommand):
    help = (
        "Dial queued retries, scheduled follow-up calls and campaign calls that are due, and pass chat handoffs "
        "nobody answered to the next agent (cron: every minute)."
    )

    def handle(self, *args, **options):
        handoff.expire_ringing()
        self.stdout.write(f"Dialled {services.dial_due()} call(s).")
        self.stdout.write(f"Campaigns: {campaigns.dispatch()} call(s).")
