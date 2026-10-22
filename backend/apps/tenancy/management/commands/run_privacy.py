"""TEN-07 / SEC-12: account deletions whose grace period ended, expired export files, and retention of logs, alerts
and chat transcripts. Run daily from cron."""

from django.core.management.base import BaseCommand

from apps.tenancy.privacy import run


class Command(BaseCommand):
    help = "Run due account deletions and data retention"

    def handle(self, **options):
        self.stdout.write(self.style.SUCCESS(str(run())))
