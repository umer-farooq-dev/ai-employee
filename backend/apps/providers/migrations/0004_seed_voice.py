"""Seed speech / telephony vendors, the MVP languages with their voice phrases, a starter voice catalogue and the
calling settings (SA-10, SA-11). Data, not code: all of it is editable in Super Admin. Vendors start switched off with
no key, and no speech route is set — which provider speaks each language is the client's choice."""

from django.db import migrations

from apps.platform_config.registry import SETTINGS

STT, TTS, TEL = "stt", "tts", "telephony"
VENDORS = [
    # key, name, description, vendor, base_url, capabilities, models, test_only
    (
        "sarvam",
        "Sarvam AI",
        "Indian speech: Saarika speech-to-text and Bulbul voices",
        "sarvam",
        "https://api.sarvam.ai",
        [STT, TTS],
        ["saarika:v2.5", "bulbul:v2"],
        False,
    ),
    ("deepgram", "Deepgram", "Fast streaming speech-to-text", "deepgram", "https://api.deepgram.com", [STT, TTS],
     ["nova-3", "aura-2"], False),
    ("elevenlabs", "ElevenLabs", "Natural multilingual voices and Scribe speech-to-text", "elevenlabs",
     "https://api.elevenlabs.io", [STT, TTS], ["scribe_v1", "eleven_flash_v2_5", "eleven_multilingual_v2"], False),
    ("cartesia", "Cartesia", "Low-latency Sonic voices", "cartesia", "https://api.cartesia.ai", [TTS], ["sonic-2"],
     False),
    ("google-speech", "Google Cloud Speech", "Chirp speech-to-text and WaveNet / Chirp voices", "google",
     "https://texttospeech.googleapis.com", [STT, TTS], ["chirp_2", "default"], False),
    ("azure-speech", "Azure AI Speech", "Speech-to-text and neural voices for Indian languages", "azure",
     "https://centralindia.tts.speech.microsoft.com", [STT, TTS], ["default"], False),
    ("whisper-local", "Whisper (local)", "Free speech-to-text on our own server — testing only", "whisper_local",
     "http://localhost", [STT], ["small", "medium", "large-v3-turbo"], True),
    ("kokoro-local", "Kokoro (local)", "Free voices on our own server (English, Hindi) — testing only",
     "kokoro_local", "http://localhost", [TTS], ["kokoro-82m"], True),
    ("exotel", "Exotel", "Indian telephony: numbers, inbound and outbound calls", "exotel",
     "https://api.in.exotel.com", [TEL], [], False),
    ("plivo", "Plivo", "Telephony: numbers, inbound and outbound calls", "plivo", "https://api.plivo.com", [TEL], [],
     False),
    ("twilio", "Twilio", "Telephony: numbers, inbound and outbound calls", "twilio", "https://api.twilio.com", [TEL],
     [], False),
]

LANGUAGES = [
    {
        "code": "en",
        "name": "English",
        "native_name": "English",
        "locale": "en-IN",
        "script": "latin",
        "texts": {
            "disclosure": "I am {{ employee_name }}, an AI assistant for {{ company_name }}.",
            "recording_consent": "This call is recorded for quality and training.",
            "greeting": "Hello! Thank you for contacting {{ company_name }}. How can I help you today?",
            "fillers": ["One moment, let me check.", "Just a second, please.", "Let me look that up for you."],
            "transfer": "Please hold, I am connecting you to a member of our team.",
            "no_agent": "Our team is busy right now. I have noted your request and someone will call you back shortly.",
            "voicemail": "Hello, this is {{ employee_name }} from {{ company_name }}. Sorry we missed you — we will "
            "call you again later.",
            "silence": "Are you still there?",
            "goodbye": "Thank you for calling {{ company_name }}. Have a good day!",
        },
    },
    {
        "code": "hi",
        "name": "Hindi",
        "native_name": "हिन्दी",
        "locale": "hi-IN",
        "script": "devanagari",
        "texts": {
            "disclosure": "मैं {{ employee_name }}, {{ company_name }} की AI सहायक हूँ।",
            "recording_consent": "गुणवत्ता और प्रशिक्षण के लिए यह कॉल रिकॉर्ड की जा रही है।",
            "greeting": "नमस्ते! {{ company_name }} से संपर्क करने के लिए धन्यवाद। मैं आपकी क्या मदद कर सकती हूँ?",
            "fillers": ["एक सेकंड, मैं चेक करती हूँ।", "बस एक पल रुकिए।", "मैं आपके लिए देख रही हूँ।"],
            "transfer": "कृपया लाइन पर बने रहें, मैं आपको हमारी टीम के सदस्य से जोड़ रही हूँ।",
            "no_agent": "अभी हमारी टीम व्यस्त है। मैंने आपकी बात नोट कर ली है, जल्द ही कोई आपको वापस कॉल करेगा।",
            "voicemail": "नमस्ते, मैं {{ company_name }} से {{ employee_name }} बोल रही हूँ। आपसे बात नहीं हो पाई, "
            "हम बाद में फिर कॉल करेंगे।",
            "silence": "क्या आप लाइन पर हैं?",
            "goodbye": "{{ company_name }} को कॉल करने के लिए धन्यवाद। आपका दिन शुभ हो!",
        },
    },
    {
        "code": "bn",
        "name": "Bengali",
        "native_name": "বাংলা",
        "locale": "bn-IN",
        "script": "bengali",
        "texts": {
            "disclosure": "আমি {{ employee_name }}, {{ company_name }}-এর একজন AI সহকারী।",
            "recording_consent": "গুণমান ও প্রশিক্ষণের জন্য এই কলটি রেকর্ড করা হচ্ছে।",
            "greeting": "নমস্কার! {{ company_name }}-এর সঙ্গে যোগাযোগ করার জন্য ধন্যবাদ। আমি আপনাকে কীভাবে সাহায্য করতে পারি?",
            "fillers": ["এক সেকেন্ড, আমি দেখে নিচ্ছি।", "একটু অপেক্ষা করুন।", "আমি আপনার জন্য খুঁজে দেখছি।"],
            "transfer": "অনুগ্রহ করে লাইনে থাকুন, আমি আপনাকে আমাদের টিমের একজনের সঙ্গে যুক্ত করছি।",
            "no_agent": "এই মুহূর্তে আমাদের টিম ব্যস্ত। আমি আপনার অনুরোধটি নোট করেছি, শীঘ্রই কেউ আপনাকে ফোন করবেন।",
            "voicemail": "নমস্কার, আমি {{ company_name }} থেকে {{ employee_name }} বলছি। আপনার সঙ্গে কথা হলো না, "
            "আমরা পরে আবার ফোন করব।",
            "silence": "আপনি কি লাইনে আছেন?",
            "goodbye": "{{ company_name }}-এ ফোন করার জন্য ধন্যবাদ। আপনার দিন ভালো কাটুক!",
        },
    },
]

