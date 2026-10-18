"""Phase 5 part 3: Voice Gateway — session link to the platform, speech services from Super Admin routes, browser
test call, recording at rest, metrics (VOICE-03 … 06, 10, 12, 19, 21, 22). The LLM is the scripted fake; no audio
provider is contacted (services are only constructed)."""

import asyncio

import pytest
from django.test import Client

from apps.agents import services as employees
from apps.agents.models import AIEmployee, Message, UsageEvent
from apps.core.crypto import decrypt_bytes
from apps.core.storage import private_storage
from apps.industries.models import Industry
from apps.providers import services as providers
from apps.providers.models import Language, Provider, Voice
from apps.rbac.models import Role
from apps.tenancy.context import company_context
from apps.tenancy.services import add_member
from apps.voice import services, session
from apps.voice.models import Call

from .conftest import make_user
from .test_ai_engine import FakeLLM


@pytest.fixture
def realty(company_a):
    industry = Industry.objects.get(key="real-estate")
    company_a.industry, company_a.template_version = industry, industry.published_version
    company_a.save()
    return company_a


@pytest.fixture
def sara(realty):
    with company_context(realty.id):
        emp = employees.create_employee(realty, {"role": "sales_executive", "name": "Sara"})
    AIEmployee.all_companies.filter(pk=emp.pk).update(status=AIEmployee.ACTIVE)
    emp.refresh_from_db()
    return emp


@pytest.fixture
def routes(db):
    """English speech: Deepgram → (failover) Whisper local; voice Sarvam Anushka."""
    for key in ("deepgram", "sarvam", "whisper-local"):
        p = Provider.objects.get(key=key)
        p.api_key, p.is_active = ("" if key == "whisper-local" else f"k-{key}"), True
        p.save()
    en = Language.objects.get(code="en")
    anushka = Voice.objects.get(provider__key="sarvam", language=en, provider_voice_id="anushka")
    providers.save_speech_routes(
        en, "stt", [{"provider": "deepgram", "model": "nova-3"}, {"provider": "whisper-local", "model": "small"}]
    )
    providers.save_speech_routes(en, "tts", [{"provider": "sarvam", "model": "bulbul:v2", "voice": str(anushka.pk)}])
    return en


def browser_call(sara):
    with company_context(sara.company_id):
        call, url = services.start_browser_test(sara, "en")
    return call, url


# ---------------------------------------------------------------- browser test call (VOICE-19, EMP-10)
@pytest.mark.django_db
def test_browser_test_needs_speech_routes_and_gives_a_signed_link(sara, realty):
    with company_context(realty.id), pytest.raises(Exception, match="speech-to-text"):
        services.start_browser_test(sara, "en")


@pytest.mark.django_db
def test_voice_test_api(sara, realty, routes):
    owner = make_user("owner@realty.example")
    add_member(realty, owner.email, Role.objects.get(scope="company", key="owner"))
    c = Client()
    c.force_login(owner)
    r = c.post(f"/api/v1/ai-employees/{sara.pk}/voice-test/", {"language": "en"}, content_type="application/json")
    assert r.status_code == 201, r.content
    call = Call.all_companies.get(pk=r.json()["call"])
    assert (
        r.json()["url"].startswith("ws://127.0.0.1:8765/browser?call=")
        and services.media_token(call.pk) in r.json()["url"]
    )
    assert call.reason == "browser_test" and call.status == Call.RINGING
    html = c.get(f"/app/ai-employees/{sara.pk}/setup/test/").content.decode()
    assert "Voice test" in html and "voice-test/" in html


# ---------------------------------------------------------------- session: opening, plan, turns, close
@pytest.mark.django_db
def test_open_session_checks_the_link_and_says_disclosure_and_recording_consent(sara, routes, realty):
    call, _ = browser_call(sara)
    with pytest.raises(session.SessionRefused):
        session.open_session(str(call.pk), "forged", "browser")
    s = session.open_session(str(call.pk), services.media_token(call.pk), "browser")
    with company_context(realty.id):
        call.refresh_from_db()
        assert call.status == Call.IN_PROGRESS and call.conversation and call.conversation.is_test
        assert call.conversation.state["voice"] is True
        opening = call.conversation.messages.get(meta__opening=True)
    assert "AI assistant" in s.opening and "recorded" in s.opening and opening.content == s.opening
    assert s.recording is True and s.max_seconds == 15 * 60 and s.language == "en"
    stt = s.speech["en"]["stt"]
    assert [r["provider"] for r in stt] == ["deepgram", "whisper-local"] and stt[0]["api_key"] == "k-deepgram"
    assert s.speech["en"]["tts"][0]["voice"] == "anushka" and s.speech["en"]["tts"][0]["locale"] == "en-IN"
    assert s.phrases["en"]["fillers"] and realty.name in s.phrases["hi"]["goodbye"]  # rendered per language

    services.save_policy(realty, {"recording_enabled": False})  # company switched recording off
    call2, _ = browser_call(sara)
    s2 = session.open_session(str(call2.pk), services.media_token(call2.pk), "browser")
    assert s2.recording is False and "quality and training" not in s2.opening


@pytest.mark.django_db
def test_employee_voice_choice_overrides_the_default_voice(sara, routes, realty):
    vidya = Voice.objects.get(provider__key="sarvam", language=routes, provider_voice_id="vidya")
    with company_context(realty.id):
        employees.update_employee(sara, {"voices": {"en": str(vidya.pk), "speed": 1.2}})
        sara.refresh_from_db()
        plan = session.speech_plan(sara)
    assert plan["en"]["tts"][0]["voice"] == "vidya" and plan["en"]["tts"][0]["speed"] == 1.2


