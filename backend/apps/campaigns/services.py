"""Outbound calling campaigns (M19: CAMP-01 … CAMP-06; COMP-03 … COMP-05).

A campaign is one AI Employee calling a lead list (a lead-list filter, a saved view, a CSV / Excel file or leads
picked in the lead list) within a schedule (dates, weekdays, time windows) and limits (calls at the same time, calls
per day, attempts per lead). A company admin approves it before the first call (COMP-05).

The scheduler (`dial_due_calls`, every minute) runs `dispatch()`. Before every dial the voice service checks the
calling hours, opt-out / Do-not-call, consent, attempt caps, the daily cap and the plan's usage (CAMP-03); per-lead
blocks skip that lead with the reason, company-wide blocks wait for the next run. Results come back from the call
(`after_call`: connected, retries) and from the conversation analysis (`after_conversation`: qualified, hot,
appointment, follow-ups). Defaults and limits are System Settings → Campaigns, the company's calling rules and the plan.
"""

import datetime as dt
import logging
import re

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.http import QueryDict
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.agents.models import AIEmployee
from apps.agents.tools import company_tz
from apps.audit.services import record
from apps.billing import limits
from apps.crm.models import ConsentRecord, Lead, SavedView
from apps.platform_config.services import get as setting
from apps.tenancy.context import company_context, platform_context

from .models import RETRY_OUTCOMES, WEEKDAYS, Campaign, CampaignMember

log = logging.getLogger(__name__)
HM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
LABELS = {k for k, _ in Lead.SCORE_LABELS}


# ------------------------------------------------------------------ settings → defaults for a new campaign
def defaults(company):
    from apps.voice.services import policy

    rules = policy(company)
    return {
        "max_attempts": min(setting("campaigns.default_max_attempts"), rules["max_attempts_per_lead"]),
        "retry_gap_minutes": setting("campaigns.default_retry_gap_minutes"),
        "retry_outcomes": list(setting("campaigns.default_retry_outcomes")),
        "max_concurrent": setting("campaigns.default_max_concurrent"),
        "daily_limit": min(setting("campaigns.default_daily_limit"), rules["max_calls_per_day"]),
        "follow_up_after_days": 2,
        "days": [d for d, _ in WEEKDAYS[:6]],
        "windows": [[rules["window_start"], rules["window_end"]]],
    }


# ------------------------------------------------------------------ create / edit (CAMP-01)
def _int(data, key, low, high, label):
    try:
        value = int(data.get(key))
    except (TypeError, ValueError):
        raise ValidationError(f"{label}: enter a whole number.") from None
    if not low <= value <= high:
        raise ValidationError(f"{label}: between {low} and {high}.")
    return value


def _list(value):
    if isinstance(value, str):
        return [v.strip() for v in re.split(r"[,\n]", value) if v.strip()]
    return [str(v).strip() for v in value or [] if str(v).strip()]


def parse_windows(value):
    """'10:00-13:00, 14:00-17:00' or [["10:00", "13:00"], …] → sorted pairs."""
    if isinstance(value, str):
        value = [part.split("-") for part in _list(value)]
    out = []
    for pair in value or []:
        if len(pair) != 2 or not all(HM.match(str(x).strip()) for x in pair):
            raise ValidationError("Time windows look like 10:00-13:00 (24-hour clock).")
        start, end = (str(x).strip() for x in pair)
        if start >= end:
            raise ValidationError(f"The window {start}-{end} must end after it starts.")
        out.append([start, end])
    return sorted(out)


def team_phones(company):
    from apps.crm.services import members

    return {u.phone: u for u in members(company) if u.phone}


