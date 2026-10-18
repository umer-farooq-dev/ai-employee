"""The Voice Gateway's link to the platform (sync Django code, called from the gateway through sync_to_async).

open_session() checks the signed call link, starts the conversation (the runtime says the AI disclosure) and gives
the gateway everything it needs as plain data: phrases per language, the speech providers in failover order and
the call limits. agent_reply() runs one turn through the same AI runtime as chat. close_session() stores the
metrics and the recording.
"""

import hmac
import io
import wave
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile

from apps.agents import runtime
from apps.agents.models import Conversation, Message
from apps.core.crypto import encrypt_bytes
from apps.core.storage import company_path, private_storage
from apps.platform_config.services import get as setting
from apps.providers import languages
from apps.providers.services import speech_chain
from apps.tenancy.context import company_context, platform_context

from . import services
from .models import Call


class SessionRefused(Exception):
    pass


@dataclass
class VoiceSession:
    call_id: str
    company_id: str
    conversation_id: str
    vendor: str  # twilio / plivo / exotel / browser
    mode: str  # talk / voicemail
    language: str
    opening: str
    phrases: dict  # {language: {key: text or [fillers]}}
    speech: dict  # {language: {"stt": [route…], "tts": [route…]}}
    recording: bool
    max_seconds: int
    provider: dict = field(default_factory=dict)  # telephony credentials for the serializer (hang up / transfer)
    is_test: bool = False


def _route(route, employee):
    p = route.provider
    voice = route.voice.provider_voice_id if route.voice else ""
    own = (employee.voices or {}).get(route.language.code)
    if own and route.kind == "tts":  # EMP-05: the company's own voice choice for this provider
        from apps.providers.models import Voice

        chosen = Voice.objects.filter(pk=own, provider=p, is_active=True).first()
        voice = chosen.provider_voice_id if chosen else voice
    return {
        "vendor": p.vendor,
        "provider": p.key,
        "api_key": p.api_key,
        "config": dict(p.config or {}),
        "base_url": p.base_url,
        "model": route.model,
        "voice": voice,
        "params": dict(route.params or {}),
        "locale": route.language.locale,
        "speed": float((employee.voices or {}).get("speed") or 1.0),
    }


def speech_plan(employee):
    plan = {}
    for code in employee.languages or [employee.primary_language]:
        plan[code] = {kind: [_route(r, employee) for r in speech_chain(code, kind)] for kind in ("stt", "tts")}
    return plan


def phrases(employee):
    out = {}
    for code in employee.languages or [employee.primary_language]:
        texts = {}
        for key in ("recording_consent", "fillers", "transfer", "no_agent", "voicemail", "silence", "goodbye"):
            value = languages.text(code, key, [] if key == "fillers" else "")
            texts[key] = (
                [runtime._render(v, employee) for v in value]
                if isinstance(value, list)
                else runtime._render(value, employee)
            )
        texts["fallback"] = runtime.fallback_text(employee, code)
        out[code] = texts
    return out


def open_session(call_id, sig, vendor, mode="talk"):
    if not sig or not hmac.compare_digest(sig, services.media_token(call_id)):
        raise SessionRefused("bad signature")
    with platform_context():
        call = Call.all_companies.select_related("employee", "provider", "lead", "company").filter(pk=call_id).first()
    if call is None or call.status in Call.TERMINAL:
        raise SessionRefused("call not found or ended")
    with company_context(call.company_id):
        employee, test = call.employee, call.reason == "browser_test"
        conv = call.conversation
        if conv is None:
            preferred = call.language or (call.lead.preferred_language if call.lead else "")
            try:
                conv = runtime.start(
                    employee,
                    "test" if test else "voice",
                    {"phone": call.customer_number, "language": preferred},
                    user=call.requested_by,
                    lead=call.lead,
                )
            except ValidationError as exc:
                raise SessionRefused(exc.messages[0]) from None
            conv.direction = call.direction
            conv.state = {**(conv.state or {}), "voice": True, "call": str(call.pk)}
            conv.save(update_fields=["direction", "state", "updated_at"])
            call.conversation, call.language = conv, conv.language
            call.save(update_fields=["conversation", "language", "updated_at"])
        services.transition(call, Call.IN_PROGRESS, f"media stream ({vendor})")
        rules = services.policy(call.company)
        recording = bool(rules["recording_enabled"] and (employee.rules or {}).get("recording", True))
        said = phrases(employee)
        lang_phrases = said.get(conv.language) or next(iter(said.values()))
        opening_msg = conv.messages.filter(role="ai").order_by("created_at").first()
        if mode == "voicemail":
            opening = lang_phrases["voicemail"]
            Message.objects.create(
                company=call.company,
                conversation=conv,
                role="ai",
                content=opening,
                language=conv.language,
                meta={"voicemail": True},
            )
        else:
            opening = opening_msg.content if opening_msg else ""
            if recording and lang_phrases["recording_consent"]:  # REC-03 / COMP-06: announced before anything else
                opening = f"{opening} {lang_phrases['recording_consent']}".strip()
                if opening_msg:
                    opening_msg.content = opening
                    opening_msg.meta = {**opening_msg.meta, "recording_consent": True}
                    opening_msg.save(update_fields=["content", "meta", "updated_at"])
        provider = {}
        if call.provider_id:
            provider = {"vendor": call.provider.vendor, "secret": call.provider.api_key, **(call.provider.config or {})}
        return VoiceSession(
            call_id=str(call.pk),
            company_id=str(call.company_id),
            conversation_id=str(conv.pk),
            vendor=vendor,
            mode=mode,
            language=conv.language,
            opening=opening,
            phrases=said,
            speech=speech_plan(employee),
            recording=recording,
            max_seconds=services.employee_max_minutes(employee) * 60,
            provider=provider,
            is_test=test,
        )


