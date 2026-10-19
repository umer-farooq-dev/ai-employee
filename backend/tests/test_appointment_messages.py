# ruff: noqa: F811 — pytest fixtures imported from the calendar and WhatsApp tests
"""Phase 6 part 3: appointment confirmations and reminders (CAL-07) and team alerts (CAL-10). Meta is faked; e-mails
go to Django's test outbox."""

import datetime as dt

import pytest
from django.core import mail
from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import Client

from apps.agents import tools as toolkit
from apps.crm import services as crm
from apps.scheduling import notices
from apps.scheduling import services as calendar
from apps.scheduling.models import Appointment, AppointmentNotice
from apps.tenancy.context import company_context
from apps.whatsapp.models import Template

from .test_calendar import at, next_monday, site, site_visit  # noqa: F401 — fixtures
from .test_voice_handoff import agent
from .test_whatsapp import fake, meta, number, realty, sara  # noqa: F401 — fixtures


@pytest.fixture
def person(realty, site):
    user = agent(realty, "ravi.sales@a.test")
    site.user = user
    site.save(update_fields=["user"])
    return user


@pytest.fixture
def approved(number, realty):
    """Approved confirmation and reminder templates (as after Meta's approval)."""
    rows = {}
    with company_context(realty.id):
        _approve(rows, realty, number)
    return rows


def _approve(rows, realty, number):
    for purpose, variables in (
        ("appointment_confirmation", ["lead.name", "appointment.type", "appointment.when", "appointment.number"]),
        ("appointment_reminder", ["appointment.type", "company.name", "appointment.when", "appointment.number"]),
    ):
        rows[purpose] = Template.objects.create(
            company=realty,
            number=number,
            name=purpose,
            language="en",
            meta_language="en",
            category="UTILITY",
            purpose=purpose,
            body="{{1}} {{2}} {{3}} {{4}}",
            variables=variables,
            status=Template.APPROVED,
        )


@pytest.fixture
def lead(realty):
    with company_context(realty.id):
        lead = crm.create_lead(realty, {"name": "Asha", "phone": "+919811112222", "email": "asha@example.com"})
        crm.record_consent(lead, "whatsapp", "opt_in", "test")
    return lead


def book(realty, site, site_visit, lead, hm="10:00", **kw):  # noqa: F811
    with company_context(realty.id):
        return calendar.book(realty, site, site_visit, at(next_monday(), hm), lead=lead, **kw)


def notes(appt, **kw):
    with company_context(appt.company_id):
        return list(AppointmentNotice.objects.filter(appointment=appt, **kw).order_by("created_at"))


# ---------------------------------------------------------------- CAL-07 confirmation, CAL-10 team alert
@pytest.mark.django_db
def test_booking_confirms_on_whatsapp_and_email_and_alerts_the_person(
    realty, site, site_visit, lead, person, approved, fake, django_capture_on_commit_callbacks  # noqa: F811
):
    with django_capture_on_commit_callbacks(execute=True):
        appt = book(realty, site, site_visit, lead, created_by_type="ai", channel="voice")
    template = [s for s in fake.sent if s[0] == "template"]
    assert template[0][1] == "+919811112222" and template[0][2] == "appointment_confirmation"
    assert template[0][3][0] == "Asha" and template[0][3][3] == appt.reference and "10:00" in template[0][3][2]
    to = {m.to[0]: m for m in mail.outbox}
    assert "confirmed" in to["asha@example.com"].subject and appt.reference in to["asha@example.com"].alternatives[0][0]
    staff = to["ravi.sales@a.test"]
    assert staff.subject.startswith("New booking:") and "the AI Employee" in staff.body and "Asha" in staff.body
    rows = {(n.kind, n.channel): n for n in notes(appt)}
    assert rows[("confirmation", "whatsapp")].status == "sent" and rows[("confirmation", "whatsapp")].wa_message
    assert rows[("confirmation", "email")].recipient == "asha@example.com"
    assert rows[("staff", "email")].recipient == "ravi.sales@a.test"
    # nothing is sent for a booking that is rolled back (the messages run only after commit)
    with django_capture_on_commit_callbacks(execute=True), pytest.raises(RuntimeError), transaction.atomic():
        book(realty, site, site_visit, lead, hm="14:00")
        raise RuntimeError
    assert len(mail.outbox) == 2


