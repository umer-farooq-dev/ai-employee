"""Speech and telephony vendors (SA-10): what each vendor needs in the key popup, its connection test and its voice
list. The live audio streams run in the Voice Gateway (Pipecat services); this module only does cheap REST checks.

Each vendor has one secret (Provider.api_key) plus non-secret identifiers in Provider.config. Which vendors exist,
their keys, models and prices are data in Super Admin; this file is the code that knows how to talk to each kind.
"""

import base64
import json
import time

from .adapters import ProviderError, _request, request_raw
from .costs import TELEPHONY_PRICES, WHATSAPP_PRICES

# config field: (name, label, placeholder, required)
VENDORS = {
    "sarvam": {
        "label": "Sarvam AI",
        "secret": "API subscription key",  # nosec B105 — field label, not a secret
        "config": [],
        "base_url": "https://api.sarvam.ai",
    },
    "deepgram": {
        "label": "Deepgram",
        "secret": "API key",
        "config": [],
        "base_url": "https://api.deepgram.com",
    },  # nosec B105 — field label, not a secret
    "elevenlabs": {
        "label": "ElevenLabs",
        "secret": "API key",
        "config": [],
        "base_url": "https://api.elevenlabs.io",
    },  # nosec B105 — field label, not a secret
    "cartesia": {
        "label": "Cartesia",
        "secret": "API key",
        "config": [],
        "base_url": "https://api.cartesia.ai",
    },  # nosec B105 — field label, not a secret
    "openai": {
        "label": "OpenAI",
        "secret": "API key",
        "config": [],
        "base_url": "https://api.openai.com/v1",
    },  # nosec B105 — field label, not a secret
    "google": {
        "label": "Google Cloud Speech",
        "secret": "Service account JSON",  # nosec B105 — field label, not a secret
        "secret_multiline": True,  # nosec B105 — field label, not a secret
        "config": [],
        "base_url": "https://texttospeech.googleapis.com",
    },
    "azure": {
        "label": "Azure AI Speech",
        "secret": "Speech resource key",  # nosec B105 — field label, not a secret
        "config": [("region", "Region", "centralindia", True)],
        "base_url": "https://centralindia.tts.speech.microsoft.com",
    },
    "whisper_local": {
        "label": "Whisper (runs in the Voice Gateway)",
        "secret": "",  # nosec B105 — field label, not a secret
        "config": [],
        "base_url": "http://localhost",
        "local": True,
    },
    "kokoro_local": {
        "label": "Kokoro (runs in the Voice Gateway)",
        "secret": "",  # nosec B105 — field label, not a secret
        "config": [],
        "base_url": "http://localhost",
        "local": True,
    },
    "exotel": {
        "label": "Exotel",
        "secret": "API token",  # nosec B105 — field label, not a secret
        "config": [
            ("account_sid", "Account SID", "", True),
            ("api_key", "API key (username)", "", True),
            ("subdomain", "API host", "api.in.exotel.com", True),
            ("flow_id", "Voicebot flow (app) ID", "", True),
            *TELEPHONY_PRICES,
        ],
        "base_url": "https://api.in.exotel.com",
    },
    "plivo": {
        "label": "Plivo",
        "secret": "Auth token",  # nosec B105 — field label, not a secret
        "config": [("auth_id", "Auth ID", "", True), *TELEPHONY_PRICES],
        "base_url": "https://api.plivo.com",
    },
    "twilio": {
        "label": "Twilio",
        "secret": "Auth token",  # nosec B105 — field label, not a secret
        "config": [
            ("account_sid", "Account SID", "AC…", True),
            ("sms_from", "SMS sender number (only for SMS)", "+1…", False),
            *TELEPHONY_PRICES,
        ],
        "base_url": "https://api.twilio.com",
    },
    # WA-01: the official WhatsApp Business Platform (Cloud API). BSPs join as further vendors with their adapter.
    "meta_whatsapp": {
        "label": "Meta WhatsApp Cloud API",
        "secret": "Access token (system user)",  # nosec B105 — field label, not a secret
        "webhook_secret": "App secret (verifies Meta's webhooks)",  # nosec B105 — field label, not a secret
        "config": [("app_id", "App ID", "", False), *WHATSAPP_PRICES],
        "base_url": "https://graph.facebook.com/v21.0",
    },
    # MOB-03 / NOTI-03: push alerts to the team. The VAPID key pair is generated when saved without one.
    "web_push": {
        "label": "Web Push (browsers and the installed web app)",
        "secret": "VAPID private key (leave empty: generated for you)",  # nosec B105 — field label, not a secret
        "config": [
            ("public_key", "VAPID public key", "generated with the private key", False),
            ("subject", "Contact for push services", "mailto:support@example.com", False),
        ],
        "base_url": "https://push.invalid",
        "generates_key": True,
    },
    # SA-10 e-mail: any SMTP service (Amazon SES, SendGrid, Brevo, Zoho, Google Workspace …)
    "smtp": {
        "label": "E-mail (SMTP)",
        "secret": "SMTP password / API key",  # nosec B105 — field label, not a secret
        "config": [
            ("host", "SMTP host", "email-smtp.ap-south-1.amazonaws.com", True),
            ("port", "Port", "587", False),
            ("username", "Username", "", True),
            ("security", "Security: tls / ssl / none", "tls", False),
            ("from_address", "Verified sender address", "no-reply@yourdomain.com", False),
        ],
        "base_url": "https://smtp.invalid",
    },
    # SA-10 SMS (OTP and notices). Indian DLT rules: the sender ID and template ID are registered on DLT first.
    "msg91": {
        "label": "MSG91 (SMS)",
        "secret": "Auth key",  # nosec B105 — field label, not a secret
        "config": [
            ("sender", "Sender ID (6 letters, DLT approved)", "AIEMPL", True),
            ("dlt_template_id", "DLT template ID of the OTP message", "", True),
            ("route", "Route", "4", False),
        ],
        "base_url": "https://api.msg91.com",
    },
    # SUB-03: subscriptions and payments. Key id + key secret from the Razorpay dashboard (test keys: rzp_test_…).
    "razorpay": {
        "label": "Razorpay",
        "secret": "Key secret",  # nosec B105 — field label, not a secret
        "webhook_secret": "Webhook secret (verifies renewals and failed payments)",  # nosec B105 — field label
        "config": [("key_id", "Key ID", "rzp_test_…", True)],
        "base_url": "https://api.razorpay.com",
    },
    "fcm": {
        "label": "Firebase Cloud Messaging (mobile app)",
        "secret": "Service account JSON",  # nosec B105 — field label, not a secret
        "secret_multiline": True,
        "config": [("project_id", "Firebase project ID", "from the JSON when empty", False)],
        "base_url": "https://fcm.googleapis.com",
    },
}
VENDOR_CHOICES = [(k, v["label"]) for k, v in VENDORS.items()]


