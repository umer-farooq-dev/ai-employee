"""Shared inbox (WA-06, CHAT-06, HO-01 chat): people take over a live chat from the AI, reply, hand it back, assign it.

Channel-independent: the website chat widget (and WhatsApp) only deliver messages; who answers is decided here.
While a person has taken over (handled_by = human) the AI pauses; customer messages are stored and shown in the inbox.
Notices for the customer ("connecting you", "Asha joined", "back with the AI") are system messages with a notice key;
the widget shows them in the customer's language from the language phrases.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record
from apps.crm import services as crm
from apps.crm.models import Lead
from apps.platform_config.services import get as setting
from apps.rbac.services import has_perm

from . import runtime
from .models import Conversation, Message


def first_name(user):
    return ((user.full_name or "").split(" ")[0] or user.email.split("@")[0]) if user else ""


def notice(conv, key, **data):
    return Message.objects.create(
        company=conv.company, conversation=conv, role="system", content=key, meta={"notice": key, **data}
    )


def _open(conv):
    if conv.status != Conversation.ACTIVE:
        raise runtime.ConversationClosed("This conversation has ended.")


def _open_handoff(conv):
    from apps.voice.models import Handoff

    return (
        Handoff.objects.filter(
            company=conv.company, conversation=conv, status__in=[Handoff.PENDING, Handoff.RINGING, Handoff.ACCEPTED]
        )
        .order_by("-created_at")
        .first()
    )


# ------------------------------------------------------------------ customer side
def customer_message(conv, text):
    """A message while a person handles the chat (or waits to): stored, the AI stays quiet."""
    _open(conv)
    text = (text or "").strip()[: setting("ai.max_message_chars")]
    if not text:
        raise ValidationError("Type a message.")
    msg = Message.objects.create(
        company=conv.company, conversation=conv, role="customer", content=text, language=conv.language
    )
    if conv.lead_id:
        Lead.objects.filter(pk=conv.lead_id).update(last_contact_at=timezone.now())
    return msg


def request_human(conv, reason="customer_request", detail=""):
    """HO-01: the customer (button, words or the AI's transfer tool) or a trigger asks for a person → routing."""
    from apps.voice import handoff

    _open(conv)
    if conv.handled_by != Conversation.AI:
        return _open_handoff(conv)
    conv.handled_by = Conversation.WAITING
    conv.save(update_fields=["handled_by", "updated_at"])
    notice(conv, "chat_waiting")
    return handoff.request(conv, reason, detail)


def after_ai_reply(conv):
    """The AI's turn may have asked for a person (transfer tool or a configured trigger)."""
    conv.refresh_from_db(fields=["state", "handled_by", "lead", "status"])
    transfer = (conv.state or {}).get("transfer")
    if transfer and conv.status == Conversation.ACTIVE:
        return request_human(conv, transfer.get("reason") or "customer_request", transfer.get("detail", ""))
    return None


def no_agent(conv):
    """HO-04 on a chat: the customer is told (language phrase); the AI answers again; without a phone number the
    widget asks for one so the callback can happen."""
    conv.handled_by = Conversation.AI
    conv.save(update_fields=["handled_by", "updated_at"])
    lang = conv.language or conv.employee.primary_language
    from apps.providers import languages

    Message.objects.create(
        company=conv.company,
        conversation=conv,
        role="ai",
        content=runtime._render(languages.text(lang, "no_agent"), conv.employee),
        language=lang,
        meta={"no_agent": True, "ask_contact": not (conv.lead_id and conv.lead.phone)},
    )


# ------------------------------------------------------------------ team side
def _can_answer(user, company):
    if not has_perm(user, "handoffs.receive", company):
        raise ValidationError("You do not have permission to answer chats.")


def join(conv, user):
    """A person answers now (called when a handoff is accepted, or on take over)."""
    conv.handled_by, conv.assigned_user = Conversation.HUMAN, user
    conv.save(update_fields=["handled_by", "assigned_user", "updated_at"])
    notice(conv, "chat_joined", name=first_name(user))
    if conv.lead_id:
        crm.log(conv.lead, "handoff", f"{user.full_name or user.email} took over the chat", actor_type="system")


@transaction.atomic
def take_over(conv, user, request=None):
    from apps.voice import handoff

    _open(conv)
    _can_answer(user, conv.company)
    if conv.handled_by == Conversation.HUMAN and conv.assigned_user_id == user.pk:
        return conv
    open_handoff = _open_handoff(conv)
    if open_handoff and open_handoff.status != open_handoff.ACCEPTED:
        open_handoff.assigned_user = user
        open_handoff.save(update_fields=["assigned_user", "updated_at"])
        handoff.answered(open_handoff)  # joins the chat
    else:
        join(conv, user)
    record(request, "inbox.take_over", "conversation", str(conv.pk), user=user, company=conv.company)
    return conv


def reply(conv, user, text, request=None):
    """The person's message to the customer. Replying takes the chat over if the AI still had it."""
    _open(conv)
    _can_answer(user, conv.company)
    text = (text or "").strip()[: setting("ai.max_message_chars")]
    if not text:
        raise ValidationError("Type a message.")
    if conv.handled_by != Conversation.HUMAN or conv.assigned_user_id != user.pk:
        take_over(conv, user, request)
    msg = Message.objects.create(
        company=conv.company,
        conversation=conv,
        role="human",
        content=text,
        language=conv.language,
        meta={"user": str(user.pk), "name": first_name(user)},
    )
    if conv.lead_id:
        Lead.objects.filter(pk=conv.lead_id).update(last_contact_at=timezone.now())
    return msg


@transaction.atomic
def hand_back(conv, user, request=None):
    """The AI answers again; it sees the person's messages in its history."""
    from apps.voice import handoff

    _open(conv)
    _can_answer(user, conv.company)
    open_handoff = _open_handoff(conv)
    if open_handoff:
        handoff.finish(open_handoff)
    conv.handled_by = Conversation.AI
    conv.state = {**(conv.state or {}), "transfer": None, "handoff": None}
    conv.save(update_fields=["handled_by", "state", "updated_at"])
    notice(conv, "chat_ai_back")
    record(request, "inbox.hand_back", "conversation", str(conv.pk), user=user, company=conv.company)
    return conv


def assign(conv, member, by, request=None):
    """Give the chat to a team member who may answer chats (they see it under "Mine")."""
    _can_answer(by, conv.company)
    if member is not None:
        if str(member.pk) not in {str(u.pk) for u in crm.members(conv.company)}:
            raise ValidationError("Choose a member of your team.")
        _can_answer(member, conv.company)
    conv.assigned_user = member
    conv.save(update_fields=["assigned_user", "updated_at"])
    record(
        request,
        "inbox.assign",
        "conversation",
        str(conv.pk),
        changes={"to": str(member.pk) if member else None},
        user=by,
        company=conv.company,
    )
    return conv


def close(conv, user=None, request=None):
    """End the chat: summary, requirement and score are saved like every conversation (REC-02)."""
    from apps.voice import handoff

    open_handoff = _open_handoff(conv)
    if open_handoff:
        handoff.finish(open_handoff)
    if conv.status == Conversation.ACTIVE:
        notice(conv, "chat_ended")
    runtime.end(conv)
    if user:
        record(request, "inbox.end", "conversation", str(conv.pk), user=user, company=conv.company)
    return conv
