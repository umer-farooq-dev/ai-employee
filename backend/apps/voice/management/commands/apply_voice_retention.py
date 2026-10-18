from django.core.management.base import BaseCommand

from apps.voice import services


class Command(BaseCommand):
    help = "Delete call recordings and voice transcripts past each company's retention days (cron: daily)."

    def handle(self, *args, **options):
        removed = services.apply_retention()
        self.stdout.write(
            f"Removed {removed['recordings']} recording(s) and {removed['transcripts']} transcript line(s)."
        )
