"""Phase 8: production scheduler (ENGR-04) and health check (ENGR-05)."""

import pytest
from django.core.management import get_commands

from apps.core.management.commands import run_scheduler


def test_scheduler_jobs_are_real_commands():
    commands = get_commands()
    assert all(name in commands for name, _, _ in run_scheduler.JOBS)


@pytest.mark.django_db
def test_scheduler_once_runs_every_job_and_reports_failures(monkeypatch):
    ran = []
    monkeypatch.setattr(run_scheduler, "call_command", lambda name, *a: ran.append((name, a)))
    from django.core.management import call_command

    call_command("run_scheduler", "--once")
    assert [n for n, _ in ran] == [n for n, _, _ in run_scheduler.JOBS]
    assert ("send_task_reminders", ("--base-url", "http://127.0.0.1:8000")) in ran

    def boom(name, *a):
        if name == "run_billing":
            raise RuntimeError("down")

    monkeypatch.setattr(run_scheduler, "call_command", boom)
    with pytest.raises(Exception, match="run_billing"):
        call_command("run_scheduler", "--once")


@pytest.mark.django_db
def test_healthz(client, monkeypatch):
    r = client.get("/healthz/")
    assert r.status_code == 200 and r.json() == {"status": "ok", "database": "ok", "cache": "ok"}
    from apps.core import views

    monkeypatch.setattr(views.cache, "get", lambda key: None)
    r = client.get("/healthz/")
    assert r.status_code == 503 and r.json()["cache"] == "down"
