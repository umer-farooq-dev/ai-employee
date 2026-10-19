"""Phase 5 part 1: speech / telephony providers (SA-10), languages, voices and speech routes (SA-11, VOICE-07 … 09,
20, 21) and the calling settings. Provider HTTP calls are faked — no network."""

import base64

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import Client

from apps.audit.models import AuditLog
from apps.core.india import detect_language
from apps.platform_config import services as config
from apps.providers import adapters, languages, services
from apps.providers.models import Language, Provider, SpeechRoute, Voice
from apps.rbac.models import Role

from .conftest import make_user

API = "/api/v1/admin/ai-providers/"
LANG_API = "/api/v1/admin/languages/"
VOICE_API = "/api/v1/admin/voices/"


class FakeHTTP:
    def __init__(self, monkeypatch, fail=False):
        self.calls, self.fail = [], fail
        monkeypatch.setattr(adapters, "_request", self)
        monkeypatch.setattr("apps.providers.vendors._request", self)

    def __call__(self, method, url, headers, body=None, timeout=60):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body})
        if self.fail:
            raise adapters.ProviderError("HTTP 401: invalid credentials")
        if "/Accounts/" in url:
            return {"friendly_name": "Test account", "status": "active"}
        if url.endswith("/v1/voices"):
            return {
                "voices": [
                    {
                        "voice_id": "v1",
                        "name": "Riya",
                        "labels": {"gender": "female"},
                        "preview_url": "https://x/1.mp3",
                    },
                    {"voice_id": "v2", "name": "Arjun", "labels": {"gender": "male"}},
                ]
            }
        if url.endswith("/v1/projects"):
            return {"projects": [{"project_id": "p"}]}
        raise AssertionError(url)


def staff_with(*perms):
    role = Role.objects.create(
        scope="platform", key="-".join(p.split(".")[0] for p in perms), name="R", permissions=perms
    )
    user = make_user(f"{role.key}@example.com")
    user.is_staff, user.platform_role = True, role
    user.save()
    c = Client()
    c.force_login(user)
    return c


# ---------------------------------------------------------------- seeds
@pytest.mark.django_db
def test_voice_vendors_languages_and_settings_are_seeded():
    voice = Provider.objects.exclude(vendor="")
    assert {"sarvam", "deepgram", "elevenlabs", "exotel", "plivo", "twilio", "whisper-local"} <= set(
        voice.values_list("key", flat=True)
    )
    assert not voice.filter(is_active=True).exists() and not voice.exclude(api_key="").exists()
    assert set(voice.filter(test_only=True).values_list("key", flat=True)) == {"whisper-local", "kokoro-local"}
    assert {"chat", "stt", "tts"} <= set(Provider.objects.get(key="openai").capabilities)  # one key for both
    assert languages.codes() == ["en", "hi", "bn"]
    hi = Language.objects.get(code="hi")
    assert hi.locale == "hi-IN" and hi.script == "devanagari" and len(hi.texts["fillers"]) == 3
    assert not SpeechRoute.objects.exists()  # which provider speaks a language is the client's choice
    assert Voice.objects.filter(provider__key="sarvam", language__code="bn").count() == 4
    assert config.get("calling.window_start") == "09:00" and config.get("retention.recordings_days") == 90


# ---------------------------------------------------------------- vendor keys, config, connection test
@pytest.mark.django_db
def test_telephony_vendor_needs_its_account_id_and_tests_with_basic_auth(admin_client, monkeypatch):
    http = FakeHTTP(monkeypatch)
    twilio = Provider.objects.get(key="twilio")
    r = admin_client.patch(f"{API}{twilio.pk}/", {"api_key": "tok-secret"}, content_type="application/json")
    assert r.status_code == 200 and "tok-secret" not in r.content.decode()
    r = admin_client.post(f"{API}{twilio.pk}/active/", {"is_active": True}, content_type="application/json")
    assert r.status_code == 400 and "Account SID" in r.json()["error"]["details"][0]
    r = admin_client.patch(
        f"{API}{twilio.pk}/",
        {"config": {"account_sid": "AC123", "unknown": "dropped"}},
        content_type="application/json",
    )
    assert r.json()["config"] == {"account_sid": "AC123"}
    r = admin_client.post(f"{API}{twilio.pk}/test/")
    assert r.json() == {"health": {"ok": True, "message": "Connected · Test account (active)"}, "models": []}
    call = http.calls[-1]
    assert call["url"] == "https://api.twilio.com/2010-04-01/Accounts/AC123.json"
    assert call["headers"]["Authorization"] == "Basic " + base64.b64encode(b"AC123:tok-secret").decode()
    assert admin_client.post(f"{API}{twilio.pk}/active/", {"is_active": True}, content_type="application/json").json()[
        "is_active"
    ]
    with connection.cursor() as cur:
        cur.execute("SELECT api_key FROM providers_provider WHERE id = %s", [twilio.pk])
        assert "tok-secret" not in cur.fetchone()[0]
    log = AuditLog.objects.filter(action="ai_provider.update", entity_id="twilio").latest("created_at")
    assert "tok-secret" not in str(log.changes)

    FakeHTTP(monkeypatch, fail=True)
    assert admin_client.post(f"{API}{twilio.pk}/test/").json()["health"]["ok"] is False


