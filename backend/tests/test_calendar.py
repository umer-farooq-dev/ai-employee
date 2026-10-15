"""Phase 3 part 4: calendar (CAL-01 … CAL-05, CAL-08, CAL-09) — availability, booking, double-booking, panel, API."""

import datetime
import threading
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import Client
from django.utils import timezone

from apps.crm import services as crm
from apps.industries.models import AppointmentType, Holiday, Industry
from apps.scheduling import services as calendar
from apps.scheduling.models import Appointment, AvailabilityException, Resource
from apps.tenancy.context import company_context

IST = ZoneInfo("Asia/Kolkata")


def next_monday():
    today = timezone.localdate()
    return today + datetime.timedelta(days=(7 - today.weekday()) % 7 or 7)


def at(date, hm):
    h, m = map(int, hm.split(":"))
    return datetime.datetime.combine(date, datetime.time(h, m), IST)


@pytest.fixture
def realty(company_a):
    industry = Industry.objects.get(key="real-estate")
    company_a.industry, company_a.template_version = industry, industry.published_version
    company_a.save()
    return company_a


@pytest.fixture
def site_visit(realty):
    return AppointmentType.objects.get(template_version=realty.template_version, key="site_visit")


@pytest.fixture
def site(realty):
    with company_context(realty.id):
        return calendar.save_resource(
            realty,
            {
                "name": "Green Valley site",
                "kind": "site",
                "slot_minutes": 60,
                "buffer_minutes": 0,
                "max_per_slot": 1,
                "min_notice_minutes": 60,
                "booking_window_days": 30,
                "working_hours": {d: "10:00-13:00, 14:00-17:00" for d in ("mon", "tue", "wed", "thu", "fri")},
            },
        )


# ---------------------------------------------------------------- availability (CAL-03, CAL-09)
@pytest.mark.django_db
def test_slots_follow_hours_breaks_and_duration(site, site_visit):
    monday = next_monday()
    slots = [s.astimezone(IST).strftime("%H:%M") for s in calendar.available_slots(site, site_visit, monday)]
    # 60-min site visit, 60-min slots, 10–13 and 14–17 (break 13–14)
    assert slots == ["10:00", "11:00", "12:00", "14:00", "15:00", "16:00"]
    sunday = monday + datetime.timedelta(days=6)
    assert calendar.available_slots(site, site_visit, sunday) == []


@pytest.mark.django_db
def test_holidays_leave_extra_time_notice_and_window(site, site_visit, realty):
    monday = next_monday()
    Holiday.objects.create(date=monday, name="Platform holiday")
    assert calendar.available_slots(site, site_visit, monday) == []
    tuesday = monday + datetime.timedelta(days=1)
    realty.holidays = [{"date": tuesday.isoformat(), "name": "Company offsite"}]
    realty.save()
    assert calendar.available_slots(site, site_visit, tuesday) == []
    wednesday = monday + datetime.timedelta(days=2)
    with company_context(realty.id):
        calendar.add_exception(site, "leave", at(wednesday, "10:00"), at(wednesday, "12:00"))
        calendar.add_exception(site, "extra", at(wednesday, "18:00"), at(wednesday, "19:00"))
    slots = [s.astimezone(IST).strftime("%H:%M") for s in calendar.available_slots(site, site_visit, wednesday)]
    assert slots == ["12:00", "14:00", "15:00", "16:00", "18:00"]
    far = timezone.localdate() + datetime.timedelta(days=40)
    assert calendar.available_slots(site, site_visit, far) == []  # outside the 30-day window
    now = at(monday + datetime.timedelta(days=3), "10:30")
    thursday_slots = calendar.available_slots(site, site_visit, now.date(), now=now)
    assert all(s >= now + datetime.timedelta(minutes=60) for s in thursday_slots)  # minimum notice


# ---------------------------------------------------------------- booking (CAL-05, CAL-08) + CRM link
@pytest.mark.django_db
def test_booking_updates_lead_and_blocks_double_booking(site, site_visit, realty, owner_a):
    monday = next_monday()
    with company_context(realty.id):
        lead = crm.create_lead(realty, {"name": "Visitor", "phone": "+919812345678"})
        appt = calendar.book(realty, site, "site_visit", at(monday, "11:00"), lead=lead, user=owner_a)
        assert appt.reference == "APT-000001" and appt.ends_at == at(monday, "12:00")
        lead.refresh_from_db()
        assert lead.status.key == "appointment" and "appointment_booked" in lead.events
        with pytest.raises(ValidationError, match="already booked"):
            calendar.book(realty, site, site_visit, at(monday, "11:00"))
        with pytest.raises(ValidationError, match="outside working hours"):
            calendar.book(realty, site, site_visit, at(monday, "13:00"))
        site.max_per_slot = 2
        site.save()
        calendar.book(realty, site, site_visit, at(monday, "11:00"))  # second seat allowed now
        calendar.reschedule(appt, at(monday, "15:00"), owner_a)
        appt.refresh_from_db()
        assert appt.status == "rescheduled" and appt.starts_at == at(monday, "15:00")
        with pytest.raises(ValidationError):
            calendar.set_status(appt, "cancelled", "")
        calendar.set_status(appt, "cancelled", "Customer travelling")
        assert at(monday, "15:00") in calendar.available_slots(site, site_visit, monday)