def clean(company, data, campaign=None):
    """Validated field values; every limit comes from the company's calling rules, the plan or System Settings."""
    from apps.catalog.models import CatalogCollection
    from apps.voice.services import clean_e164, policy

    rules = policy(company)
    out = {}
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValidationError("Give the campaign a name.")
    out["name"], out["description"] = name[:120], str(data.get("description") or "").strip()
    out["brief"] = str(data.get("brief") or "").strip()[:4000]
    employee = AIEmployee.objects.filter(company=company, pk=_uuid(data.get("employee"))).first()
    if not employee or employee.status == AIEmployee.ARCHIVED:
        raise ValidationError("Choose the AI Employee who makes the calls.")
    out["employee"] = employee
    out["source"] = data.get("source") or "filter"
    if out["source"] not in dict(Campaign.SOURCES):
        raise ValidationError("Choose where the lead list comes from.")
    out["filter_params"] = str(data.get("filter_params") or "").lstrip("?")[:2000]
    out["saved_view"] = None
    if out["source"] == "view":
        out["saved_view"] = SavedView.objects.filter(company=company, pk=_uuid(data.get("saved_view"))).first()
        if not out["saved_view"]:
            raise ValidationError("Choose a saved view.")
    out["starts_on"] = parse_date(str(data.get("starts_on") or "")) if data.get("starts_on") else None
    out["ends_on"] = parse_date(str(data.get("ends_on") or "")) if data.get("ends_on") else None
    if out["starts_on"] and out["ends_on"] and out["ends_on"] < out["starts_on"]:
        raise ValidationError("The end date is before the start date.")
    days = _list(data.get("days"))
    if any(d not in dict(WEEKDAYS) for d in days):
        raise ValidationError("Unknown weekday.")
    out["days"] = [d for d, _ in WEEKDAYS if d in days]
    out["windows"] = parse_windows(data.get("windows"))
    for start, end in out["windows"]:
        if start < rules["window_start"] or end > rules["window_end"]:
            raise ValidationError(
                f"Windows must stay within your calling hours {rules['window_start']}–{rules['window_end']} "
                "(Settings → Calling)."
            )
    out["max_attempts"] = _int(data, "max_attempts", 1, rules["max_attempts_per_lead"], "Attempts per lead")
    out["retry_gap_minutes"] = _int(data, "retry_gap_minutes", 5, 10080, "Gap between attempts (minutes)")
    out["retry_outcomes"] = _list(data.get("retry_outcomes"))
    if any(o not in dict(RETRY_OUTCOMES) for o in out["retry_outcomes"]):
        raise ValidationError("Unknown outcome to call again.")
    out["collection"] = None
    if data.get("collection"):
        out["collection"] = CatalogCollection.objects.filter(company=company, pk=_uuid(data["collection"])).first()
        if not out["collection"]:
            raise ValidationError("Unknown collection.")
    out["whatsapp_after_call"] = data.get("whatsapp_after_call") in (True, "on", "true", "1", 1)
    out["follow_up_labels"] = [x for x in _list(data.get("follow_up_labels")) if x in LABELS]
    out["follow_up_after_days"] = _int(data, "follow_up_after_days", 1, 60, "Follow-up call after (days)")
    concurrent = limits.limit(company, "concurrent_calls")
    out["max_concurrent"] = _int(data, "max_concurrent", 1, concurrent or 100, "Calls at the same time")
    out["daily_limit"] = _int(data, "daily_limit", 1, rules["max_calls_per_day"], "Calls per day")
    out["test_mode"] = data.get("test_mode") in (True, "on", "true", "1", 1)
    numbers = []
    for raw in _list(data.get("test_numbers")):
        try:
            numbers.append(clean_e164(raw))
        except ValidationError:
            raise ValidationError(f"Test number {raw!r}: use +91… format.") from None
    numbers = list(dict.fromkeys(numbers))
    if out["test_mode"]:
        team = team_phones(company)
        if not numbers:
            raise ValidationError("Test mode: add at least one internal test number.")
        if len(numbers) > setting("campaigns.max_test_numbers"):
            raise ValidationError(f"Test mode: at most {setting('campaigns.max_test_numbers')} numbers.")
        outside = [n for n in numbers if n not in team]
        if outside:
            raise ValidationError(
                f"Test numbers must be your team's own numbers (Team / Profile): {', '.join(outside)} is not."
            )
    out["test_numbers"] = numbers
    return out


def _uuid(value):
    import uuid

    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def save_campaign(company, data, campaign=None, user=None, request=None):
    if campaign and not campaign.editable:
        raise ValidationError("Pause the campaign before changing it.")
    values = clean(company, data, campaign)
    creating = campaign is None
    campaign = campaign or Campaign(company=company, created_by=user if user and user.is_authenticated else None)
    if not creating and campaign.status != Campaign.DRAFT and campaign.test_mode != values["test_mode"]:
        raise ValidationError("Test mode can only be changed while the campaign is a draft.")
    for key, value in values.items():
        setattr(campaign, key, value)
    campaign.save()
    record(request, "campaign.create" if creating else "campaign.update", "campaign", campaign.pk, company=company)
    return campaign