def spec(provider):
    return VENDORS.get(provider.vendor or "")


def needs_key(provider):
    s = spec(provider)
    return not (s and s.get("local"))


def prepare(provider):
    """Before saving: vendors whose key the platform makes itself (Web Push VAPID pair)."""
    if (spec(provider) or {}).get("generates_key") and not provider.api_key:
        from apps.notifications.push import vapid_keys

        provider.api_key, public = vapid_keys()
        provider.config = {**(provider.config or {}), "public_key": public}
        return True
    return False


def missing_config(provider):
    s = spec(provider) or {"config": []}
    return [label for name, label, _ph, required in s["config"] if required and not (provider.config or {}).get(name)]


def _basic(user, password):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


def _cfg(provider, name):
    return str((provider.config or {}).get(name, "")).strip()


# ------------------------------------------------------------------ connection tests (free REST calls)
def _google_token(provider, timeout):
    """Service-account JSON → OAuth access token (JWT bearer grant)."""
    import jwt

    try:
        sa = json.loads(provider.api_key)
        now = int(time.time())
        assertion = jwt.encode(
            {
                "iss": sa["client_email"],
                "scope": "https://www.googleapis.com/auth/cloud-platform",
                "aud": sa.get("token_uri", "https://oauth2.googleapis.com/token"),
                "iat": now,
                "exp": now + 600,
            },
            sa["private_key"],
            algorithm="RS256",
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise ProviderError(f"The service account JSON is not valid ({exc.__class__.__name__}).") from None
    data = _request(
        "POST",
        sa.get("token_uri", "https://oauth2.googleapis.com/token"),
        {},
        {"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
        timeout,
    )
    return data["access_token"]


def test(provider, timeout=30):
    """→ health message on success; raises ProviderError otherwise."""
    v, base, key = provider.vendor, provider.base_url.rstrip("/"), provider.api_key
    if spec(provider).get("local"):
        return "Runs inside the Voice Gateway — no key needed"
    if not key:
        raise ProviderError("No key saved.")
    if missing_config(provider):
        raise ProviderError(f"Fill in: {', '.join(missing_config(provider))}.")
    if v == "deepgram":
        n = len(_request("GET", f"{base}/v1/projects", {"Authorization": f"Token {key}"}, timeout=timeout)["projects"])
        return f"Connected · {n} project(s)"
    if v in ("elevenlabs", "cartesia", "azure", "google"):
        return f"Connected · {len(voices(provider, timeout=timeout))} voices available"
    if v == "openai":
        n = len(_request("GET", f"{base}/models", {"Authorization": f"Bearer {key}"}, timeout=timeout)["data"])
        return f"Connected · {n} models available"
    if v == "sarvam":
        # no free account endpoint: a 1-word transliteration call is the cheapest authenticated request
        _request(
            "POST",
            f"{base}/transliterate",
            {"api-subscription-key": key},
            {"input": "namaste", "source_language_code": "en-IN", "target_language_code": "hi-IN"},
            timeout,
        )
        return "Connected"
    if v == "twilio":
        sid = _cfg(provider, "account_sid")
        data = _request("GET", f"{base}/2010-04-01/Accounts/{sid}.json", _basic(sid, key), timeout=timeout)
        return f"Connected · {data.get('friendly_name', sid)} ({data.get('status', '')})"
    if v == "plivo":
        auth_id = _cfg(provider, "auth_id")
        data = _request("GET", f"{base}/v1/Account/{auth_id}/", _basic(auth_id, key), timeout=timeout)
        return f"Connected · {data.get('name') or auth_id}"
    if v == "exotel":
        sid, host = _cfg(provider, "account_sid"), _cfg(provider, "subdomain")
        _request(
            "GET", f"https://{host}/v1/Accounts/{sid}.json", _basic(_cfg(provider, "api_key"), key), timeout=timeout
        )
        return f"Connected · {sid}"
    if v == "web_push":
        if not _cfg(provider, "public_key"):
            raise ProviderError("The VAPID public key is missing: remove the key and save to generate a new pair.")
        return "Keys ready · browsers can subscribe"
    if v == "fcm":
        project = _cfg(provider, "project_id") or json.loads(key).get("project_id", "")
        _google_token(provider, timeout)
        return f"Connected · Firebase project {project}"
    if v == "smtp":
        from apps.notifications.backends import smtp_connection

        conn = smtp_connection(provider, timeout=timeout)
        try:
            conn.open()
        except Exception as exc:  # noqa: BLE001 — any SMTP / socket error is a failed test
            raise ProviderError(f"SMTP login failed: {exc}") from None
        finally:
            conn.close()
        return f"Connected · {_cfg(provider, 'host')}"
    if v == "msg91":
        route = _cfg(provider, "route") or "4"
        body, _ = request_raw(
            "GET", f"https://control.msg91.com/api/balance.php?authkey={key}&type={route}", {}, None, timeout, False
        )
        text = body.decode(errors="replace").strip()[:80]
        if not text.replace(".", "", 1).isdigit():
            raise ProviderError(f"MSG91 refused the key: {text}")
        return f"Connected · {text} SMS credits"
    if v == "razorpay":
        from apps.billing.razorpay import test as razorpay_test

        return razorpay_test(provider, timeout)
    if v == "meta_whatsapp":
        data = _request("GET", f"{base}/me?fields=id,name", {"Authorization": f"Bearer {key}"}, timeout=timeout)
        note = "" if provider.webhook_secret else " · add the app secret to receive messages"
        return f"Connected · {data.get('name') or data.get('id', '')}{note}"
    raise ProviderError("This vendor has no connection test.")


# ------------------------------------------------------------------ voice catalogue import (VOICE-09)
def voices(provider, locale="", timeout=30):
    """→ [{"id", "name", "gender", "locale", "sample", "style"}] from the vendor (empty when it has no voice list)."""
    v, base, key = provider.vendor, provider.base_url.rstrip("/"), provider.api_key
    out = []
    if v == "elevenlabs":
        for row in _request("GET", f"{base}/v1/voices", {"xi-api-key": key}, timeout=timeout).get("voices", []):
            labels = row.get("labels") or {}
            out.append(
                {
                    "id": row["voice_id"],
                    "name": row.get("name", ""),
                    "gender": labels.get("gender", ""),
                    "locale": "",  # multilingual voices
                    "sample": row.get("preview_url", ""),
                    "style": labels.get("description") or labels.get("use_case", ""),
                }
            )
    elif v == "cartesia":
        data = _request("GET", f"{base}/voices", {"X-API-Key": key, "Cartesia-Version": "2025-04-16"}, timeout=timeout)
        for row in data.get("data", data) if isinstance(data, dict) else data:
            out.append(
                {
                    "id": row["id"],
                    "name": row.get("name", ""),
                    "gender": row.get("gender", ""),
                    "locale": row.get("language", ""),
                    "sample": "",
                    "style": row.get("description", ""),
                }
            )
    elif v == "azure":
        region = _cfg(provider, "region")
        url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/voices/list"
        rows = _request("GET", url, {"Ocp-Apim-Subscription-Key": key}, timeout=timeout)
        for row in rows if isinstance(rows, list) else []:
            out.append(
                {
                    "id": row["ShortName"],
                    "name": row.get("LocalName") or row.get("DisplayName", ""),
                    "gender": row.get("Gender", ""),
                    "locale": row.get("Locale", ""),
                    "sample": "",
                    "style": ", ".join(row.get("StyleList") or []),
                }
            )
    elif v == "google":
        token = _google_token(provider, timeout)
        query = f"?languageCode={locale}" if locale else ""
        data = _request("GET", f"{base}/v1/voices{query}", {"Authorization": f"Bearer {token}"}, timeout=timeout)
        for row in data.get("voices", []):
            out.append(
                {
                    "id": row["name"],
                    "name": row["name"],
                    "gender": row.get("ssmlGender", ""),
                    "locale": (row.get("languageCodes") or [""])[0],
                    "sample": "",
                    "style": "",
                }
            )
    for row in out:
        row["gender"] = {"female": "female", "male": "male"}.get(str(row["gender"]).lower(), "neutral")
    if locale:
        out = [r for r in out if not r["locale"] or r["locale"].lower().startswith(locale.lower().split("-")[0])]
    return out
