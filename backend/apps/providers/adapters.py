"""Provider adapters (SDD: providers package). Two wire formats cover the popular vendors:

- "openai": the OpenAI-compatible /chat/completions, /embeddings and /models API — OpenAI, Google Gemini (its
  /v1beta/openai endpoint), xAI, Groq, Mistral, DeepSeek, OpenRouter, Together, Cerebras, FreeLLMAPI, OmniRoute …
- "anthropic": the Anthropic Messages API.

The engine speaks one format (OpenAI-style messages, neutral tool list) and gets one result shape back:
{"text": str, "tool_calls": [{"id", "name", "arguments": dict}], "usage": {"input_tokens", "output_tokens"}, "model"}.
"""

import json
import urllib.error
import urllib.request

ANTHROPIC_VERSION = "2023-06-01"


class ProviderError(Exception):
    pass


def _request(method, url, headers, body=None, timeout=60):
    if not url.startswith(("https://", "http://")):
        raise ProviderError("Base URL must start with https:// or http://")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **headers})
    try:
        # scheme limited to http(s) above
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise ProviderError(f"HTTP {exc.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderError(f"Connection failed: {getattr(exc, 'reason', exc)}") from None
    except json.JSONDecodeError:
        raise ProviderError("The provider did not return JSON.") from None


def request_raw(method, url, headers, data=None, timeout=60, as_json=True):
    """Binary / multipart bodies (speech files, media uploads) and binary downloads."""
    if not url.startswith(("https://", "http://")):
        raise ProviderError("Base URL must start with https:// or http://")
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 — scheme checked above
            body = resp.read()
            return (json.loads(body or b"{}"), resp.headers) if as_json else (body, resp.headers)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise ProviderError(f"HTTP {exc.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderError(f"Connection failed: {getattr(exc, 'reason', exc)}") from None
    except json.JSONDecodeError:
        raise ProviderError("The provider did not return JSON.") from None


def multipart(fields, files):
    """fields {name: value}, files {name: (file name, bytes, content type)} → (body, content type header)."""
    import secrets

    boundary = "----aie" + secrets.token_hex(12)
    out = []
    for name, value in fields.items():
        out.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for name, (fname, content, ctype) in files.items():
        head = f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{fname}"\r\n'
        out.append(f"{head}Content-Type: {ctype}\r\n\r\n".encode() + content + b"\r\n")
    out.append(f"--{boundary}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={boundary}"


class OpenAIAdapter:
    def __init__(self, provider, timeout):
        self.base = provider.base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {provider.api_key}"} if provider.api_key else {}
        self.timeout = timeout

    def list_models(self):
        data = _request("GET", f"{self.base}/models", self.headers, timeout=self.timeout)
        return sorted({m["id"] for m in data.get("data", []) if m.get("id")})

    def chat(self, model, messages, tools=None, **params):
        body = {"model": model, "messages": messages, **params}
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]
        data = _request("POST", f"{self.base}/chat/completions", self.headers, body, self.timeout)
        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError(f"Unexpected response: {str(data)[:200]}") from None
        usage = data.get("usage") or {}
        return {
            "text": msg.get("content") or "",
            "tool_calls": [
                {
                    "id": c.get("id", ""),
                    "name": c["function"]["name"],
                    "arguments": _json_args(c["function"].get("arguments")),
                }
                for c in msg.get("tool_calls") or []
            ],
            "usage": {
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
            },
            "model": data.get("model", model),
        }

    def embed(self, model, texts):
        data = _request("POST", f"{self.base}/embeddings", self.headers, {"model": model, "input": texts}, self.timeout)
        rows = sorted(data.get("data", []), key=lambda r: r.get("index", 0))
        usage = data.get("usage") or {}
        return {
            "vectors": [r["embedding"] for r in rows],
            "usage": {"input_tokens": usage.get("prompt_tokens", 0), "output_tokens": 0},
            "model": model,
        }


class AnthropicAdapter:
    def __init__(self, provider, timeout):
        self.base = provider.base_url.rstrip("/")
        self.headers = {"x-api-key": provider.api_key, "anthropic-version": ANTHROPIC_VERSION}
        self.timeout = timeout

    def list_models(self):
        data = _request("GET", f"{self.base}/v1/models?limit=1000", self.headers, timeout=self.timeout)
        return sorted(m["id"] for m in data.get("data", []))

    def chat(self, model, messages, tools=None, **params):
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        body = {"model": model, "messages": _to_anthropic(messages), "max_tokens": 1024, **params}
        if system:
            body["system"] = system
        if tools:
            body["tools"] = [
                {"name": t["name"], "description": t.get("description", ""), "input_schema": t["parameters"]}
                for t in tools
            ]
        data = _request("POST", f"{self.base}/v1/messages", self.headers, body, self.timeout)
        blocks = data.get("content") or []
        usage = data.get("usage") or {}
        return {
            "text": "".join(b.get("text", "") for b in blocks if b.get("type") == "text"),
            "tool_calls": [
                {"id": b["id"], "name": b["name"], "arguments": b.get("input") or {}}
                for b in blocks
                if b.get("type") == "tool_use"
            ],
            "usage": {
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            },
            "model": data.get("model", model),
        }

    def embed(self, model, texts):
        raise ProviderError("Anthropic has no embeddings API; route the embedding task to another provider.")


def _json_args(raw):
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}


def _to_anthropic(messages):
    """OpenAI-style history (assistant tool_calls, role=tool results) → Anthropic content blocks."""
    out = []
    for m in messages:
        if m["role"] == "system":
            continue
        if m["role"] == "tool":
            block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": str(m.get("content", ""))}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)  # parallel tool results go in one user turn
            else:
                out.append({"role": "user", "content": [block]})
        elif m["role"] == "assistant" and m.get("tool_calls"):
            content = [{"type": "text", "text": m["content"]}] if m.get("content") else []
            content += [
                {
                    "type": "tool_use",
                    "id": c["id"],
                    "name": c["function"]["name"],
                    "input": _json_args(c["function"].get("arguments")),
                }
                for c in m["tool_calls"]
            ]
            out.append({"role": "assistant", "content": content})
        else:
            out.append({"role": m["role"], "content": m.get("content") or ""})
    return out


ADAPTERS = {"openai": OpenAIAdapter, "anthropic": AnthropicAdapter}


def for_provider(provider, timeout=60):
    return ADAPTERS[provider.adapter](provider, timeout)
