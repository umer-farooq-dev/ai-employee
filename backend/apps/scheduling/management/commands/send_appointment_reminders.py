"""CAL-07: appointment reminders at the hours set in Calendar → Messages. Run every few minutes from cron."""

from django.core.management.base import BaseCommand

from apps.scheduling.notices import send_reminders


class Command(BaseCommand):
    help = "Send due appointment reminders (WhatsApp / e-mail) to customers"

    def handle(self, **options):
        self.stdout.write(self.style.SUCCESS(f"{send_reminders()} reminder(s) sent"))
