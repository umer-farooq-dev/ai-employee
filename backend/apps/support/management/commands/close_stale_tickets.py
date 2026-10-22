"""SA-19: answered / resolved tickets without a company reply for support.auto_close_days are closed. Run daily."""

from django.core.management.base import BaseCommand

from apps.support.services import auto_close


class Command(BaseCommand):
    help = "Close support tickets nobody replied to"

    def handle(self, **options):
        self.stdout.write(self.style.SUCCESS(f"{auto_close()} ticket(s) closed"))
