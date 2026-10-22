"""ENGR-04: runs every scheduled job of the platform in one long-lived process, so a server needs no crontab.

    python manage.py run_scheduler            # forever (the "scheduler" container)
    python manage.py run_scheduler --once     # every job once, then exit (smoke test)

Each job runs in its own thread and is skipped while its previous run is still busy, so a slow knowledge import never
delays call retries. Run exactly one scheduler per environment.
"""

import logging
import threading
import time

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

log = logging.getLogger(__name__)

MINUTE, HOUR, DAY = 60, 3600, 86400

# (command, seconds between runs, arguments) — the same list as the README's cron section
JOBS = [
    ("dial_due_calls", MINUTE, []),
    ("send_task_reminders", 5 * MINUTE, lambda: ["--base-url", settings.PUBLIC_BASE_URL]),
    ("process_knowledge", 5 * MINUTE, []),
    ("end_idle_conversations", 5 * MINUTE, []),
    ("send_appointment_reminders", 5 * MINUTE, []),
    ("send_usage_alerts", HOUR, []),
    ("run_billing", HOUR, []),
    ("run_privacy", DAY, []),
    ("close_stale_tickets", DAY, []),
    ("apply_voice_retention", DAY, []),
]


def run_job(name, args):
    started = time.monotonic()
    try:
        call_command(name, *(args() if callable(args) else args))
        log.info("scheduler job done", extra={"job": name, "seconds": round(time.monotonic() - started, 1)})
        return True
    except Exception:
        log.exception("scheduler job failed", extra={"job": name})  # lands in Super Admin → Logs → Errors
        return False
    finally:
        close_old_connections()


class Command(BaseCommand):
    help = "Run the platform's scheduled jobs (replaces crontab entries)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Run every job once and exit")

    def handle(self, *args, once=False, **options):
        if once:
            failed = [name for name, _, job_args in JOBS if not run_job(name, job_args)]
            if failed:
                raise CommandError(f"Failed: {', '.join(failed)}")
            return
        due = {name: 0.0 for name, _, _ in JOBS}  # everything runs once at start-up
        busy = {}
        self.stdout.write(f"Scheduler: {len(JOBS)} jobs")
        while True:
            now = time.monotonic()
            for name, every, job_args in JOBS:
                if now >= due[name] and not (busy.get(name) and busy[name].is_alive()):
                    due[name] = now + every
                    busy[name] = threading.Thread(target=run_job, args=(name, job_args), name=name, daemon=True)
                    busy[name].start()
            time.sleep(5)