# ------------------------------------------------------------------ the lead list
def _member_for_lead(campaign, lead):
    return CampaignMember(
        company_id=campaign.company_id, campaign=campaign, lead=lead, phone=lead.phone, name=lead.name[:150]
    )


def add_leads(campaign, leads, user=None, request=None):
    """Leads join the list (no phone or already in it → not added). → (added, without phone)."""
    if campaign.status != Campaign.DRAFT:
        raise ValidationError("Leads can be added while the campaign is a draft.")
    if campaign.test_mode:
        raise ValidationError("A test-mode campaign calls only its internal test numbers.")
    have = set(campaign.members.values_list("phone", flat=True))
    room = setting("campaigns.max_leads") - len(have)
    rows, no_phone = [], 0
    for lead in leads:
        if not lead.phone:
            no_phone += 1
            continue
        if lead.phone in have or lead.deleted_at:
            continue
        have.add(lead.phone)
        rows.append(_member_for_lead(campaign, lead))
    if len(rows) > room:
        raise ValidationError(f"A campaign can have at most {setting('campaigns.max_leads')} leads.")
    CampaignMember.objects.bulk_create(rows, batch_size=1000)
    record(request, "campaign.add_leads", "campaign", campaign.pk, {"added": len(rows)}, user, company=campaign.company)
    return len(rows), no_phone


def build_list(campaign, request, upload=None):
    """Draft only: (re)build the list from the campaign's source. → (added, without phone)."""
    from apps.crm import filters, imports

    if campaign.status != Campaign.DRAFT:
        raise ValidationError("The list can be rebuilt while the campaign is a draft.")
    if campaign.test_mode:
        campaign.members.all().delete()
        team = team_phones(campaign.company)
        CampaignMember.objects.bulk_create(
            [
                CampaignMember(
                    company_id=campaign.company_id,
                    campaign=campaign,
                    phone=n,
                    name=(team[n].full_name or team[n].email)[:150] if n in team else "",
                )
                for n in campaign.test_numbers
            ]
        )
        return len(campaign.test_numbers), 0
    if campaign.source == "csv":
        if upload is None:
            raise ValidationError("Choose the CSV or Excel file.")
        imp = imports.start(campaign.company, upload, request.user, request)
        imp = imports.run(imp, imp.mapping, "update", request.user, request)
        campaign.csv_import = imp
        campaign.save(update_fields=["csv_import", "updated_at"])
        leads = Lead.objects.filter(pk__in=imp.lead_ids)
    elif campaign.source == "leads":
        raise ValidationError("Pick the leads in the lead list and use “Add to campaign”.")
    else:
        params = campaign.saved_view.params if campaign.source == "view" and campaign.saved_view else ""
        qs, _ = filters.apply(request, QueryDict(params or campaign.filter_params))
        leads = qs
    campaign.members.all().delete()
    return add_leads(campaign, leads.filter(deleted_at__isnull=True))


# ------------------------------------------------------------------ approval and controls (CAMP-02, COMP-05)
def _people(campaign, perm):
    from apps.notifications import alerts

    return alerts.people_with(campaign.company, perm)


def request_approval(campaign, user=None, request=None):
    from apps.notifications import alerts

    if campaign.status != Campaign.DRAFT:
        raise ValidationError("Only a draft waits for approval.")
    if not campaign.members.exists():
        raise ValidationError("The lead list is empty: build it first.")
    campaign.approval_requested_by, campaign.approval_requested_at = user, timezone.now()
    campaign.save(update_fields=["approval_requested_by", "approval_requested_at", "updated_at"])
    alerts.notify(
        campaign.company,
        [p for p in _people(campaign, "campaigns.approve") if not user or p.pk != user.pk],
        "campaign",
        f"Approve the campaign “{campaign.name}”",
        f"{campaign.members.count()} leads · {campaign.employee.name}",
        reverse("panel:campaign", args=[campaign.pk]),
        data={"campaign": str(campaign.pk), "event": "approval"},
    )
    record(request, "campaign.request_approval", "campaign", campaign.pk, company=campaign.company)
    return campaign


