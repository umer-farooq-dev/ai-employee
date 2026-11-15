from django.core.management.base import BaseCommand

from apps.audit import ops


class Command(BaseCommand):
    help = "E-mail the platform team about error bursts and failing providers (ENGR-05)."

    def handle(self, *args, **options):
        sent = ops.watch()
        self.stdout.write(f"alerts sent: {', '.join(sent) or 'none'}")
