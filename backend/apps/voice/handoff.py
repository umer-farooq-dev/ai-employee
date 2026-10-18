"""Human handoff (M17: HO-01 … HO-05; TOOL-08 / VOICE-11 transfer_call).

1 trigger   customer asks for a person (the AI calls transfer_call), knowledge gap, hot lead, keywords, repeated
            failure (runtime) — rules per AI Employee, thresholds in System Settings → Human handoff
2 routing   assigned agent → the AI Employee's transfer team (round robin) → any available agent; only members with
            "Receive handoffs" permission, availability Online, not in an appointment right now (calendar)
3 notify    screen pop in the panel (polled) + e-mail with summary, requirement and score
4 connect   voice: warm transfer (the agent hears the summary before the caller is connected); cold when the
            telephony vendor cannot whisper
5 no answer next agent after the ring time; nobody → message to the customer, callback task, lead flagged
6 record    Handoff row (reason, agent, time to answer, outcome), lead timeline, call / conversation status
"""

import logging
from datetime import UTC, datetime, timedelta

from django.db.models import Count, Max
from django.utils import timezone

from apps.agents.models import Conversation
from apps.audit.services import record
from apps.crm import services as crm
from apps.industries import fields as field_engine
from apps.industries import services as templates
from apps.notifications import services as notify
from apps.platform_config.services import get as setting
from apps.rbac.services import has_perm
from apps.scheduling.models import Appointment
from apps.tenancy.context import company_context, platform_context

from . import services, telephony
from .models import Call, Handoff

log = logging.getLogger(__name__)


def _busy(company, user, now):
    """In an appointment right now (own or on a calendar that belongs to the user)."""
    active = Appointment.objects.filter(
        company=company, status__in=Appointment.ACTIVE, starts_at__lte=now, ends_at__gt=now
    )
    return active.filter(assigned_user=user).exists() or active.filter(resource__user=user).exists()


def eligible(company, user, channel, now=None):
    now = now or timezone.now()
    return (
        user.is_active
        and user.availability == "online"
        and has_perm(user, "handoffs.receive", company)
        and (channel != "voice" or bool(user.phone))
        and not Handoff.objects.filter(
            company=company, assigned_user=user, status__in=[Handoff.RINGING, Handoff.ACCEPTED]
        ).exists()
        and not _busy(company, user, now)
    )


def route(company, employee, lead, channel):
    """HO-02 → candidate users in order (eligible only)."""
    members = {str(u.pk): u for u in crm.members(company)}
    ordered = []
    if lead and lead.assigned_user_id and str(lead.assigned_user_id) in members:
        ordered.append(str(lead.assigned_user_id))
    team = [str(i) for i in (employee.rules or {}).get("transfer_user_ids") or [] if str(i) in members]
    if team:  # round robin: the team member who got a handoff longest ago (or never) first
        last = {
            str(uid): at
            for uid, at in Handoff.objects.filter(company=company, assigned_user_id__in=team)
            .values("assigned_user_id")
            .annotate(at=Max("created_at"))
            .values_list("assigned_user_id", "at")
        }
        never = datetime.min.replace(tzinfo=UTC)
        ordered += sorted(team, key=lambda uid: last.get(uid) or never)
    load = {
        str(uid): n
        for uid, n in Handoff.objects.filter(company=company, created_at__gte=timezone.now() - timedelta(days=1))
        .values("assigned_user_id")
        .annotate(n=Count("id"))
        .values_list("assigned_user_id", "n")
    }
    ordered += sorted(members, key=lambda uid: load.get(uid, 0))  # any available agent, least busy today first
    seen, out = set(), []
    for uid in ordered:
        if uid in seen:
            continue
        seen.add(uid)
        if eligible(company, members[uid], channel):
            out.append(uid)
    return out[: setting("handoff.max_agents")]


def agent_summary(conv, reason_label):
    """HO-03: what the agent needs at a glance (no AI call — instant)."""
    lead = conv.lead
    parts = []
    if lead:
        defs = {d.key: d for d in templates.fields_for(conv.company, "lead")}
        wants = ", ".join(field_engine.display(defs[k], v) for k, v in lead.custom.items() if k in defs and v)
        score = f"{lead.get_score_label_display()} {lead.score_value}" if lead.score_label else ""
        parts.append(f"{lead.name or 'New customer'} ({lead.reference}){', ' + score if score else ''}.")
        if wants:
            parts.append(f"Looking for: {wants}.")
    last = conv.messages.filter(role="customer").order_by("-created_at").first()
    if last:
        parts.append(f'Last said: "{last.content[:160]}".')
    parts.append(f"Reason: {reason_label}.")
    return " ".join(parts)