@pytest.mark.django_db(transaction=True)
def test_concurrent_requests_cannot_double_book(site, site_visit, realty):
    """Phase 3 gate: two simultaneous bookings for the last seat → exactly one succeeds."""
    start = at(next_monday(), "10:00")
    results = []
    barrier = threading.Barrier(4)

    def attempt():
        try:
            barrier.wait()
            with company_context(realty.id):  # as in a real request
                calendar.book(realty, Resource.all_companies.get(pk=site.pk), site_visit, start)
            results.append("ok")
        except ValidationError:
            results.append("refused")
        except Exception as exc:  # noqa: BLE001 — surface unexpected errors in the assertion
            results.append(repr(exc))
        finally:
            connection.close()

    threads = [threading.Thread(target=attempt) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["ok", "refused", "refused", "refused"]
    assert Appointment.all_companies.filter(resource_id=site.pk, starts_at=start).count() == 1


# ---------------------------------------------------------------- panel (CAL-01, CAL-08)
@pytest.mark.django_db
def test_calendar_panel_flow(client, owner_a, realty, site, site_visit):
    client.force_login(owner_a)
    assert client.get("/app/calendar/").status_code == 200
    monday = next_monday()
    page = client.get(f"/app/calendar/book/?resource={site.pk}&type=site_visit&date={monday}").content.decode()
    assert "10:00" in page and "13:00" not in page
    with company_context(realty.id):
        lead = crm.create_lead(realty, {"name": "Panel Lead", "phone": "+919899990000"})
    response = client.post(
        "/app/calendar/book/",
        {
            "resource": site.pk,
            "type": "site_visit",
            "date": monday,
            "start": at(monday, "14:00").isoformat(),
            "lead": lead.pk,
        },
    )
    appt = Appointment.all_companies.get(company=realty)
    assert response.url == f"/app/calendar/appointments/{appt.pk}/"
    events = client.get(
        "/app/calendar/events/",
        {"start": at(monday, "00:00").isoformat(), "end": at(monday + datetime.timedelta(days=1), "00:00").isoformat()},
    )
    assert events.json()[0]["title"].startswith("Site Visit")
    assert b"Site Visit" in client.get(f"/app/leads/{lead.pk}/").content
    client.post(f"/app/calendar/appointments/{appt.pk}/", {"status": "completed"})
    appt.refresh_from_db()
    assert appt.status == "completed"


@pytest.mark.django_db
def test_resource_settings_screen(client, owner_a, realty):
    client.force_login(owner_a)
    client.post(
        "/app/calendar/resources/new/",
        {
            "op": "save",
            "name": "Counsellor Asha",
            "kind": "user",
            "slot_minutes": 45,
            "max_per_slot": 1,
            "min_notice_minutes": 0,
            "booking_window_days": 14,
            "is_active": "on",
            "wh_mon": "09:00-12:00, 13:00-17:00",
        },
    )
    resource = Resource.all_companies.get(name="Counsellor Asha")
    assert resource.working_hours["mon"] == [["09:00", "12:00"], ["13:00", "17:00"]] and resource.slot_minutes == 45
    client.post(f"/app/calendar/resources/{resource.pk}/", {"op": "save", "name": "x", "wh_mon": "17:00-09:00"})
    resource.refresh_from_db()
    assert resource.name == "Counsellor Asha"  # invalid hours rejected
    client.post(
        f"/app/calendar/resources/{resource.pk}/",
        {"op": "exception", "kind": "leave", "starts_at": "2030-01-01T09:00", "ends_at": "2030-01-02T18:00"},
    )
    assert AvailabilityException.all_companies.filter(resource=resource).count() == 1


@pytest.mark.django_db
def test_company_without_resources_falls_back_to_business_hours(realty, site_visit):
    realty.business_hours = {
        d: {"open": "10:00", "close": "12:00", "closed": False}
        for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    }
    realty.save()
    with company_context(realty.id):
        resource = calendar.save_resource(realty, {"name": "Office", "slot_minutes": 60, "min_notice_minutes": 0})
    slots = calendar.available_slots(resource, site_visit, next_monday())
    assert [s.astimezone(IST).strftime("%H:%M") for s in slots] == ["10:00", "11:00"]


# ---------------------------------------------------------------- API + isolation
@pytest.mark.django_db
def test_calendar_api_and_isolation(client, owner_a, realty, owner_b, company_b):
    client.force_login(owner_a)
    resource = client.post(
        "/api/v1/calendar/resources/",
        {
            "name": "API site",
            "kind": "site",
            "slot_minutes": 60,
            "min_notice_minutes": 0,
            "working_hours": {"mon": [["10:00", "12:00"]]},
        },
        content_type="application/json",
    ).json()
    monday = next_monday()
    slots = client.get(
        f"/api/v1/calendar/resources/{resource['id']}/availability/", {"type": "site_visit", "date": monday}
    ).json()["slots"]
    assert len(slots) == 2
    booked = client.post(
        "/api/v1/calendar/appointments/",
        {"resource": resource["id"], "type": "site_visit", "start": slots[0]},
        content_type="application/json",
    )
    assert booked.status_code == 201, booked.content
    again = client.post(
        "/api/v1/calendar/appointments/",
        {"resource": resource["id"], "type": "site_visit", "start": slots[0]},
        content_type="application/json",
    )
    assert again.status_code == 400
    appt_id = booked.json()["id"]
    moved = client.post(
        f"/api/v1/calendar/appointments/{appt_id}/reschedule/", {"start": slots[1]}, content_type="application/json"
    )
    assert moved.json()["status"] == "rescheduled"
    config = client.get("/api/v1/calendar/config/").json()
    assert config["appointment_types"][0]["key"] == "site_visit"
    other = Client()
    other.force_login(owner_b)
    assert other.get(f"/api/v1/calendar/appointments/{appt_id}/").status_code == 404
    assert other.get("/api/v1/calendar/resources/").json() == []
