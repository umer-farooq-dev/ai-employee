"""WhatsApp provider adapters (WA-01). The platform speaks one interface; each vendor maps it to its API.

Meta Cloud API (graph.facebook.com): messages, media, templates, webhook signature. A BSP is another class here
with the same methods, chosen by the provider's vendor in Super Admin.
"""

import hashlib
import hmac

from apps.platform_config.services import get as setting
from apps.providers.adapters import ProviderError, _request, multipart, request_raw


class MetaCloud:
    def __init__(self, provider):
        self.provider = provider
        self.base = provider.base_url.rstrip("/")
        self.timeout = setting("ai.request_timeout_seconds")

    @property
    def _auth(self):
        if not self.provider.api_key:
            raise ProviderError("The WhatsApp provider has no access token (Super Admin → Voice & channel providers).")
        return {"Authorization": f"Bearer {self.provider.api_key}"}

    # ------------------------------------------------------------------ webhooks (SEC-13)
    def verify_signature(self, body, header):
        """X-Hub-Signature-256 = sha256 HMAC of the raw body with the app secret."""
        secret = self.provider.webhook_secret
        if not secret or not header or not header.startswith("sha256="):
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, header.removeprefix("sha256="))

    # ------------------------------------------------------------------ messages
    def _send(self, number, to, payload):
        body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to.lstrip("+"), **payload}
        data = _request("POST", f"{self.base}/{number.phone_number_id}/messages", self._auth, body, self.timeout)
        try:
            return data["messages"][0]["id"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError(f"Unexpected response: {str(data)[:200]}") from None

    def send_text(self, number, to, text):
        return self._send(number, to, {"type": "text", "text": {"body": text, "preview_url": True}})

    def send_media(self, number, to, kind, media_id, caption="", filename=""):
        media = {"id": media_id}
        if caption:
            media["caption"] = caption
        if kind == "document" and filename:
            media["filename"] = filename
        return self._send(number, to, {"type": kind, kind: media})

    def send_location(self, number, to, latitude, longitude, name="", address=""):
        loc = {"latitude": latitude, "longitude": longitude, "name": name, "address": address}
        return self._send(number, to, {"type": "location", "location": loc})

    def send_template(self, number, to, template, params, header_media_id=""):
        components = []
        if template.header_type in ("image", "document") and header_media_id:
            kind = template.header_type
            components.append({"type": "header", "parameters": [{"type": kind, kind: {"id": header_media_id}}]})
        if params:
            components.append({"type": "body", "parameters": [{"type": "text", "text": str(p)} for p in params]})
        payload = {"name": template.name, "language": {"code": template.meta_language}}
        if components:
            payload["components"] = components
        return self._send(number, to, {"type": "template", "template": payload})

    def mark_read(self, number, wamid):
        body = {"messaging_product": "whatsapp", "status": "read", "message_id": wamid}
        _request("POST", f"{self.base}/{number.phone_number_id}/messages", self._auth, body, self.timeout)

    # ------------------------------------------------------------------ media
    def upload_media(self, number, content, mime, filename):
        body, ctype = multipart({"messaging_product": "whatsapp", "type": mime}, {"file": (filename, content, mime)})
        headers = {**self._auth, "Content-Type": ctype}
        data, _ = request_raw("POST", f"{self.base}/{number.phone_number_id}/media", headers, body, self.timeout)
        if not data.get("id"):
            raise ProviderError(f"Upload failed: {str(data)[:200]}")
        return data["id"]

    def download_media(self, media_id):
        """→ (bytes, mime type). Meta gives a short-lived URL that also needs the token."""
        info = _request("GET", f"{self.base}/{media_id}", self._auth, timeout=self.timeout)
        if not info.get("url"):
            raise ProviderError("Media not found.")
        content, _ = request_raw("GET", info["url"], self._auth, timeout=self.timeout, as_json=False)
        return content, info.get("mime_type", "application/octet-stream")

    def upload_example(self, content, mime):
        """Resumable upload → handle for a template's sample header image / PDF (needs the App ID)."""
        app_id = (self.provider.config or {}).get("app_id")
        if not app_id:
            raise ProviderError("Add the App ID of the WhatsApp provider to submit templates with a media header.")
        session = _request(
            "POST", f"{self.base}/{app_id}/uploads?file_length={len(content)}&file_type={mime}", self._auth, {}, 30
        )
        headers = {"Authorization": f"OAuth {self.provider.api_key}", "file_offset": "0"}
        data, _ = request_raw("POST", f"{self.base}/{session['id']}", headers, content, self.timeout)
        return data["h"]

    # ------------------------------------------------------------------ templates (WA-03)
    def create_template(self, template, header_handle=""):
        components = []
        if template.header_type == "text" and template.header_text:
            components.append({"type": "HEADER", "format": "TEXT", "text": template.header_text})
        elif template.header_type in ("image", "document"):
            header = {"type": "HEADER", "format": template.header_type.upper()}
            if header_handle:
                header["example"] = {"header_handle": [header_handle]}
            components.append(header)
        body = {"type": "BODY", "text": template.body}
        samples = template_samples(template)
        if samples:
            body["example"] = {"body_text": [samples]}
        components.append(body)
        if template.footer:
            components.append({"type": "FOOTER", "text": template.footer})
        if template.buttons:
            components.append({"type": "BUTTONS", "buttons": template.buttons})
        payload = {
            "name": template.name,
            "language": template.meta_language,
            "category": template.category,
            "components": components,
        }
        data = _request(
            "POST", f"{self.base}/{template.number.waba_id}/message_templates", self._auth, payload, self.timeout
        )
        return data.get("id", ""), str(data.get("status", "PENDING")).lower()

    def list_templates(self, waba_id):
        url = (
            f"{self.base}/{waba_id}/message_templates?fields=id,name,language,status,category,rejected_reason&limit=200"
        )
        rows = []
        while url:
            data = _request("GET", url, self._auth, timeout=self.timeout)
            rows += data.get("data", [])
            url = (data.get("paging") or {}).get("next")
        return rows

    def delete_template(self, template):
        query = f"name={template.name}" + (
            f"&hsm_id={template.provider_template_id}" if template.provider_template_id else ""
        )
        _request("DELETE", f"{self.base}/{template.number.waba_id}/message_templates?{query}", self._auth, None, 30)


SAMPLES = {
    "lead.name": "Ravi",
    "company.name": "Your company",
    "employee.name": "Sara",
    "appointment.when": "Sat 25 Oct, 11:00",
    "appointment.number": "APT-000123",
    "appointment.type": "Site visit",
    "item.title": "Green Valley 2 BHK",
    "item.price": "₹65 lakh",
    "text": "your request",
}


def template_samples(template):
    """Example values Meta needs to review a template with variables."""
    company = template.company.name if template.company_id else ""
    out = []
    for source in template.variables or []:
        out.append(company if source == "company.name" and company else SAMPLES.get(source, "example"))
    return out


ADAPTERS = {"meta_whatsapp": MetaCloud}


def for_provider(provider):
    cls = ADAPTERS.get(provider.vendor)
    if not cls:
        raise ProviderError(f"{provider.name} is not a supported WhatsApp vendor.")
    return cls(provider)