@pytest.mark.django_db
def test_turns_run_through_the_runtime_with_the_spoken_style(monkeypatch, sara, routes, realty):
    fake = FakeLLM(monkeypatch, [{"text": "Noted — what is your budget?"}])
    call, _ = browser_call(sara)
    s = session.open_session(str(call.pk), services.media_token(call.pk), "browser")
    out = session.agent_reply(s, "I want a 2BHK in New Town")
    assert out == {
        "text": "Noted — what is your budget?",
        "language": "en",
        "ended": False,
        "transfer": None,
        "fallback": False,
    }
    system = fake.calls[0]["messages"][0]["content"]
    assert "## This is a voice call" in system and "Never use lists" in system


@pytest.mark.django_db
def test_close_session_stores_metrics_and_an_encrypted_recording(tmp_path, monkeypatch, sara, routes, realty):
    from django.core.files.storage import FileSystemStorage

    monkeypatch.setattr(private_storage, "_wrapped", FileSystemStorage(location=tmp_path))
    FakeLLM(monkeypatch, [], analysis={"summary": {"summary": "Test call"}})
    call, _ = browser_call(sara)
    s = session.open_session(str(call.pk), services.media_token(call.pk), "browser")
    pcm = b"\x01\x00" * 16000 * 2 * 3  # 3 s stereo
    session.close_session(
        s,
        {"p50_ms": 900, "p95_ms": 1500, "turns": [{"total_ms": 900}]},
        "customer",
        {"pcm": pcm, "sample_rate": 16000, "channels": 2},
    )
    with company_context(realty.id):
        call.refresh_from_db()
        assert call.status == Call.COMPLETED and call.metrics["p50_ms"] == 900 and call.hangup_by == "customer"
        assert call.recording_status == "stored" and call.recording_seconds == 3
        assert call.recording_key.startswith(f"tenants/{realty.id}/recordings/")
        raw = private_storage.open(call.recording_key, "rb").read()
        assert not raw.startswith(b"RIFF") and decrypt_bytes(raw).startswith(b"RIFF")  # encrypted at rest
        assert UsageEvent.objects.filter(company=realty, meter="calls").exists()


@pytest.mark.django_db
def test_voicemail_mode_says_the_voicemail_message(sara, routes, realty):
    call, _ = browser_call(sara)
    s = session.open_session(str(call.pk), services.media_token(call.pk), "browser", mode="voicemail")
    assert "Sorry we missed you" in s.opening and realty.name in s.opening
    with company_context(realty.id):
        assert Message.objects.filter(conversation__call=call, meta__voicemail=True).exists()


# ---------------------------------------------------------------- speech services from routes (VOICE-08, 21)
@pytest.mark.django_db
def test_speech_services_built_from_routes_with_failover(sara, routes, realty):
    from pipecat.pipeline.service_switcher import ServiceSwitcher

    from apps.voice.gateway import speech

    call, _ = browser_call(sara)
    s = session.open_session(str(call.pk), services.media_token(call.pk), "browser")

    async def build():
        import aiohttp

        async with aiohttp.ClientSession() as http:
            stt, errors = speech.chain("stt", s.speech["en"]["stt"][:1], http)
            tts = speech.build("tts", s.speech["en"]["tts"][0], http)
            broken = {**s.speech["en"]["stt"][0], "vendor": "nonexistent"}
            switch, errs = speech.chain("stt", [broken, s.speech["en"]["stt"][0], s.speech["en"]["stt"][0]], http)
            return stt, tts, switch, errs

    stt, tts, switch, errs = asyncio.run(build())
    assert type(stt).__name__ == "DeepgramSTTService" and type(tts).__name__ == "SarvamTTSService"
    assert isinstance(switch, ServiceSwitcher) and "nonexistent" in errs[0]
    with pytest.raises(speech.SpeechUnavailable):
        asyncio.run(_chain_none())


async def _chain_none():
    from apps.voice.gateway import speech

    speech.chain("tts", [], None)


# ---------------------------------------------------------------- serializer, spoken text, metrics
def test_browser_serializer_and_spoken_text():
    from pipecat.frames.frames import (
        EndFrame,
        InputAudioRawFrame,
        OutputAudioRawFrame,
        OutputTransportMessageUrgentFrame,
    )

    from apps.voice.gateway.app import BrowserSerializer
    from apps.voice.gateway.pipeline import CallStats, spoken

    ser = BrowserSerializer()
    frame = asyncio.run(ser.deserialize(b"\x00\x01" * 160))
    assert isinstance(frame, InputAudioRawFrame) and frame.sample_rate == 16000
    assert isinstance(asyncio.run(ser.deserialize('{"type": "hangup"}')), EndFrame)
    assert asyncio.run(ser.serialize(OutputAudioRawFrame(audio=b"ab", sample_rate=16000, num_channels=1))) == b"ab"
    msg = asyncio.run(ser.serialize(OutputTransportMessageUrgentFrame(message={"type": "transcript", "text": "hi"})))
    assert '"transcript"' in msg

    assert spoken("Saved.\n\n- **Greater Noida**?\n- Villa\nhttps://x.y") == "Saved. Greater Noida? Villa."
    stats = CallStats()
    for ms in (800, 1000, 3000):
        stats.turn_started()
        stats.turn_t0 -= ms / 1000
        stats.bot_started()
    summary = stats.summary()
    assert summary["p50_ms"] == 1000 and summary["p95_ms"] == 3000 and len(summary["turns"]) == 3
