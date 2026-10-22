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
    from apps.audit import ops

    r = client.get("/healthz/")
    assert r.status_code == 200 and r.json() == {"status": "ok", "database": "ok", "cache": "ok", "scheduler": "down"}
    ops.beat()
    assert client.get("/healthz/").json()["scheduler"] == "ok"  # reported, never makes the web container unhealthy
    from apps.core import views

    monkeypatch.setattr(views.cache, "get", lambda key: None)
    r = client.get("/healthz/")
    assert r.status_code == 503 and r.json()["cache"] == "down"


@pytest.mark.django_db
def test_ops_alerts_once_per_cooldown(set_setting):
    from django.core import mail

    from apps.audit import ops
    from apps.audit.models import ErrorLog
    from apps.providers.models import Provider

    set_setting("monitoring.alert_emails", ["ops@platform.example"])
    set_setting("monitoring.error_threshold", 3)
    for _ in range(2):
        ErrorLog.objects.create(level="ERROR", logger="django.request", message="boom", path="/app/")
    assert ops.watch() == []  # below the threshold
    ErrorLog.objects.create(level="ERROR", logger="django.request", message="boom", path="/app/")
    p = Provider.objects.get(key="twilio")
    p.is_active, p.health = True, {"ok": False, "message": "401 Unauthorized"}
    p.save()
    assert sorted(ops.watch()) == ["errors", "provider:twilio"]
    assert {m.subject for m in mail.outbox} == {"[local] 3 server errors in 15 minutes", "[local] Twilio is failing"}
    assert all(m.to == ["ops@platform.example"] for m in mail.outbox)
    assert ops.watch() == []  # same problems inside the cool-down: no repeat
