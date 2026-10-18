from django.core.management.base import BaseCommand

from apps.voice import services


class Command(BaseCommand):
    help = "Dial queued retries and scheduled follow-up calls that are due (cron: every minute)."

    def handle(self, *args, **options):
        self.stdout.write(f"Dialled {services.dial_due()} call(s).")
