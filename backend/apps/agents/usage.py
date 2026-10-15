"""ENG-11 / USE-01: record AI usage per company, AI Employee and conversation (tokens, credits, provider cost)."""

from apps.platform_config.services import get as setting
from apps.providers.models import Provider

from .models import UsageEvent


def _prices(provider_key, model):
    provider = Provider.objects.filter(key=provider_key).only("available_models").first()
    for m in provider.available_models if provider else []:
        if m["id"] == model:
            return m.get("input_cost", 0) or 0, m.get("output_cost", 0) or 0
    return 0, 0


def record(company_id, result, task, employee=None, conversation=None):
    """`result` is a gateway result (provider, route_model, usage).
    Prices are per 1M tokens in the platform currency."""
    usage = result.get("usage") or {}
    tokens_in, tokens_out = usage.get("input_tokens", 0) or 0, usage.get("output_tokens", 0) or 0
    provider, model = result.get("provider", ""), result.get("route_model", "")
    price_in, price_out = _prices(provider, model)
    cost_paise = (tokens_in * price_in + tokens_out * price_out) / 1_000_000 * 100
    common = {
        "company_id": company_id,
        "employee": employee,
        "conversation": conversation,
        "task": task,
        "provider_key": provider,
        "model": model,
    }
    in_meter = "embedding_tokens" if task == "embedding" else "ai_input_tokens"
    rows = [UsageEvent(meter=in_meter, quantity=tokens_in, **common)]
    if tokens_out:
        rows.append(UsageEvent(meter="ai_output_tokens", quantity=tokens_out, **common))
    rows.append(
        UsageEvent(
            meter="ai_credits",
            quantity=(tokens_in + tokens_out) / setting("ai.tokens_per_credit"),
            unit="credits",
            provider_cost_paise=cost_paise,
            **common,
        )
    )
    UsageEvent.objects.bulk_create(rows)