# provider key, provider voice id, name, gender, style, languages
VOICES = [
    ("sarvam", "anushka", "Anushka", "female", "clear, professional", ["en", "hi", "bn"]),
    ("sarvam", "vidya", "Vidya", "female", "warm", ["en", "hi", "bn"]),
    ("sarvam", "abhilash", "Abhilash", "male", "confident", ["en", "hi", "bn"]),
    ("sarvam", "karun", "Karun", "male", "friendly", ["en", "hi", "bn"]),
    ("kokoro-local", "hf_alpha", "Kokoro Alpha", "female", "test voice", ["hi"]),
    ("kokoro-local", "hm_omega", "Kokoro Omega", "male", "test voice", ["hi"]),
    ("kokoro-local", "af_heart", "Kokoro Heart", "female", "test voice", ["en"]),
]


def seed(apps, schema_editor):
    Provider = apps.get_model("providers", "Provider")
    Language = apps.get_model("providers", "Language")
    Voice = apps.get_model("providers", "Voice")
    start = (Provider.objects.order_by("-sort_order").values_list("sort_order", flat=True).first() or 0) + 10
    for i, (key, name, desc, vendor, url, caps, models, test_only) in enumerate(VENDORS):
        Provider.objects.get_or_create(
            key=key,
            defaults={
                "name": name,
                "description": desc,
                "vendor": vendor,
                "base_url": url,
                "capabilities": caps,
                "available_models": [{"id": m, "input_cost": 0, "output_cost": 0} for m in models],
                "test_only": test_only,
                "sort_order": start + i * 10,
            },
        )
    openai = Provider.objects.filter(key="openai").first()
    if openai:  # one OpenAI key serves chat, embeddings, transcription and voices
        openai.vendor = "openai"
        openai.capabilities = sorted(set(openai.capabilities) | {STT, TTS})
        have = {m["id"] for m in openai.available_models}
        openai.available_models += [
            {"id": m, "input_cost": 0, "output_cost": 0}
            for m in ("gpt-4o-transcribe", "gpt-4o-mini-tts")
            if m not in have
        ]
        openai.save()
    for order, row in enumerate(LANGUAGES, start=1):
        Language.objects.get_or_create(code=row["code"], defaults={**row, "sort_order": order * 10})
    for order, (pkey, vid, name, gender, style, langs) in enumerate(VOICES, start=1):
        provider = Provider.objects.get(key=pkey)
        for code in langs:
            Voice.objects.get_or_create(
                language=Language.objects.get(code=code),
                provider=provider,
                provider_voice_id=vid,
                defaults={"name": name, "gender": gender, "style": style, "sort_order": order * 10},
            )
    PlatformSetting = apps.get_model("platform_config", "PlatformSetting")
    for s in SETTINGS:
        if s.key.split(".")[0] in ("calling", "voice", "retention"):
            PlatformSetting.objects.get_or_create(key=s.key, defaults={"value": s.default})


class Migration(migrations.Migration):
    dependencies = [("providers", "0003_phase5_voice"), ("platform_config", "0003_seed_phase2_settings")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