def check_ready(campaign):
    from apps.billing import access
    from apps.voice.services import number_for

    reason = access.blocked(campaign.company, "campaigns")
    if reason:
        raise ValidationError(reason)
    employee = campaign.employee
    if employee.status != AIEmployee.ACTIVE and not campaign.test_mode:
        raise ValidationError(f"{employee.name} is not active.")
    if not number_for(employee, "outbound"):
        raise ValidationError(f"Connect a phone number for outbound calls to {employee.name} first.")
    if not campaign.members.filter(status=CampaignMember.PENDING).exists():
        raise ValidationError("Nobody left to call in the list.")
    active = Campaign.objects.filter(company=campaign.company, status__in=Campaign.ACTIVE).exclude(pk=campaign.pk)
    limits.check(campaign.company, "campaigns", active.count(), label="active campaigns")


def approve(campaign, user, request=None):
    """COMP-05: a company admin approves; the campaign is scheduled or starts at once."""
    if campaign.status != Campaign.DRAFT:
        raise ValidationError("Only a draft can be approved.")
    check_ready(campaign)
    today = timezone.localtime(timezone.now(), company_tz(campaign.company)).date()
    campaign.approved_by, campaign.approved_at = user, timezone.now()
    if campaign.starts_on and campaign.starts_on > today:
        campaign.status = Campaign.SCHEDULED
    else:
        campaign.status, campaign.started_at = Campaign.RUNNING, timezone.now()
    campaign.save()
    record(
        request,
        "campaign.approve",
        "campaign",
        campaign.pk,
        {"status": campaign.status},
        user,
        company=campaign.company,
    )
    return campaign


def pause(campaign, user=None, request=None):
    if campaign.status not in (Campaign.RUNNING, Campaign.SCHEDULED):
        raise ValidationError("Only a running or scheduled campaign can be paused.")
    campaign.status = Campaign.PAUSED
    campaign.save(update_fields=["status", "updated_at"])
    record(request, "campaign.pause", "campaign", campaign.pk, company=campaign.company)
    return campaign


def resume(campaign, user=None, request=None):
    if campaign.status != Campaign.PAUSED:
        raise ValidationError("Only a paused campaign can be resumed.")
    check_ready(campaign)
    campaign.status = Campaign.RUNNING if campaign.started_at else Campaign.SCHEDULED
    campaign.save(update_fields=["status", "updated_at"])
    record(request, "campaign.resume", "campaign", campaign.pk, company=campaign.company)
    return campaign


def stop(campaign, reason="", user=None, request=None):
    if campaign.status not in Campaign.ACTIVE:
        raise ValidationError("Only a scheduled, running or paused campaign can be stopped.")
    finish(campaign, Campaign.STOPPED, reason or "Stopped by the team")
    record(request, "campaign.stop", "campaign", campaign.pk, {"reason": reason}, user, company=campaign.company)
    return campaign


def finish(campaign, status=Campaign.COMPLETED, reason=""):
    """Completed (everyone done / end date) or stopped: leads not called are skipped; the team is told (CP-03)."""
    from apps.notifications import alerts

    campaign.members.filter(status=CampaignMember.PENDING).update(
        status=CampaignMember.SKIPPED, skip_reason=reason or "The campaign ended", updated_at=timezone.now()
    )
    campaign.status, campaign.finished_at, campaign.stop_reason = status, timezone.now(), reason[:255]
    campaign.save(update_fields=["status", "finished_at", "stop_reason", "updated_at"])
    numbers = stats(campaign)
    people = {u.pk: u for u in (campaign.created_by, campaign.approved_by, campaign.approval_requested_by) if u}
    word = "finished" if status == Campaign.COMPLETED else "stopped"
    alerts.notify(
        campaign.company,
        people.values(),
        "campaign",
        f"Campaign {word}: {campaign.name}",
        f"{numbers['connected']} connected · {numbers['qualified']} qualified · {numbers['hot']} hot · "
        f"{numbers['appointments']} appointments of {numbers['total']}",
        reverse("panel:campaign", args=[campaign.pk]),
        email=("alerts/campaign_finished", {"campaign_name": campaign.name, **numbers}),
        data={"campaign": str(campaign.pk), "event": status},
    )
    return campaign


