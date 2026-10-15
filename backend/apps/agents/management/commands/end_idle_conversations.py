"""Cron (every few minutes): end conversations idle longer than the AI setting, so the summary, CRM update and
scoring run (and test conversations remove their test records)."""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Max
from django.utils import timezone

from apps.agents import runtime
from apps.agents.models import Conversation
from apps.platform_config.services import get as setting
from apps.tenancy.context import company_context, platform_context


class Command(BaseCommand):
    help = "End idle AI conversations."

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(minutes=setting("ai.conversation_idle_minutes"))
        with platform_context():
            idle = list(
                Conversation.all_companies.filter(status=Conversation.ACTIVE)
                .annotate(last=Max("messages__created_at"))
                .filter(last__lt=cutoff)
                .values_list("pk", "company_id")
            )
        for pk, company_id in idle:
            with company_context(company_id):
                runtime.end(Conversation.objects.get(pk=pk))
        self.stdout.write(f"{len(idle)} conversations ended")
