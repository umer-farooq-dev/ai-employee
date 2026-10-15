"""ENG-12 AI quality evaluation: golden conversations per industry × role × language (eval/golden.json).

Each case runs through the real engine (the AI providers set in Super Admin) inside a throw-away evaluation company,
then everything is rolled back. Scores: grounding (zero invented amounts reach the customer), extraction accuracy,
tool selection, AI disclosure, language match and hand-over. Thresholds are AI settings; grounding and disclosure
allow no failures (phase gate).
"""

import json
import re
import uuid
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.catalog import services as catalog
from apps.core.india import detect_language
from apps.core.money import parse_inr
from apps.industries.models import Industry
from apps.knowledge import services as kb
from apps.platform_config.services import get as setting
from apps.scheduling import services as calendar
from apps.tenancy.context import company_context
from apps.tenancy.models import Company

from . import runtime
from . import services as employees
from .models import ToolInvocation

GOLDEN = Path(__file__).parent / "eval" / "golden.json"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
# open around the clock, so the result never depends on the time the evaluation runs
ALL_DAY = {d: {"open": "00:00", "close": "23:59", "closed": False} for d in DAYS}
RESOURCE_HOURS = {d: "00:00-23:59" for d in DAYS}


def load(path=GOLDEN):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _value_matches(expected, actual):
    if actual in (None, "", []):
        return False
    if isinstance(expected, list):  # any of these words appears (text / location fields, several scripts)
        return any(e.lower() in str(actual).lower() for e in expected)
    if isinstance(expected, (int, float)):
        try:
            return float(str(actual).replace(",", "")) == float(expected)
        except ValueError:
            return False
    try:
        want, have = parse_inr(expected), parse_inr(actual)
        return abs(want - have) <= want * 0.01
    except (ValidationError, TypeError):
        return str(expected).strip().lower() == str(actual).strip().lower()


def score_case(case, conv):
    """→ result dict for one finished conversation."""
    expect = case.get("expect", {})
    ai = list(conv.messages.filter(role="ai").order_by("created_at"))
    called = set(ToolInvocation.objects.filter(conversation=conv).values_list("tool_key", flat=True))
    for m in ai:
        if m.meta.get("fallback") == "missing_facts":
            called.add("cannot_answer")
    fields = expect.get("fields", {})
    extracted = conv.requirement or {}
    field_hits = {k: _value_matches(v, extracted.get(k)) for k, v in fields.items()}
    replies = [m for m in ai if not m.meta.get("opening")]
    invented = sum(1 for m in replies if m.meta.get("grounding_blocked"))
    leaked = sum(1 for m in replies if runtime.ungrounded(m.content, _facts(conv)))
    forbidden = [p for p in expect.get("forbidden", []) for m in replies if re.search(p, m.content, re.I)]
    lang_target = case["language"]
    lang_hits = [detect_language(m.content, default="en") == lang_target for m in replies if m.content]
    tools_ok = (
        all(t in called for t in expect.get("tools_all", []))
        and (not expect.get("tools_any") or bool(called & set(expect["tools_any"])))
        and not (called & set(expect.get("tools_none", [])))
    )
    handoff_ok = not expect.get("handoff") or bool(called & {"assign_salesperson", "schedule_callback"})
    disclosure_ok = bool(ai) and ai[0].meta.get("disclosure") is True and bool(ai[0].content)
    passed = (
        all(field_hits.values())
        and tools_ok
        and handoff_ok
        and disclosure_ok
        and not leaked
        and not forbidden
        and all(lang_hits)
    )
    return {
        "id": case["id"],
        "industry": case["industry"],
        "language": lang_target,
        "passed": passed,
        "fields": field_hits,
        "extracted": extracted,
        "tools_called": sorted(called),
        "tools_ok": tools_ok,
        "handoff_ok": handoff_ok,
        "disclosure_ok": disclosure_ok,
        "model_invented": invented,
        "leaked_amounts": leaked,
        "forbidden": forbidden,
        "language_hits": lang_hits,
        "transcript": [(m.role, m.content) for m in conv.messages.order_by("created_at")],
    }