# ------------------------------------------------------------------ progress (CAMP-04) and export (CAMP-05)
def stats(campaign):
    M = CampaignMember
    data = campaign.members.aggregate(
        total=Count("pk"),
        pending=Count("pk", filter=Q(status=M.PENDING)),
        calling=Count("pk", filter=Q(status=M.CALLING)),
        dialled=Count("pk", filter=Q(attempts__gt=0)),
        connected=Count("pk", filter=Q(connected=True)),
        qualified=Count("pk", filter=Q(qualified=True)),
        hot=Count("pk", filter=Q(hot=True)),
        appointments=Count("pk", filter=Q(appointment=True)),
        failed=Count("pk", filter=Q(status=M.FAILED)),
        skipped=Count("pk", filter=Q(status=M.SKIPPED)),
        done=Count("pk", filter=Q(status__in=(M.DONE, M.FAILED, M.SKIPPED))),
    )
    data["percent"] = round(data["done"] * 100 / data["total"]) if data["total"] else 0
    return data


STAT_LABELS = [
    ("total", "Total"),
    ("pending", "To call"),
    ("dialled", "Dialled"),
    ("connected", "Connected"),
    ("qualified", "Qualified"),
    ("hot", "Hot"),
    ("appointments", "Appointments"),
    ("failed", "Not reached"),
    ("skipped", "Skipped"),
]

EXPORT_HEADER = [
    "Lead ID",
    "Name",
    "Phone",
    "Result",
    "Attempts",
    "Last call",
    "Last call outcome",
    "Connected",
    "Qualified",
    "Hot",
    "Appointment",
    "Reason skipped",
    "Summary",
]


def export(campaign, fmt="csv", user=None, request=None):
    tz = company_tz(campaign.company)
    rows = [EXPORT_HEADER]
    yes = {True: "Yes", False: "No"}
    for m in campaign.members.select_related("lead").order_by("created_at"):
        rows.append(
            [
                m.lead.reference if m.lead_id else "",
                m.name,
                m.phone,
                m.get_status_display(),
                m.attempts,
                m.last_called_at.astimezone(tz).strftime("%d %b %Y %H:%M") if m.last_called_at else "",
                m.outcome.replace("_", " "),
                yes[m.connected],
                yes[m.qualified],
                yes[m.hot],
                yes[m.appointment],
                m.skip_reason,
                m.summary,
            ]
        )
    numbers = stats(campaign)
    rows += [[], ["Summary"], *[[k.replace("_", " ").capitalize(), v] for k, v in numbers.items()]]
    from apps.core.tabular import write_table

    record(
        request,
        "campaign.export",
        "campaign",
        campaign.pk,
        {"format": fmt, "rows": numbers["total"]},
        user,
        company=campaign.company,
        category="security",
    )
    return write_table(rows, "xlsx" if fmt == "xlsx" else "csv", campaign.name)


# ------------------------------------------------------------------ dialling (scheduler) — CAMP-03
def _consent_ok(lead):
    """COMP-05: outbound only to leads with a valid source or consent (or, by setting, a recorded opt-in)."""
    last = (
        ConsentRecord.objects.filter(company_id=lead.company_id, lead=lead, channel__in=("voice", "all"))
        .order_by("-created_at")
        .first()
    )
    opted_in = bool(last and last.action == "opt_in") or lead.consent_status == "opted_in"
    if setting("campaigns.require_opt_in"):
        return opted_in
    return opted_in or bool(lead.source_id)


def in_schedule(campaign, now):
    local = timezone.localtime(now, company_tz(campaign.company))
    if campaign.days and WEEKDAYS[local.weekday()][0] not in campaign.days:
        return False
    hm = local.strftime("%H:%M")
    return not campaign.windows or any(start <= hm < end for start, end in campaign.windows)


def _wait(campaign, reason):
    if campaign.waiting_reason != reason[:255]:
        campaign.waiting_reason = reason[:255]
        campaign.save(update_fields=["waiting_reason", "updated_at"])