def request(conv, reason="customer_request", detail="", call=None):
    """Start a handoff for a live conversation → Handoff (ringing the first agent, or no_agent)."""
    reason = reason if reason in dict(Handoff.REASONS) else "ai_decision"
    candidates = route(conv.company, conv.employee, conv.lead, conv.channel if not conv.is_test else "voice")
    handoff = Handoff.objects.create(
        company=conv.company,
        conversation=conv,
        call=call,
        lead=conv.lead,
        channel="voice" if call else conv.channel,
        mode=(
            "warm" if (call is None or call.provider is None or call.provider.vendor in ("twilio", "plivo")) else "cold"
        ),
        reason=reason,
        detail=str(detail or "")[:300],
        summary=agent_summary(conv, dict(Handoff.REASONS)[reason]),
        candidates=candidates,
    )
    conv.state = {**(conv.state or {}), "transfer": None, "handoff": str(handoff.pk)}
    conv.save(update_fields=["state", "updated_at"])
    if conv.lead_id:
        crm.log(
            conv.lead,
            "handoff",
            f"AI {conv.employee.name} handed over: {handoff.get_reason_display()}",
            actor_type="ai",
            handoff=str(handoff.pk),
        )
    if call:
        call.transfer_status = "requested"
        call.save(update_fields=["transfer_status", "updated_at"])
    return next_agent(handoff)


def next_agent(handoff):
    """Ring the next candidate, or finish with no agent (HO-04)."""
    remaining = [u for u in handoff.candidates if u not in handoff.tried_user_ids]
    if not remaining:
        return no_agent(handoff)
    uid = remaining[0]
    handoff.tried_user_ids = [*handoff.tried_user_ids, uid]
    handoff.assigned_user_id = uid
    handoff.status = Handoff.RINGING
    handoff.save(update_fields=["tried_user_ids", "assigned_user", "status", "updated_at"])
    _alert(handoff)
    return handoff


def _alert(handoff):
    """HO-03 e-mail alert (the panel shows a screen pop from the live list)."""
    user = handoff.assigned_user
    if not user or not user.email:
        return
    notify.send(
        "handoff/alert",
        [user.email],
        {
            "name": user.full_name or user.email,
            "employee": handoff.conversation.employee.name,
            "reason": handoff.get_reason_display(),
            "summary": handoff.summary,
            "lead": handoff.lead.reference if handoff.lead else "",
        },
    )


def no_agent(handoff):
    """HO-04: tell the customer (caller hears the language's no-agent phrase), callback task, lead flagged."""
    handoff.status, handoff.assigned_user, handoff.ended_at = Handoff.NO_AGENT, None, timezone.now()
    lead = handoff.lead
    if lead:
        task = crm.create_task(
            handoff.company,
            {
                "title": f"Call back — no agent was free ({handoff.get_reason_display()})",
                "notes": handoff.summary,
                "due_at": timezone.now() + timedelta(minutes=setting("handoff.callback_minutes")),
                "lead": lead,
                "type": "callback",
            },
        )
        handoff.callback_task = task
        lead.next_action = "Call back: the customer asked for a person and no agent was free"
        lead.save(update_fields=["next_action", "updated_at"])
        crm.log(lead, "handoff", "No agent was available — callback task created", actor_type="system")
    handoff.save()
    if handoff.call_id:
        Call.objects.filter(pk=handoff.call_id).update(transfer_status="no_agent")
    return handoff


def answered(handoff):
    handoff.status, handoff.accepted_at = Handoff.ACCEPTED, handoff.accepted_at or timezone.now()
    handoff.save(update_fields=["status", "accepted_at", "updated_at"])
    if handoff.call_id:
        call = Call.objects.get(pk=handoff.call_id)
        services.transition(call, Call.TRANSFERRED, f"agent {handoff.assigned_user_id}")
        call.transfer_status = "completed"
        call.save(update_fields=["transfer_status", "updated_at"])
    if handoff.lead_id:
        who = handoff.assigned_user.full_name or handoff.assigned_user.email
        crm.log(handoff.lead, "handoff", f"{who} took over after {handoff.seconds_to_answer}s", actor_type="system")
    return handoff


