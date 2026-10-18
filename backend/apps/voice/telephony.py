"""Telephony adapters (SDD §9.3): place a call, hang up, transfer, answer with a media stream, verify and read the
provider's callbacks. One class per vendor; the platform speaks one normalised event shape:

    {"call_id", "status", "from", "to", "duration", "answered_by", "event_id"}

status is one of Call.STATUSES. Signatures are checked with the provider's secret (SEC-13); every callback URL also
carries our own per-provider token, so vendors without signatures (Exotel) are protected too.
"""

import base64
import hashlib
import hmac
import json
import urllib.error
import urllib.parse
import urllib.request
from xml.sax.saxutils import escape, quoteattr

from apps.providers.adapters import ProviderError, _request

from .models import Call


def _form(method, url, headers, data, timeout=30):
    """Form-encoded request → JSON response (Twilio and Exotel REST APIs)."""
    if not url.startswith("https://"):
        raise ProviderError("Telephony API URLs must use https.")
    body = urllib.parse.urlencode(data, doseq=True).encode() if data is not None else None
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 (https only, checked above)
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raise ProviderError(f"HTTP {exc.code}: {exc.read().decode(errors='replace')[:300]}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderError(f"Connection failed: {getattr(exc, 'reason', exc)}") from None
    except json.JSONDecodeError:
        raise ProviderError("The provider did not return JSON.") from None


def _basic(user, password):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


def _first(params, *names):
    for n in names:
        if params.get(n) not in (None, ""):
            return params[n]
    return ""


def _key(params, *names):
    return ":".join(str(params.get(n, "")) for n in names)


def _int(value):
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


class Telephony:
    STATUS_MAP = {}
    content_type = "application/xml"

    def __init__(self, provider, timeout=30):
        self.provider = provider
        self.cfg = provider.config or {}
        self.secret = provider.api_key
        self.base = provider.base_url.rstrip("/")
        self.timeout = timeout

    def status(self, raw):
        return self.STATUS_MAP.get(str(raw or "").lower(), "")

    # subclasses: place_call, hangup, transfer, answer, dial, verify, parse


class Twilio(Telephony):
    STATUS_MAP = {
        "queued": Call.QUEUED,
        "initiated": Call.QUEUED,
        "ringing": Call.RINGING,
        "in-progress": Call.IN_PROGRESS,
        "answered": Call.IN_PROGRESS,
        "completed": Call.COMPLETED,
        "busy": Call.BUSY,
        "no-answer": Call.NO_ANSWER,
        "failed": Call.FAILED,
        "canceled": Call.CANCELED,
    }

    def _api(self, path):
        sid = self.cfg.get("account_sid", "")
        return f"{self.base}/2010-04-01/Accounts/{sid}{path}", _basic(sid, self.secret)

    def place_call(self, to, from_, answer_url, status_url, ring_timeout, time_limit, amd):  # seconds
        url, auth = self._api("/Calls.json")
        data = {
            "To": to,
            "From": from_,
            "Url": answer_url,
            "StatusCallback": status_url,
            "StatusCallbackEvent": ["initiated", "ringing", "answered", "completed"],
            "Timeout": ring_timeout,
            "TimeLimit": time_limit,
        }
        if amd:
            data["MachineDetection"] = "Enable"
        return _form("POST", url, auth, data, self.timeout)["sid"]

    def hangup(self, call_id):
        url, auth = self._api(f"/Calls/{call_id}.json")
        _form("POST", url, auth, {"Status": "completed"}, self.timeout)

    def transfer(self, call_id, dial_url):
        url, auth = self._api(f"/Calls/{call_id}.json")
        _form("POST", url, auth, {"Url": dial_url, "Method": "POST"}, self.timeout)

    def answer(self, stream_url, params):
        tags = "".join(f"<Parameter name={quoteattr(k)} value={quoteattr(str(v))}/>" for k, v in params.items())
        return f"<Response><Connect><Stream url={quoteattr(stream_url)}>{tags}</Stream></Connect></Response>"

    def dial(self, to, caller_id, whisper_url="", ring_seconds=30, after=""):
        number = f"<Number url={quoteattr(whisper_url)}>{escape(to)}</Number>" if whisper_url else escape(to)
        action = f" action={quoteattr(after)}" if after else ""
        return (
            f"<Response><Dial callerId={quoteattr(caller_id)} timeout={quoteattr(str(ring_seconds))}{action}>"
            f"{number}</Dial></Response>"
        )

    def hangup_xml(self, say=""):
        return f"<Response>{'<Say>' + escape(say) + '</Say>' if say else ''}<Hangup/></Response>"

    def verify(self, url, params, headers):
        """X-Twilio-Signature = base64(HMAC-SHA1(auth token, url + sorted key+value pairs))."""
        signed = url + "".join(k + str(params[k]) for k in sorted(params))
        expected = base64.b64encode(hmac.new(self.secret.encode(), signed.encode(), hashlib.sha1).digest()).decode()
        return hmac.compare_digest(expected, headers.get("X-Twilio-Signature", ""))

    def parse(self, params):
        answered_by = str(params.get("AnsweredBy", "")).lower()
        return {
            "call_id": params.get("CallSid", ""),
            "status": self.status(params.get("CallStatus")),
            "from": params.get("From", ""),
            "to": params.get("To", ""),
            "duration": _int(params.get("CallDuration")),
            "answered_by": "machine" if answered_by.startswith("machine") or answered_by == "fax" else answered_by,
            "event_id": _key(params, "CallSid", "CallStatus", "SequenceNumber"),
        }


class Plivo(Telephony):
    STATUS_MAP = {
        "queued": Call.QUEUED,
        "ringing": Call.RINGING,
        "in-progress": Call.IN_PROGRESS,
        "completed": Call.COMPLETED,
        "busy": Call.BUSY,
        "no-answer": Call.NO_ANSWER,
        "timeout": Call.NO_ANSWER,
        "failed": Call.FAILED,
        "cancel": Call.CANCELED,
    }

    def _api(self, path):
        auth_id = self.cfg.get("auth_id", "")
        return f"{self.base}/v1/Account/{auth_id}{path}", _basic(auth_id, self.secret)

    def place_call(self, to, from_, answer_url, status_url, ring_timeout, time_limit, amd):  # seconds
        url, auth = self._api("/Call/")
        body = {
            "from": from_.lstrip("+"),
            "to": to.lstrip("+"),
            "answer_url": answer_url,
            "answer_method": "POST",
            "hangup_url": status_url,
            "ring_url": status_url,
            "ring_timeout": ring_timeout,
            "time_limit": time_limit,
        }
        if amd:
            body.update({"machine_detection": "true", "machine_detection_url": status_url})
        data = _request("POST", url, auth, body, self.timeout)
        return data.get("request_uuid") or (data.get("request_uuid_list") or [""])[0]

    def hangup(self, call_id):
        url, auth = self._api(f"/Call/{call_id}/")
        _request("DELETE", url, auth, None, self.timeout)

    def transfer(self, call_id, dial_url):
        url, auth = self._api(f"/Call/{call_id}/")
        _request("POST", url, auth, {"legs": "aleg", "aleg_url": dial_url, "aleg_method": "POST"}, self.timeout)

    def answer(self, stream_url, params):
        query = urllib.parse.urlencode(params)
        return (
            '<Response><Stream bidirectional="true" keepCallAlive="true" contentType="audio/x-mulaw;rate=8000">'
            f"{escape(stream_url + ('&' if '?' in stream_url else '?') + query)}</Stream></Response>"
        )

    def dial(self, to, caller_id, whisper_url="", ring_seconds=30, after=""):
        confirm = f' confirmSound={quoteattr(whisper_url)} confirmKey=""' if whisper_url else ""
        action = f" action={quoteattr(after)}" if after else ""
        return (
            f"<Response><Dial callerId={quoteattr(caller_id.lstrip('+'))} timeout={quoteattr(str(ring_seconds))}"
            f"{action}{confirm}><Number>{escape(to.lstrip('+'))}</Number></Dial></Response>"
        )

    def hangup_xml(self, say=""):
        return f"<Response>{'<Speak>' + escape(say) + '</Speak>' if say else ''}<Hangup/></Response>"

    def verify(self, url, params, headers):
        """V2: X-Plivo-Signature-V2 = base64(HMAC-SHA256(auth token, url without query + nonce))."""
        nonce = headers.get("X-Plivo-Signature-V2-Nonce", "")
        base = url.split("?", 1)[0]
        expected = base64.b64encode(hmac.new(self.secret.encode(), (base + nonce).encode(), hashlib.sha256).digest())
        return bool(nonce) and hmac.compare_digest(expected.decode(), headers.get("X-Plivo-Signature-V2", ""))

    def parse(self, params):
        machine = str(params.get("Machine", "")).lower() == "true"
        status = self.status(params.get("CallStatus"))
        return {
            "call_id": _first(params, "CallUUID", "RequestUUID"),
            "status": status,
            "from": "+" + str(params.get("From", "")).lstrip("+") if params.get("From") else "",
            "to": "+" + str(params.get("To", "")).lstrip("+") if params.get("To") else "",
            "duration": _int(_first(params, "Duration", "BillDuration")),
            "answered_by": "machine" if machine else "",
            "event_id": ":".join([_first(params, "CallUUID", "RequestUUID"), _key(params, "CallStatus", "Event")]),
        }


class Exotel(Telephony):
    """Exotel streams audio through a Voicebot applet in a flow (App Bazaar); the flow's id is in the provider
    settings. Exotel callbacks carry no signature — our URL token protects them."""

    STATUS_MAP = {
        "queued": Call.QUEUED,
        "ringing": Call.RINGING,
        "in-progress": Call.IN_PROGRESS,
        "completed": Call.COMPLETED,
        "busy": Call.BUSY,
        "no-answer": Call.NO_ANSWER,
        "failed": Call.FAILED,
        "canceled": Call.CANCELED,
    }
    content_type = "application/json"

    def _api(self, path):
        sid, host = self.cfg.get("account_sid", ""), self.cfg.get("subdomain", "")
        return f"https://{host}/v1/Accounts/{sid}{path}", _basic(self.cfg.get("api_key", ""), self.secret)

    def place_call(self, to, from_, answer_url, status_url, ring_timeout, time_limit, amd):  # seconds
        url, auth = self._api("/Calls/connect.json")
        sid = self.cfg.get("account_sid", "")
        data = {
            "From": to,
            "CallerId": from_,
            "Url": f"http://my.exotel.com/{sid}/exoml/start_voice/{self.cfg.get('flow_id', '')}",
            "CustomField": answer_url,
            "StatusCallback": status_url,
            "StatusCallbackEvents[0]": "terminal",
            "StatusCallbackEvents[1]": "answered",
            "TimeOut": ring_timeout,
            "TimeLimit": time_limit,
        }
        return _form("POST", url, auth, data, self.timeout)["Call"]["Sid"]

    def hangup(self, call_id):
        raise ProviderError("Exotel ends the call when the Voicebot applet stream closes.")

    def transfer(self, call_id, dial_url):
        raise ProviderError("Exotel transfers through the flow's Connect applet after the Voicebot.")

    def answer(self, stream_url, params):
        """Voicebot applet 'dynamic URL': returns the wss address to stream to."""
        query = urllib.parse.urlencode(params)
        return json.dumps({"url": stream_url + ("&" if "?" in stream_url else "?") + query})

    def dial(self, to, caller_id, whisper_url="", ring_seconds=30, after=""):
        return json.dumps({"destination": {"numbers": [to]}, "record": False, "max_ringing_duration": ring_seconds})

    def hangup_xml(self, say=""):
        return json.dumps({"hangup": True})

    def verify(self, url, params, headers):
        return True

    def parse(self, params):
        return {
            "call_id": params.get("CallSid", ""),
            "status": self.status(_first(params, "Status", "CallStatus")),
            "from": params.get("From", ""),
            "to": _first(params, "To", "DialWhomNumber"),
            "duration": _int(_first(params, "ConversationDuration", "Duration")),
            "answered_by": "",
            "event_id": ":".join(
                [_key(params, "CallSid"), _first(params, "Status", "CallStatus"), _key(params, "EventType")]
            ),
        }


ADAPTERS = {"twilio": Twilio, "plivo": Plivo, "exotel": Exotel}


def for_provider(provider, timeout=30):
    if provider.vendor not in ADAPTERS:
        raise ProviderError(f"{provider.name} is not a telephony vendor.")
    return ADAPTERS[provider.vendor](provider, timeout)