def _dial(campaign, member, now):
    """→ True when a call went out; False when the company cannot call now (stop this run)."""
    from apps.voice import services as voice

    member.attempts += 1
    member.status, member.last_called_at, member.next_attempt_at = CampaignMember.CALLING, now, None
    member.save(update_fields=["attempts", "status", "last_called_at", "next_attempt_at", "updated_at"])
    try:
        if campaign.test_mode:
            call = voice.place_test_call(campaign.employee, member.phone, campaign_member=member)
        else:
            call = voice.place_call(campaign.employee, member.lead, "campaign", campaign_member=member, now=now)
    except voice.CallBlocked as exc:
        member.attempts -= 1
        if exc.lead and exc.retry_at:
            member.status, member.next_attempt_at = CampaignMember.PENDING, exc.retry_at
        elif exc.lead:
            member.status, member.skip_reason = CampaignMember.SKIPPED, exc.messages[0][:255]
        else:  # the company's limits / hours / number: wait and try again on a later run
            member.status = CampaignMember.PENDING
            member.next_attempt_at = exc.retry_at
            member.save(update_fields=["attempts", "status", "next_attempt_at", "updated_at"])
            _wait(campaign, exc.messages[0])
            return False
        member.save(update_fields=["attempts", "status", "next_attempt_at", "skip_reason", "updated_at"])
        return True
    except ValidationError as exc:  # test mode: plan limits, number
        member.attempts -= 1
        member.status = CampaignMember.PENDING
        member.save(update_fields=["attempts", "status", "updated_at"])
        _wait(campaign, exc.messages[0])
        return False
    CampaignMember.objects.filter(pk=member.pk, last_call__isnull=True).update(last_call=call)
    return True


def dispatch_one(campaign, now=None):
    """One scheduler run for one campaign. → calls placed."""
    from apps.voice.models import Call
    from apps.voice.services import _day_start

    now = now or timezone.now()
    company = campaign.company
    today = timezone.localtime(now, company_tz(company)).date()
    if company.is_suspended:
        return 0
    if campaign.status == Campaign.SCHEDULED and (not campaign.starts_on or campaign.starts_on <= today):
        campaign.status, campaign.started_at = Campaign.RUNNING, now
        campaign.save(update_fields=["status", "started_at", "updated_at"])
    if campaign.status != Campaign.RUNNING:
        return 0
    if campaign.ends_on and today > campaign.ends_on:
        finish(campaign, Campaign.COMPLETED, "The campaign's end date passed")
        return 0
    campaign.last_run_at = now
    campaign.save(update_fields=["last_run_at", "updated_at"])
    if not in_schedule(campaign, now):
        _wait(campaign, "Outside the campaign's days / time windows")
        return 0
    members = campaign.members
    slots = campaign.max_concurrent - members.filter(status=CampaignMember.CALLING).count()
    calls_today = Call.objects.filter(campaign_member__campaign=campaign, queued_at__gte=_day_start(company, now))
    room = min(slots, campaign.daily_limit - calls_today.count())
    if room <= 0:
        _wait(campaign, "Daily limit reached" if slots > 0 else "")
        return 0
    due = members.filter(status=CampaignMember.PENDING).filter(
        Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now)
    )
    placed = 0
    for member in due.select_related("lead").order_by("next_attempt_at", "created_at")[: room * 5]:
        if placed >= room:
            break
        if not campaign.test_mode:
            lead = member.lead
            if lead is None or lead.deleted_at:
                member.status, member.skip_reason = CampaignMember.SKIPPED, "The lead was deleted"
                member.save(update_fields=["status", "skip_reason", "updated_at"])
                continue
            if not _consent_ok(lead):
                member.status = CampaignMember.SKIPPED
                member.skip_reason = "No lead source or consent to be called"
                member.save(update_fields=["status", "skip_reason", "updated_at"])
                continue
        if not _dial(campaign, member, now):
            break
        member.refresh_from_db()
        placed += int(member.status == CampaignMember.CALLING or member.attempts > 0)
    if placed:
        _wait(campaign, "")
    check_done(campaign)
    return placed


def dispatch(now=None):
    """Scheduler (cron, every minute, with dial_due_calls)."""
    now = now or timezone.now()
    with platform_context():
        due = list(
            Campaign.all_companies.filter(status__in=(Campaign.SCHEDULED, Campaign.RUNNING)).values_list(
                "pk", "company_id"
            )
        )
    placed = 0
    for pk, company_id in due:
        try:
            with company_context(company_id):
                campaign = Campaign.objects.select_related("company", "employee").get(pk=pk)
                placed += dispatch_one(campaign, now)
        except Exception:  # noqa: BLE001 — one company's campaign never stops the others
            log.exception("campaign %s dispatch failed", pk)
    return placed


