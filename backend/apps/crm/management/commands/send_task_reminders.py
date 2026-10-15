"""CRM-16: email reminders for follow-up tasks. Run every few minutes from the server's scheduler (cron)."""

from django.core.management.base import BaseCommand
from django.urls import reverse
from django.utils import timezone

from apps.crm.services import due_reminders
from apps.notifications import services as mail
from apps.tenancy.context import platform_context


class Command(BaseCommand):
    help = "Send reminder emails for follow-up tasks that are due soon"

    def add_arguments(self, parser):
        parser.add_argument("--base-url", default="", help="e.g. https://app.example.com (for the link in the email)")

    def handle(self, base_url="", **options):
        sent = 0
        with platform_context():
            for task in due_reminders():
                link = f"{base_url.rstrip('/')}{reverse('panel:tasks')}"
                if mail.send(
                    "crm/task_reminder",
                    task.assigned_user.email,
                    {"task": task, "user": task.assigned_user, "task_url": link},
                ):
                    sent += 1
                task.reminded_at = timezone.now()
                task.save(update_fields=["reminded_at", "updated_at"])
        self.stdout.write(self.style.SUCCESS(f"{sent} reminder(s) sent"))