def agent_reply(session, text):
    """One caller turn → the AI's answer (same engine as chat: knowledge, tools, grounding, guardrails)."""
    with company_context(session.company_id):
        conv = Conversation.objects.select_related("employee").get(pk=session.conversation_id)
        if conv.status != Conversation.ACTIVE:
            return {"text": "", "language": conv.language, "ended": True, "transfer": None}
        msg = runtime.reply(conv, text)
        conv.refresh_from_db()
        return {
            "text": msg.content,
            "language": conv.language,
            "ended": conv.status != Conversation.ACTIVE,
            "transfer": (conv.state or {}).get("transfer"),
            "fallback": bool(msg.meta.get("fallback") or msg.meta.get("grounding_blocked")),
        }


def mark_unspoken(session):
    """The caller kept talking before the AI's answer was ready: that answer was never said."""
    with company_context(session.company_id):
        msg = Message.objects.filter(conversation_id=session.conversation_id, role="ai").order_by("-created_at").first()
        if msg:
            msg.meta = {**msg.meta, "unspoken": True}
            msg.save(update_fields=["meta", "updated_at"])


def note(session, role, text, meta=None):
    """A line the gateway said by itself (filler, silence prompt, goodbye) — kept in the transcript."""
    with company_context(session.company_id):
        conv = Conversation.objects.get(pk=session.conversation_id)
        Message.objects.create(
            company_id=session.company_id,
            conversation=conv,
            role=role,
            content=text,
            language=conv.language,
            meta={"voice": True, **(meta or {})},
        )


def _wav(pcm, sample_rate, channels):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def close_session(session, metrics, hangup_by="", recording=None):
    """Store what the gateway measured and recorded. Browser tests end here; telephony calls end with the
    provider's status callback (whichever comes last finishes the call)."""
    with company_context(session.company_id):
        call = Call.objects.select_related("conversation", "employee", "lead").get(pk=session.call_id)
        call.metrics = {**(call.metrics or {}), **metrics}
        call.hangup_by = call.hangup_by or hangup_by
        if recording and recording.get("pcm"):
            data = _wav(recording["pcm"], recording["sample_rate"], recording["channels"])
            key = company_path(call.company_id, "recordings", "call.wav.enc")
            private_storage.save(key, ContentFile(encrypt_bytes(data)))
            call.recording_key, call.recording_status = key, "stored"
            call.recording_seconds = int(len(recording["pcm"]) / (2 * recording["channels"] * recording["sample_rate"]))
        call.save()
        if session.is_test or call.provider_id is None:
            services.transition(call, Call.COMPLETED, "browser test ended")
            services.finish(call)
        _quality_alert(call)
    return True


def _quality_alert(call):
    """ENGR-05 / VOICE-22: a call slower than the alert thresholds is logged for the platform team."""
    import logging

    m = call.metrics or {}
    p50, p95 = m.get("p50_ms"), m.get("p95_ms")
    if (p50 and p50 > setting("voice.latency_alert_p50_ms")) or (p95 and p95 > setting("voice.latency_alert_p95_ms")):
        logging.getLogger("apps.voice.quality").warning(
            "voice latency above threshold", extra={"call": str(call.pk), "p50_ms": p50, "p95_ms": p95}
        )