@pytest.mark.django_db
def test_move_and_cancel_tell_customer_and_team_but_not_the_person_who_changed_it(
    realty, site, site_visit, lead, person, approved, fake, django_capture_on_commit_callbacks  # noqa: F811
):
    with django_capture_on_commit_callbacks(execute=True):
        appt = book(realty, site, site_visit, lead)
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True), company_context(realty.id):
        calendar.reschedule(appt, at(next_monday(), "15:00"))
    subjects = {m.to[0]: m.subject for m in mail.outbox}
    assert "New time" in subjects["asha@example.com"] and subjects["ravi.sales@a.test"].startswith("Booking moved")
    assert "10:00" in mail.outbox[0].body  # "it was …"
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True), company_context(realty.id):
        calendar.set_status(appt, "cancelled", "Customer travelling", user=person)  # the person cancels it
    assert [m.to[0] for m in mail.outbox] == ["asha@example.com"] and "cancelled" in mail.outbox[0].subject
    cancelled = {n.channel: n for n in notes(appt, kind="cancelled")}
    assert cancelled["whatsapp"].status == "skipped" and "No approved WhatsApp template" in cancelled["whatsapp"].detail
    # cancelling again or completing does not send anything more
    with django_capture_on_commit_callbacks(execute=True), company_context(realty.id):
        calendar.set_status(appt, "completed")
    assert len(mail.outbox) == 1


# ---------------------------------------------------------------- CAL-07 reminders
@pytest.mark.django_db
def test_reminders_once_per_offset_latest_only_and_not_before_booking(
    realty, site, site_visit, lead, approved, fake  # noqa: F811
):
    appt = book(realty, site, site_visit, lead)  # no commit callbacks: confirmations not run here
    Appointment.all_companies.filter(pk=appt.pk).update(time_set_at=appt.starts_at - dt.timedelta(days=3))
    start = appt.starts_at
    assert notices.send_reminders(now=start - dt.timedelta(hours=30)) == 0
    assert notices.send_reminders(now=start - dt.timedelta(hours=23)) == 2  # WhatsApp + e-mail, 24 h
    assert notices.send_reminders(now=start - dt.timedelta(hours=22)) == 0  # once
    assert notices.send_reminders(now=start - dt.timedelta(minutes=90)) == 2  # 2 h
    rows = notes(appt, kind="reminder")
    assert sorted({n.offset_minutes for n in rows}) == [120, 1440] and all(n.status == "sent" for n in rows)
    assert [s[2] for s in fake.sent if s[0] == "template"] == ["appointment_reminder"] * 2
    assert "Reminder" in mail.outbox[0].subject

    # the job was down for a day: only the latest reminder goes
    late = book(realty, site, site_visit, lead, hm="14:00")
    Appointment.all_companies.filter(pk=late.pk).update(time_set_at=late.starts_at - dt.timedelta(days=3))
    assert notices.send_reminders(now=late.starts_at - dt.timedelta(hours=1)) == 2
    assert {n.offset_minutes for n in notes(late, kind="reminder")} == {120}

    # booked 1 h before: the 24 h and 2 h reminder times were already past
    soon = book(realty, site, site_visit, lead, hm="16:00")
    Appointment.all_companies.filter(pk=soon.pk).update(time_set_at=soon.starts_at - dt.timedelta(hours=1))
    assert notices.send_reminders(now=soon.starts_at - dt.timedelta(minutes=30)) == 0

    # cancelled or past appointments get none; a suspended company gets none
    with company_context(realty.id):
        calendar.set_status(soon, "cancelled", "x", notify=False)
    realty.status = "suspended"
    realty.save(update_fields=["status"])
    assert notices.send_reminders(now=start - dt.timedelta(minutes=30)) == 0


