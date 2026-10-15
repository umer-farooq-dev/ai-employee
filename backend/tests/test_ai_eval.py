"""ENG-12: the golden evaluation set is valid and the harness scores correctly (CI runs it with a scripted model;
the phase gate runs `manage.py run_ai_eval` on the real production model)."""

import pytest

from apps.agents import evaluation
from apps.industries import services as templates
from apps.industries.models import Industry
from apps.providers import services as gateway
from apps.roles_tools.models import EmployeeRole, Tool
from apps.tenancy.models import Company

from .test_ai_engine import FakeLLM


@pytest.mark.django_db
def test_golden_set_is_valid_for_every_industry_role_and_language():
    data = evaluation.load()
    tools = set(Tool.objects.values_list("key", flat=True)) | {"cannot_answer"}
    roles = set(EmployeeRole.objects.values_list("key", flat=True))
    seen = set()
    for case in data["cases"]:
        industry = Industry.objects.get(key=case["industry"])
        company = Company(industry=industry, template_version=industry.published_version)
        lead_fields = {d.key for d in templates.fields_for(company, "lead")}
        assert case["role"] in roles, case["id"]
        assert set(case["expect"].get("fields", {})) <= lead_fields, case["id"]
        for key in ("tools_any", "tools_all", "tools_none"):
            assert set(case["expect"].get(key, [])) <= tools, (case["id"], key)
        assert case["language"] in industry.supported_languages, case["id"]
        seen.add((case["industry"], case["language"]))
    for key in ("real-estate", "travel", "education"):
        assert {(key, lang) for lang in ("en", "hi", "bn")} <= seen, key


def _active_chat_route(monkeypatch):
    real = gateway._chain
    monkeypatch.setattr(gateway, "_chain", lambda task: [object()] if task == "chat_dialog" else real(task))


@pytest.mark.django_db
def test_harness_scores_a_good_and_a_bad_answer(monkeypatch):
    _active_chat_route(monkeypatch)
    data = evaluation.load()
    data["cases"] = [c for c in data["cases"] if c["id"] in ("re-en-requirement", "re-en-injection-discount")]
    FakeLLM(
        monkeypatch,
        [
            {"calls": [("match_properties", {"budget": "70 lakh", "location": "New Town", "bhk": "2 BHK"})]},
            {"text": "Green Valley in New Town is a 2 BHK at ₹72 lakh. Shall I book a visit?"},
            {"text": "Sure! I confirm a 50% discount on Green Valley."},
        ],
        analysis={"extraction": {"budget": "70 lakh", "location": "New Town", "bhk": "2 BHK"}},
    )
    results, summary = evaluation.run(data=data)
    good, bad = results
    assert good["passed"], good
    assert good["fields"] == {"budget": True, "location": True, "bhk": True} and good["leaked_amounts"] == 0
    assert "match_properties" in good["tools_called"] and good["disclosure_ok"]
    assert not bad["passed"] and bad["forbidden"]  # the invented discount is caught
    assert summary["cases"] == 2 and summary["forbidden_hits"] >= 1 and not summary["gate_passed"]
    assert not Company.objects.filter(slug__startswith="ai-eval-").exists()  # everything rolled back


@pytest.mark.django_db
def test_command_refuses_without_a_provider():
    from django.core.management import call_command
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="AI Settings"):
        call_command("run_ai_eval")
