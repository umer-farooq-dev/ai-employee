"""Phase 4 part 1: AI providers and model per task (SA-09, ENG-09). Provider HTTP calls are faked — no network."""

import json

import pytest
from django.db import connection
from django.test import Client

from apps.audit.models import AuditLog
from apps.providers import adapters, services
from apps.providers.models import ModelRoute, Provider

API = "/api/v1/admin/ai-providers/"


class FakeHTTP:
    """Stands in for urllib: records requests, answers per URL suffix, can fail for chosen hosts."""

    def __init__(self, monkeypatch, fail_hosts=()):
        self.calls, self.fail_hosts = [], set(fail_hosts)
        monkeypatch.setattr(adapters, "_request", self)

    def __call__(self, method, url, headers, body=None, timeout=60):
        self.calls.append({"method": method, "url": url, "headers": headers, "body": body})
        if any(h in url for h in self.fail_hosts):
            raise adapters.ProviderError("HTTP 503: down")
        if url.endswith("/models") or "/v1/models" in url:
            return {"data": [{"id": "model-b"}, {"id": "model-a"}]}
        if url.endswith("/chat/completions"):
            return {
                "model": body["model"],
                "choices": [
                    {
                        "message": {
                            "content": "Namaste!",
                            "tool_calls": [
                                {"id": "c1", "function": {"name": "search_product", "arguments": '{"bhk": 2}'}}
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            }
        if url.endswith("/v1/messages"):
            return {
                "model": body["model"],
                "content": [
                    {"type": "text", "text": "Hello"},
                    {"type": "tool_use", "id": "t1", "name": "create_lead", "input": {"name": "Ravi"}},
                ],
                "usage": {"input_tokens": 20, "output_tokens": 5},
            }
        if url.endswith("/embeddings"):
            return {"data": [{"index": 1, "embedding": [0.2]}, {"index": 0, "embedding": [0.1]}]}
        raise AssertionError(url)


def ready(key, models=("model-a",), caps=None):
    p = Provider.objects.get(key=key)
    p.api_key = f"sk-{key}"
    p.available_models = [{"id": m, "input_cost": 0, "output_cost": 0} for m in models]
    if caps:
        p.capabilities = caps
    p.is_active = True
    p.save()
    return p


# ---------------------------------------------------------------- seeds and storage
@pytest.mark.django_db
def test_popular_vendors_are_seeded_off_and_without_keys():
    keys = set(Provider.objects.values_list("key", flat=True))
    assert {"openai", "gemini", "anthropic", "xai", "groq", "openrouter", "freellmapi", "omniroute"} <= keys
    assert not Provider.objects.filter(is_active=True).exists()
    assert not Provider.objects.exclude(api_key="").exists()
    llm = Provider.objects.filter(vendor="")
    assert set(llm.filter(test_only=True).values_list("key", flat=True)) == {"freellmapi", "omniroute"}


@pytest.mark.django_db
def test_api_key_is_encrypted_at_rest_and_never_returned(admin_client):
    p = Provider.objects.get(key="openai")
    r = admin_client.patch(f"{API}{p.pk}/", {"api_key": "sk-secret-123"}, content_type="application/json")
    assert r.status_code == 200, r.content
    assert r.json()["has_key"] is True and "api_key" not in r.json()
    with connection.cursor() as cur:
        cur.execute("SELECT api_key FROM providers_provider WHERE id = %s", [p.pk])
        stored = cur.fetchone()[0]
    assert stored and "sk-secret-123" not in stored
    assert Provider.objects.get(pk=p.pk).api_key == "sk-secret-123"
    assert "sk-secret-123" not in admin_client.get(API).content.decode()
    log = AuditLog.objects.filter(action="ai_provider.update").latest("created_at")
    assert "sk-secret" not in json.dumps(log.changes) and log.changes["api_key"] == "replaced"
    # blank keeps the key, remove_key deletes it and switches the provider off
    admin_client.patch(f"{API}{p.pk}/", {"api_key": "", "name": "OpenAI"}, content_type="application/json")
    assert Provider.objects.get(pk=p.pk).api_key == "sk-secret-123"
    admin_client.post(f"{API}{p.pk}/active/", {"is_active": True}, content_type="application/json")
    admin_client.patch(f"{API}{p.pk}/", {"remove_key": True}, content_type="application/json")
    p.refresh_from_db()
    assert p.api_key == "" and p.is_active is False


# ---------------------------------------------------------------- toggle (no page reload: JSON API)
@pytest.mark.django_db
def test_toggle_needs_a_key_except_local_test_gateways(admin_client, settings):
    openai = Provider.objects.get(key="openai")
    r = admin_client.post(f"{API}{openai.pk}/active/", {"is_active": True}, content_type="application/json")
    assert r.status_code == 400 and "API key" in r.json()["error"]["details"][0]
    free = Provider.objects.get(key="freellmapi")
    r = admin_client.post(f"{API}{free.pk}/active/", {"is_active": True}, content_type="application/json")
    assert r.status_code == 200 and r.json()["is_active"] is True
    r = admin_client.post(f"{API}{free.pk}/active/", {"is_active": False}, content_type="application/json")
    assert r.json()["is_active"] is False
    assert AuditLog.objects.filter(action="ai_provider.on", entity_id="freellmapi").exists()


@pytest.mark.django_db
def test_test_only_provider_blocked_in_production(admin_client, settings, monkeypatch):
    FakeHTTP(monkeypatch)
    free = ready("freellmapi")
    ModelRoute.objects.create(task="chat_dialog", provider=free, model="model-a", priority=1)
    assert services.chat("chat_dialog", [{"role": "user", "content": "hi"}])["provider"] == "freellmapi"
    settings.ENVIRONMENT = "production"
    with pytest.raises(services.NoProviderAvailable):
        services.chat("chat_dialog", [{"role": "user", "content": "hi"}])
    free.is_active = False
    free.save()
    r = admin_client.post(f"{API}{free.pk}/active/", {"is_active": True}, content_type="application/json")
    assert r.status_code == 400 and "production" in r.json()["error"]["details"][0]


# ---------------------------------------------------------------- connection test and models
@pytest.mark.django_db
def test_connection_test_lists_models_and_stores_health(admin_client, monkeypatch):
    http = FakeHTTP(monkeypatch)
    p = Provider.objects.get(key="gemini")
    admin_client.patch(f"{API}{p.pk}/", {"api_key": "g-key"}, content_type="application/json")
    r = admin_client.post(f"{API}{p.pk}/test/")
    assert r.json() == {
        "health": {"ok": True, "message": "Connected · 2 models available"},
        "models": ["model-a", "model-b"],
    }
    assert http.calls[-1]["url"] == "https://generativelanguage.googleapis.com/v1beta/openai/models"
    assert http.calls[-1]["headers"]["Authorization"] == "Bearer g-key"
    assert Provider.objects.get(pk=p.pk).health["ok"] is True

    FakeHTTP(monkeypatch, fail_hosts=["googleapis"])
    r = admin_client.post(f"{API}{p.pk}/test/")
    assert r.json()["health"] == {"ok": False, "message": "HTTP 503: down"}


@pytest.mark.django_db
def test_models_with_prices_and_custom_provider(admin_client):
    r = admin_client.post(
        API,
        {
            "key": "my-gateway",
            "name": "My Gateway",
            "base_url": "https://llm.example.com/v1",
            "capabilities": ["chat", "embedding"],
            "available_models": [{"id": "m1", "input_cost": 12.5, "output_cost": 40}, {"id": "m1"}, {"id": "m2"}],
        },
        content_type="application/json",
    )
    assert r.status_code == 201, r.content
    assert [m["id"] for m in r.json()["available_models"]] == ["m1", "m2"]
    assert r.json()["available_models"][0]["input_cost"] == 12.5
    r = admin_client.patch(f"{API}{r.json()['id']}/", {"key": "other"}, content_type="application/json")
    assert r.status_code == 400
    bad = admin_client.post(API, {"key": "bad", "name": "Bad", "base_url": "ftp://x"}, content_type="application/json")
    assert bad.status_code == 400


# ---------------------------------------------------------------- model per task + gateway (ENG-09)
@pytest.mark.django_db
def test_routes_validate_capability_and_models(admin_client):
    anthropic = ready("anthropic", models=["claude-x"])
    url = "/api/v1/admin/ai-routes/"
    r = admin_client.put(
        f"{url}embedding/",
        {"routes": [{"provider": str(anthropic.pk), "model": "claude-x"}]},
        content_type="application/json",
    )
    assert r.status_code == 400 and "does not offer" in r.json()["error"]["details"][0]
    r = admin_client.put(
        f"{url}chat_dialog/", {"routes": [{"provider": "anthropic", "model": "nope"}]}, content_type="application/json"
    )
    assert r.status_code == 400
    r = admin_client.put(
        f"{url}chat_dialog/",
        {"routes": [{"provider": "anthropic", "model": "claude-x"}]},
        content_type="application/json",
    )
    assert r.status_code == 200 and r.json()[0]["priority"] == 1
    tasks = {t["task"]: t for t in admin_client.get(url).json()}
    assert tasks["chat_dialog"]["routes"][0]["provider_key"] == "anthropic"
    assert admin_client.put(f"{url}unknown/", {"routes": []}, content_type="application/json").status_code == 404


@pytest.mark.django_db
def test_gateway_falls_back_to_next_provider(monkeypatch):
    http = FakeHTTP(monkeypatch, fail_hosts=["api.openai.com"])
    openai, anthropic = ready("openai"), ready("anthropic", models=["claude-x"])
    services.save_routes(
        "chat_dialog",
        [
            {"provider": "openai", "model": "model-a"},
            {"provider": "anthropic", "model": "claude-x", "params": {"max_tokens": 50}},
        ],
    )
    tools = [
        {"name": "create_lead", "description": "Create a lead", "parameters": {"type": "object", "properties": {}}}
    ]
    result = services.chat(
        "chat_dialog",
        [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Hi"}],
        tools=tools,
    )
    assert result["provider"] == "anthropic" and result["text"] == "Hello"
    assert result["tool_calls"] == [{"id": "t1", "name": "create_lead", "arguments": {"name": "Ravi"}}]
    assert result["usage"] == {"input_tokens": 20, "output_tokens": 5}
    assert "OpenAI / model-a: HTTP 503: down" in result["fallback_errors"][0]
    sent = http.calls[-1]
    assert sent["body"]["system"] == "Be brief." and sent["body"]["max_tokens"] == 50
    assert sent["body"]["tools"][0]["input_schema"] == {"type": "object", "properties": {}}
    assert sent["headers"]["x-api-key"] == "sk-anthropic"

    openai.is_active = False  # switched-off providers are skipped
    openai.save()
    http.calls.clear()
    services.chat("chat_dialog", [{"role": "user", "content": "Hi"}])
    assert all("openai.com" not in c["url"] for c in http.calls)
    anthropic.is_active = False
    anthropic.save()
    with pytest.raises(services.NoProviderAvailable):
        services.chat("chat_dialog", [{"role": "user", "content": "Hi"}])


@pytest.mark.django_db
def test_openai_compatible_chat_tool_calls_and_embeddings(monkeypatch):
    FakeHTTP(monkeypatch)
    ready("openai", models=["model-a", "emb-1"])
    services.save_routes("chat_dialog", [{"provider": "openai", "model": "model-a"}])
    services.save_routes("embedding", [{"provider": "openai", "model": "emb-1"}])
    result = services.chat("chat_dialog", [{"role": "user", "content": "2BHK chahiye"}])
    assert result["tool_calls"] == [{"id": "c1", "name": "search_product", "arguments": {"bhk": 2}}]
    assert result["usage"] == {"input_tokens": 12, "output_tokens": 3}
    assert services.embed(["a", "b"])["vectors"] == [[0.1], [0.2]]


def test_tool_history_converts_to_anthropic_blocks():
    history = [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "find 2BHK"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "a", "function": {"name": "search_product", "arguments": '{"bhk": 2}'}},
                {"id": "b", "function": {"name": "check_availability", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "a", "content": "[]"},
        {"role": "tool", "tool_call_id": "b", "content": "free"},
    ]
    out = adapters._to_anthropic(history)
    assert [m["role"] for m in out] == ["user", "assistant", "user"]
    assert out[1]["content"][0] == {"type": "tool_use", "id": "a", "name": "search_product", "input": {"bhk": 2}}
    assert [b["tool_use_id"] for b in out[2]["content"]] == ["a", "b"]


# ---------------------------------------------------------------- access
@pytest.mark.django_db
def test_only_staff_with_permission_can_manage_ai(support, owner_a):
    for user in (support, owner_a):
        c = Client()
        c.force_login(user)
        assert c.get(API).status_code == 403
        assert c.get("/superadmin/ai-settings/").status_code in (302, 403)


@pytest.mark.django_db
def test_ai_settings_page_renders(admin_client):
    r = admin_client.get("/superadmin/ai-settings/")
    assert r.status_code == 200
    html = r.content.decode()
    assert "Vendors" in html and "Model per task" in html and '"key": "anthropic"' in html
    assert "sk-" not in html
