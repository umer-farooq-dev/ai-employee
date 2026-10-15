"""Cron (every few minutes): queued / stuck knowledge sources, due website re-syncs (KB-01) and re-embedding after
the embedding model changes in AI Settings."""

from django.core.management.base import BaseCommand

from apps.knowledge.services import run_scheduled


class Command(BaseCommand):
    help = "Process queued knowledge, scheduled website re-syncs and missing embeddings."

    def handle(self, *args, **options):
        processed, embedded = run_scheduled()
        self.stdout.write(f"{processed} sources processed, {embedded} chunks embedded")
