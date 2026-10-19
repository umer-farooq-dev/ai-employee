from django.core.management.base import BaseCommand

from apps.voice import handoff, services


class Command(BaseCommand):
    help = (
        "Dial queued retries and scheduled follow-up calls that are due, and pass chat handoffs nobody answered to "
        "the next agent (cron: every minute)."
    )

    def handle(self, *args, **options):
        handoff.expire_ringing()
        self.stdout.write(f"Dialled {services.dial_due()} call(s).")