def _facts(conv):
    parts = [m.content for m in conv.messages.filter(role="customer")]
    parts += [json.dumps(t.output, ensure_ascii=False) for t in conv.tool_invocations.all()]
    parts += [c.text for c in kb.usable_chunks(conv.company)]
    parts.append(runtime.fallback_text(conv.employee, conv.language))
    return "\n".join(parts)


def _setup_company(industry, fixtures):
    company = Company.objects.create(
        name=f"AI evaluation — {industry.name}",
        slug=f"ai-eval-{industry.key}-{uuid.uuid4().hex[:8]}",
        status=Company.ACTIVE,
        industry=industry,
        template_version=industry.published_version,
        business_hours=ALL_DAY,
    )
    with company_context(company.id):
        for type_key, items in (fixtures.get("catalog") or {}).items():
            ctype = catalog.get_type(company, type_key)
            for values in items:
                catalog.create_item(company, ctype, values)
        for doc in fixtures.get("knowledge") or []:
            source = kb.create_source(company, {"type": "text", **doc})
            kb.process(source.pk)
            source.refresh_from_db()
            kb.approve(source)
        if fixtures.get("resource"):
            calendar.save_resource(company, {**fixtures["resource"], "working_hours": RESOURCE_HOURS})
    return company


def run(cases=None, data=None):
    """Run the golden cases (all, or the given ids). Nothing is kept: the whole run is rolled back."""
    from apps.providers.services import NoProviderAvailable, _chain

    if not _chain("chat_dialog"):
        raise NoProviderAvailable("no active chat provider")
    data = data or load()
    chosen = [c for c in data["cases"] if not cases or c["id"] in cases or c["industry"] in cases]
    results = []
    with transaction.atomic():
        companies, staff = {}, {}
        for case in chosen:
            industry = Industry.objects.get(key=case["industry"])
            if industry.key not in companies:
                companies[industry.key] = _setup_company(industry, data["fixtures"].get(industry.key, {}))
            company = companies[industry.key]
            with company_context(company.id):
                key = (industry.key, case["role"])
                if key not in staff:
                    staff[key] = employees.create_employee(
                        company, {"role": case["role"], "name": setting("ai.default_employee_name")}
                    )
                conv = runtime.start(staff[key], "test", {"language": case["language"]})
                for turn in case["turns"]:
                    runtime.reply(conv, turn)
                conv.refresh_from_db()
                conv.is_test = False  # keep the extracted data for scoring (rolled back anyway)
                runtime.end(conv)
                results.append(score_case(case, conv))
        transaction.set_rollback(True)
    return results, summary(results)


def summary(results):
    fields = [hit for r in results for hit in r["fields"].values()]
    langs = [hit for r in results for hit in r["language_hits"]]
    pct = lambda xs: round(100 * sum(xs) / len(xs), 1) if xs else 100.0  # noqa: E731
    out = {
        "cases": len(results),
        "passed": sum(r["passed"] for r in results),
        "extraction_percent": pct(fields),
        "tool_percent": pct([r["tools_ok"] for r in results]),
        "language_percent": pct(langs),
        "handoff_percent": pct([r["handoff_ok"] for r in results]),
        "disclosure_failures": sum(not r["disclosure_ok"] for r in results),
        "leaked_amounts": sum(r["leaked_amounts"] for r in results),
        "model_invented": sum(r["model_invented"] for r in results),
        "forbidden_hits": sum(len(r["forbidden"]) for r in results),
    }
    out["gate_passed"] = (
        out["extraction_percent"] >= setting("ai.eval_min_extraction_percent")
        and out["tool_percent"] >= setting("ai.eval_min_tool_percent")
        and out["language_percent"] >= setting("ai.eval_min_language_percent")
        and out["disclosure_failures"] == 0
        and out["leaked_amounts"] == 0
        and out["forbidden_hits"] == 0
    )
    return out