# ---------------------------------------------------------------- company choices, tests, panel, API
@pytest.mark.django_db
def test_company_choices_and_validation(
    realty, site, site_visit, lead, person, django_capture_on_commit_callbacks
):  # noqa: F811
    from apps.platform_config import services as config

    assert config.clean("calendar.reminder_hours", "2\n24\n\n") == ["24", "2"]  # Super Admin default, one per line
    with pytest.raises(ValidationError):
        config.clean("calendar.reminder_hours", "24\nabc")
    with company_context(realty.id):
        with pytest.raises(ValidationError):
            notices.save_policy(realty, {"reminder_hours": "abc"})
        with pytest.raises(ValidationError):
            notices.save_policy(realty, {"reminder_hours": "1000"})
        rules = notices.save_policy(
            realty, {"reminder_hours": "0.5, 24,24", "confirm_email": False, "notify_staff": False}
        )
    assert rules["reminder_hours"] == ["24", "0.5"] and rules["confirm_whatsapp"] is True
    with django_capture_on_commit_callbacks(execute=True):
        appt = book(realty, site, site_visit, lead)
    assert mail.outbox == [] and [n.channel for n in notes(appt)] == ["whatsapp"]
    assert notes(appt)[0].status == "skipped"  # no approved template
    # back to the platform defaults
    with company_context(realty.id):
        assert notices.save_policy(realty, {"use_platform": True})["reminder_hours"] == ["24", "2"]


@pytest.mark.django_db
def test_ai_booking_tool_sends_but_test_conversations_do_not(
    realty, sara, site, site_visit, lead, person, django_capture_on_commit_callbacks  # noqa: F811
):
    from apps.agents import runtime

    start = at(next_monday(), "10:00").replace(tzinfo=None).isoformat(timespec="minutes")
    for channel, hm in (("test", "10:00"), ("web_chat", "14:00")):
        with django_capture_on_commit_callbacks(execute=True), company_context(realty.id):
            conv = runtime.start(sara, channel, lead=lead)
            ctx = toolkit.ToolContext(realty, sara, conv, lead=lead, turn=1)
            out = toolkit.run(
                ctx, toolkit.enabled(sara), "book_site_visit", {"resource_id": str(site.pk), "start": start[:-5] + hm}
            )
        assert out.get("booked"), out
    sent = {m.to[0] for m in mail.outbox}
    assert sent == {"asha@example.com", "ravi.sales@a.test"} and len(mail.outbox) == 2  # only the real chat


@pytest.mark.django_db
def test_panel_and_api(
    client, owner_a, realty, site, site_visit, lead, person, approved, fake, django_capture_on_commit_callbacks
):  # noqa: F811
    client.force_login(owner_a)
    page = client.get("/app/calendar/messages/")
    assert page.status_code == 200 and "platform defaults" in page.content.decode()
    client.post("/app/calendar/messages/", {"confirm_whatsapp": "on", "reminder_hours": "48, 3", "notify_staff": "on"})
    realty.refresh_from_db()
    assert realty.settings["appointments"]["reminder_hours"] == ["48", "3"]
    assert realty.settings["appointments"]["confirm_email"] is False
    assert client.get("/api/v1/calendar/messages/").json()["uses_platform_defaults"] is False
    patched = client.patch("/api/v1/calendar/messages/", {"confirm_email": True}, content_type="application/json")
    assert patched.json()["confirm_email"] is True and patched.json()["reminder_hours"] == ["48", "3"]
    bad = client.patch("/api/v1/calendar/messages/", {"reminder_hours": ["x"]}, content_type="application/json")
    assert bad.status_code == 400

    with django_capture_on_commit_callbacks(execute=True):
        appt = book(realty, site, site_visit, lead, user=owner_a)
    detail = client.get(f"/app/calendar/appointments/{appt.pk}/").content.decode()
    assert "Messages" in detail and "asha@example.com" in detail and "Send confirmation again" in detail
    client.post(f"/app/calendar/appointments/{appt.pk}/", {"op": "resend"})
    assert len(notes(appt, kind="confirmation")) == 4
    data = client.get(f"/api/v1/calendar/appointments/{appt.pk}/").json()
    assert {n["channel"] for n in data["notices"]} == {"whatsapp", "email"}
    assert data["notices"][0]["delivery"] in ("sent", "")
    resent = client.post(f"/api/v1/calendar/appointments/{appt.pk}/resend/")
    assert resent.status_code == 200 and len(resent.json()) == 2

    # a human agent may book but not change the messages
    client.force_login(person)
    assert client.get("/app/calendar/messages/").status_code == 403
    assert client.patch("/api/v1/calendar/messages/", {}, content_type="application/json").status_code == 403
    assert Client().get("/api/v1/calendar/messages/").status_code in (401, 403)