def check_done(campaign):
    if (
        campaign.status == Campaign.RUNNING
        and not campaign.members.filter(status__in=(CampaignMember.PENDING, CampaignMember.CALLING)).exists()
    ):
        finish(campaign, Campaign.COMPLETED)


# ------------------------------------------------------------------ results (from the voice service and the AI)
@transaction.atomic
def after_call(call):
    """A campaign call reached its final state: connected?, call again (campaign retry rules) or done."""
    from apps.voice.models import Call

    member = CampaignMember.objects.select_for_update().select_related("campaign").get(pk=call.campaign_member_id)
    campaign = member.campaign
    member.last_call, member.outcome = call, call.status
    member.connected = member.connected or bool(call.answered_at and call.status != Call.VOICEMAIL)
    retry = (
        call.status in (campaign.retry_outcomes or [])
        and member.attempts < campaign.max_attempts
        and campaign.status in (Campaign.RUNNING, Campaign.PAUSED, Campaign.SCHEDULED)
        and not member.connected
    )
    if retry:
        member.status = CampaignMember.PENDING
        member.next_attempt_at = timezone.now() + dt.timedelta(minutes=campaign.retry_gap_minutes)
    else:
        member.status = CampaignMember.DONE if member.connected else CampaignMember.FAILED
    member.save()
    check_done(campaign)
    return member


def after_conversation(conv):
    """CAMP-04 results and CAMP-01 follow-up rules once the call's conversation is analysed."""
    call = getattr(conv, "call", None)
    if call is None or not call.campaign_member_id:
        return None
    member = CampaignMember.objects.select_related("campaign", "lead").get(pk=call.campaign_member_id)
    campaign, lead = member.campaign, member.lead
    member.summary = conv.summary
    if lead and not conv.is_test:
        from apps.scheduling.models import Appointment

        lead.refresh_from_db()
        member.hot = lead.score_label == Lead.HOT
        member.qualified = lead.score_label in setting("campaigns.qualified_labels")
        member.appointment = (
            member.appointment or Appointment.objects.filter(lead=lead, created_at__gte=call.queued_at).exists()
        )
        _follow_up(campaign, lead, conv)
    member.save(update_fields=["summary", "hot", "qualified", "appointment", "updated_at"])
    return member


def _follow_up(campaign, lead, conv):
    from apps.voice.models import Call
    from apps.voice.services import schedule_follow_up

    if campaign.whatsapp_after_call and not (conv.employee.rules or {}).get("whatsapp_after_call"):
        from apps.crm import services as crm
        from apps.whatsapp import services as whatsapp

        template = whatsapp.find_template(conv.company, "lead_follow_up", conv.language or lead.preferred_language)
        try:
            if not template:
                raise ValidationError("No approved WhatsApp follow-up template.")
            whatsapp.send_template(template, lead, {"employee": conv.employee})
        except ValidationError as exc:
            crm.log(lead, "whatsapp", f"Campaign WhatsApp follow-up not sent: {exc.messages[0]}", None, "system")
    if lead.score_label in (campaign.follow_up_labels or []):
        queued = Call.objects.filter(lead=lead, status=Call.QUEUED, provider_call_id="", reason="follow_up")
        if not queued.exists():
            when = timezone.now() + dt.timedelta(days=campaign.follow_up_after_days)
            schedule_follow_up(campaign.employee, lead, when)


# ------------------------------------------------------------------ what the AI is told on a campaign call
def prompt_layer(conv):
    """CAMP-01: the campaign's brief and its property / product collection, for the system prompt."""
    call = getattr(conv, "call", None)
    member = call.campaign_member if call and call.campaign_member_id else None
    if member is None:
        return ""
    campaign = member.campaign
    lines = [f"## This is an outbound call of the campaign “{campaign.name}”"]
    if campaign.brief:
        lines.append(campaign.brief)
    if campaign.collection_id:
        from apps.catalog import services as catalog

        items = catalog.collection_items(campaign.collection)[:10]
        if items:
            lines.append("Offer these when they fit what the customer wants (search the catalogue for details):")
            lines += [f"- {i.title}" for i in items]
    return "\n".join(lines)