@pytest.mark.django_db
def test_local_free_engines_need_no_key_but_are_blocked_in_production(admin_client, settings):
    whisper = Provider.objects.get(key="whisper-local")
    r = admin_client.post(f"{API}{whisper.pk}/active/", {"is_active": True}, content_type="application/json")
    assert r.status_code == 200
    assert services.test_connection(whisper)[0]["message"].startswith("Runs inside the Voice Gateway")
    sarvam = Provider.objects.get(key="sarvam")
    r = admin_client.post(f"{API}{sarvam.pk}/active/", {"is_active": True}, content_type="application/json")
    assert r.status_code == 400  # real vendors need their key
    settings.ENVIRONMENT = "production"
    whisper.is_active = False
    whisper.save()
    r = admin_client.post(f"{API}{whisper.pk}/active/", {"is_active": True}, content_type="application/json")
    assert r.status_code == 400 and "production" in r.json()["error"]["details"][0]


@pytest.mark.django_db
def test_custom_speech_provider_needs_a_known_vendor(admin_client):
    base = {"key": "my-stt", "name": "My STT", "base_url": "https://stt.example.com", "capabilities": ["stt"]}
    r = admin_client.post(API, base, content_type="application/json")
    assert r.status_code == 400 and "vendor" in r.json()["error"]["details"][0]
    r = admin_client.post(API, {**base, "vendor": "deepgram"}, content_type="application/json")
    assert r.status_code == 201 and r.json()["vendor"] == "deepgram"


@pytest.mark.django_db
def test_ai_and_voice_staff_only_manage_their_own_capabilities():
    ai_only = staff_with("ai_providers.manage")
    keys = {p["key"] for p in ai_only.get(API).json()}
    assert "openai" in keys and "twilio" not in keys
    openai = Provider.objects.get(key="openai")
    r = ai_only.patch(f"{API}{openai.pk}/", {"capabilities": ["chat", "embedding"]}, content_type="application/json")
    assert r.status_code == 403  # removing stt / tts belongs to Voice Settings
    r = ai_only.patch(
        f"{API}{openai.pk}/", {"capabilities": ["chat", "embedding", "stt", "tts"]}, content_type="application/json"
    )
    assert r.status_code == 200
    assert ai_only.get(LANG_API).status_code == 403
    voice_only = staff_with("voice_settings.manage")
    keys = {p["key"] for p in voice_only.get(f"{API}?group=voice").json()}
    assert "twilio" in keys and "anthropic" not in keys
    assert voice_only.get("/api/v1/admin/ai-routes/").status_code == 403
    assert voice_only.get("/superadmin/voice-settings/").status_code == 200
    assert voice_only.get("/superadmin/ai-settings/").status_code in (302, 403)