def missed(handoff):
    handoff.status = Handoff.MISSED
    handoff.save(update_fields=["status", "updated_at"])
    return next_agent(handoff)


def accept(handoff, user, request=None):
    """The agent confirms in the panel (screen pop) — for chat handoffs and when a call reached the agent."""
    if str(handoff.assigned_user_id) != str(user.pk):
        from django.core.exceptions import ValidationError

        raise ValidationError("This handoff is not assigned to you.")
    if handoff.status in (Handoff.RINGING, Handoff.PENDING):
        answered(handoff)
    handoff.seen_at = handoff.seen_at or timezone.now()
    handoff.save(update_fields=["seen_at", "updated_at"])
    record(request, "handoff.accept", "handoff", str(handoff.pk), user=user, company=handoff.company)
    return handoff


def finish(handoff, outcome=Handoff.COMPLETED):
    if handoff.status not in (Handoff.NO_AGENT, Handoff.COMPLETED, Handoff.FAILED):
        handoff.status, handoff.ended_at = outcome, timezone.now()
        handoff.save(update_fields=["status", "ended_at", "updated_at"])
    return handoff


def live_for(user, company):
    """Screen pop: handoffs ringing / just accepted for this agent."""
    return Handoff.objects.filter(
        company=company, assigned_user=user, status__in=[Handoff.RINGING, Handoff.ACCEPTED], ended_at__isnull=True
    ).select_related("lead", "conversation__employee", "call")


# ------------------------------------------------------------------ telephony transfer (warm / cold)
def start_transfer(call_id, reason, detail=""):
    """Called by the Voice Gateway after the AI said it will connect the caller. → {"say", "end", "transfer_url"}"""
    with platform_context():
        call = Call.all_companies.select_related("conversation", "provider", "employee").get(pk=call_id)
    with company_context(call.company_id):
        conv = Conversation.objects.select_related("employee", "lead", "company").get(pk=call.conversation_id)
        handoff = request(conv, reason, detail, call=call)
        if handoff.status == Handoff.NO_AGENT:
            return {"handoff": str(handoff.pk), "status": "no_agent", "end": False}
        if call.reason == "browser_test" or call.provider is None:
            # a browser test cannot be transferred: the agent still gets the screen pop and e-mail
            return {"handoff": str(handoff.pk), "status": "simulated", "end": True}
        services.transition(call, Call.TRANSFERRING, handoff.get_reason_display())
        return {
            "handoff": str(handoff.pk),
            "status": "ringing",
            "end": False,
            "transfer_url": services.webhook_url(call.provider, "transfer", handoff=handoff.pk),
        }


def redirect(call_id, transfer_url):
    """Move the live call to the dial instructions (the media stream to the AI ends)."""
    with platform_context():
        call = Call.all_companies.select_related("provider").get(pk=call_id)
    try:
        telephony.for_provider(call.provider).transfer(call.provider_call_id, transfer_url)
        return True
    except telephony.ProviderError as exc:
        log.warning("transfer failed for call %s: %s", call_id, exc)
        with company_context(call.company_id):
            services.transition(call, Call.IN_PROGRESS, f"transfer failed: {exc}")
            Call.objects.filter(pk=call.pk).update(transfer_status="failed")
            handoff = call.handoffs.order_by("-created_at").first()
            if handoff:
                finish(handoff, Handoff.FAILED)
        return False


def dial_response(handoff):
    """Dial instructions for the ringing agent (the provider fetches these from the transfer webhook)."""
    call = handoff.call
    adapter = telephony.for_provider(call.provider)
    if handoff.status != Handoff.RINGING or not handoff.assigned_user:
        phrase = _phrase(handoff, "no_agent")
        return adapter.hangup_xml(phrase)
    whisper = services.webhook_url(call.provider, "whisper", handoff=handoff.pk) if handoff.mode == "warm" else ""
    after = services.webhook_url(call.provider, "transfer-result", handoff=handoff.pk)
    return adapter.dial(
        handoff.assigned_user.phone,
        call.to_e164 if call.direction == "inbound" else call.from_e164,
        whisper,
        setting("handoff.agent_ring_seconds"),
        after,
    )


def _phrase(handoff, key):
    from apps.agents import runtime
    from apps.providers import languages

    lang = handoff.conversation.language or handoff.conversation.employee.primary_language
    return runtime._render(languages.text(lang, key), handoff.conversation.employee)