# ---------------------------------------------------------------- languages (VOICE-20: no code)
@pytest.mark.django_db
def test_new_language_is_configuration_only(admin_client, set_setting):
    r = admin_client.post(
        LANG_API,
        {
            "code": "ta",
            "name": "Tamil",
            "native_name": "தமிழ்",
            "locale": "ta-IN",
            "script": "tamil",
            "texts": {"disclosure": "நான் AI உதவியாளர்.", "fillers": ["ஒரு நிமிடம்", " "], "unknown_key": "x"},
        },
        content_type="application/json",
    )
    assert r.status_code == 400 and "Unknown text" in r.json()["error"]["details"][0]
    r = admin_client.post(
        LANG_API,
        {
            "code": "ta",
            "name": "Tamil",
            "locale": "ta-IN",
            "script": "tamil",
            "texts": {"fillers": ["ஒரு நிமிடம்", " "]},
        },
        content_type="application/json",
    )
    assert r.status_code == 201, r.content
    assert r.json()["texts"] == {"fillers": ["ஒரு நிமிடம்"]}
    assert ("ta", "Tamil") in languages.choices()
    assert detect_language("வணக்கம், எனக்கு வீடு வேண்டும்") == "ta"
    assert detect_language("मुझे घर चाहिए") == "hi" and detect_language("2BHK chahiye") == "en"
    ta = r.json()["id"]
    assert admin_client.patch(f"{LANG_API}{ta}/", {"code": "tm"}, content_type="application/json").status_code == 400
    # forms everywhere follow the list: System Settings shows a fallback text field for Tamil
    assert "ai.fallback_message__ta" in admin_client.get("/superadmin/settings/system/?tab=ai").content.decode()
    admin_client.patch(f"{LANG_API}{ta}/", {"is_active": False}, content_type="application/json")
    assert "ta" not in languages.codes() and detect_language("வணக்கம் வீடு") == "en"
    assert AuditLog.objects.filter(action="language.create", entity_id="ta").exists()


@pytest.mark.django_db
def test_last_language_cannot_be_switched_off_and_used_language_cannot_be_deleted(admin_client, company_a):
    for code in ("hi", "bn"):
        services.save_language(Language.objects.get(code=code), {"is_active": False})
    en = Language.objects.get(code="en")
    r = admin_client.patch(f"{LANG_API}{en.pk}/", {"is_active": False}, content_type="application/json")
    assert r.status_code == 400 and "At least one" in r.json()["error"]["details"][0]

    from apps.agents import services as employees
    from apps.industries.models import Industry
    from apps.tenancy.context import company_context

    company_a.industry = Industry.objects.get(key="real-estate")
    company_a.template_version = company_a.industry.published_version
    company_a.save()
    with company_context(company_a.id):
        employees.create_employee(company_a, {"role": "sales_executive", "name": "Sara"})
    hi = Language.objects.get(code="hi")
    r = admin_client.delete(f"{LANG_API}{hi.pk}/")
    assert r.status_code == 400 and "switch it off" in r.json()["error"]["details"][0]


# ---------------------------------------------------------------- speech routes with failover (VOICE-08, 21)
@pytest.mark.django_db
def test_speech_routes_validate_capability_voice_and_fail_over_in_order(admin_client, settings):
    hi = Language.objects.get(code="hi")
    url = f"{LANG_API}{hi.pk}/routes/"
    r = admin_client.put(
        url, {"kind": "stt", "routes": [{"provider": "cartesia", "model": "sonic-2"}]}, "application/json"
    )
    assert r.status_code == 400 and "does not offer" in r.json()["error"]["details"][0]
    r = admin_client.put(
        url,
        {
            "kind": "stt",
            "routes": [
                {"provider": "sarvam", "model": "saarika:v2.5"},
                {"provider": "whisper-local", "model": "small"},
            ],
        },
        "application/json",
    )
    assert r.status_code == 200, r.content
    r = admin_client.put(
        url, {"kind": "tts", "routes": [{"provider": "sarvam", "model": "bulbul:v2"}]}, "application/json"
    )
    assert r.status_code == 400 and "voice" in r.json()["error"]["details"][0]
    anushka = Voice.objects.get(provider__key="sarvam", language=hi, provider_voice_id="anushka")
    r = admin_client.put(
        url,
        {"kind": "tts", "routes": [{"provider": "sarvam", "model": "saarika:v2.5", "voice": str(anushka.pk)}]},
        "application/json",
    )
    assert r.status_code == 400 and "text-to-speech model" in r.json()["error"]["details"][0]  # an STT model
    kokoro_en = Voice.objects.get(provider__key="kokoro-local", language__code="en")
    r = admin_client.put(
        url,
        {"kind": "tts", "routes": [{"provider": "sarvam", "model": "bulbul:v2", "voice": str(kokoro_en.pk)}]},
        "application/json",
    )
    assert r.status_code == 400  # the voice must belong to that provider
    r = admin_client.put(
        url,
        {"kind": "tts", "routes": [{"provider": "sarvam", "model": "bulbul:v2", "voice": str(anushka.pk)}]},
        "application/json",
    )
    tts = [x for x in r.json()["routes"] if x["kind"] == "tts"]
    assert tts[0]["voice_name"] == "Anushka" and tts[0]["provider_active"] is False

    assert services.speech_chain("hi", "stt") == []  # providers are still off
    Provider.objects.filter(key__in=["sarvam", "whisper-local"]).update(is_active=True, api_key="")
    assert [r.provider.key for r in services.speech_chain("hi", "stt")] == ["sarvam", "whisper-local"]
    settings.ENVIRONMENT = "production"
    assert [r.provider.key for r in services.speech_chain("hi", "stt")] == ["sarvam"]  # test-only skipped


# ---------------------------------------------------------------- voice catalogue (VOICE-09)
@pytest.mark.django_db
def test_voice_catalogue_crud_and_import_from_provider(admin_client, monkeypatch):
    FakeHTTP(monkeypatch)
    eleven = Provider.objects.get(key="elevenlabs")
    services.save_provider(eleven, {"api_key": "xi-key"})
    r = admin_client.get(f"{API}{eleven.pk}/voices/?locale=hi-IN")
    assert [v["id"] for v in r.json()] == ["v1", "v2"] and r.json()[1]["gender"] == "male"
    r = admin_client.post(
        VOICE_API,
        {
            "language": "hi",
            "provider": "elevenlabs",
            "provider_voice_id": "v1",
            "name": "Riya",
            "gender": "female",
            "sample": "https://x/1.mp3",
        },
        content_type="application/json",
    )
    assert r.status_code == 201, r.content
    dup = admin_client.post(
        VOICE_API,
        {"language": "hi", "provider": "elevenlabs", "provider_voice_id": "v1", "name": "Again"},
        "application/json",
    )
    assert dup.status_code == 400
    bad = admin_client.post(
        VOICE_API,
        {"language": "hi", "provider": "deepgram-x", "provider_voice_id": "z", "name": "Z"},
        "application/json",
    )
    assert bad.status_code == 400
    stt_only = admin_client.post(
        VOICE_API,
        {"language": "hi", "provider": "whisper-local", "provider_voice_id": "z", "name": "Z"},
        "application/json",
    )
    assert stt_only.status_code == 400 and "does not offer" in stt_only.json()["error"]["details"][0]
    assert {v["name"] for v in admin_client.get(f"{VOICE_API}?language=hi&provider=elevenlabs").json()} == {"Riya"}
    vid = r.json()["id"]
    assert (
        admin_client.patch(f"{VOICE_API}{vid}/", {"is_active": False}, "application/json").json()["is_active"] is False
    )
    assert admin_client.delete(f"{VOICE_API}{vid}/").status_code == 204


# ---------------------------------------------------------------- calling settings and runtime texts
@pytest.mark.django_db
def test_calling_settings_validate_times():
    with pytest.raises(ValidationError):
        config.clean("calling.window_start", "9am")
    assert config.clean("calling.window_end", "20:30") == "20:30"


@pytest.mark.django_db
def test_runtime_uses_the_language_texts_when_the_template_has_none(company_a):
    from apps.agents import runtime
    from apps.agents import services as employees
    from apps.industries.models import Industry
    from apps.tenancy.context import company_context

    company_a.industry = Industry.objects.get(key="real-estate")
    company_a.template_version = company_a.industry.published_version
    company_a.save()
    with company_context(company_a.id):
        emp = employees.create_employee(company_a, {"role": "sales_executive", "name": "Sara"})
        emp.template_version.disclosure_texts = {}
        services.save_language(
            Language.objects.get(code="hi"), {"texts": {"disclosure": "मैं {{ employee_name }} हूँ।"}}
        )
        assert runtime.disclosure(emp, "hi") == f"मैं {emp.name} हूँ।"


# ---------------------------------------------------------------- pages
@pytest.mark.django_db
def test_voice_pages_render(admin_client):
    html = admin_client.get("/superadmin/voice-settings/").content.decode()
    assert "Voice &amp; Channels" in html and '"key": "twilio"' in html and '"key": "anthropic"' not in html
    assert "Model per task" not in html
    ai = admin_client.get("/superadmin/ai-settings/").content.decode()
    assert '"key": "anthropic"' in ai and '"key": "twilio"' not in ai
    html = admin_client.get("/superadmin/languages/").content.decode()
    assert "Voice catalogue" in html and '"code": "bn"' in html and "Anushka" in html
