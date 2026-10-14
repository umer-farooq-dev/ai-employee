"""Phase 0 AI PoC: can the LLM turn Hinglish / Bengali / English customer speech into CRM fields?

DEFERRED (owner decision): run after the system is built; the AI provider (e.g. FreeLLMAPI) and its key are
configured in Super Admin (Phase 4), never in .env. Uses any OpenAI-compatible endpoint (dev only, dummy data):
  LLM_BASE_URL (default http://127.0.0.1:3001/v1), LLM_API_KEY, LLM_MODEL (default "auto")

Run:  python poc/ai_extraction.py            -> prints per-field accuracy, writes poc/output/ai_report.md
      python poc/ai_extraction.py --selftest -> checks the scoring, no network
"""

import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

OUT = Path(__file__).parent / "output"
FIELDS = ["location", "bhk", "budget_inr", "property_type", "purpose", "visit_day"]

PROMPT = """You extract real-estate lead details from what an Indian customer said (Hindi, English, Bengali or mixed).
Return ONLY a JSON object with these keys (use null when not said, never guess):
location (string), bhk (integer), budget_inr (integer rupees; 1 lakh = 100000, 1 crore = 10000000),
property_type ("flat" | "villa" | "plot" | "office" | null), purpose ("buy" | "rent" | "invest" | null),
visit_day (lower-case English weekday or "today" / "tomorrow" or null)."""

CASES = [
    (
        "Sir mujhe New Town mein 2BHK chahiye, budget around 70 lakh hai.",
        {"location": "new town", "bhk": 2, "budget_inr": 7000000, "purpose": "buy"},
    ),
    (
        "Salt Lake mein 3 BHK flat rent pe chahiye, 40 hazaar tak.",
        {"location": "salt lake", "bhk": 3, "budget_inr": 40000, "property_type": "flat", "purpose": "rent"},
    ),
    (
        "मुझे राजारहाट में एक करोड़ तक का विला चाहिए, इस रविवार देखने आ सकता हूँ।",
        {"location": "rajarhat", "budget_inr": 10000000, "property_type": "villa", "visit_day": "sunday"},
    ),
    (
        "আমার নিউ টাউনে দুই বিএইচকে ফ্ল্যাট চাই, বাজেট প্রায় সত্তর লাখ।",
        {"location": "new town", "bhk": 2, "budget_inr": 7000000, "property_type": "flat"},
    ),
    (
        "I want to invest in a plot near Joka, budget is 25 lakhs.",
        {"location": "joka", "budget_inr": 2500000, "property_type": "plot", "purpose": "invest"},
    ),
    (
        "Kal site visit kar sakte hain kya? 1.2 crore ka 4BHK dekh raha hoon Ballygunge mein.",
        {"location": "ballygunge", "bhk": 4, "budget_inr": 12000000, "visit_day": "tomorrow"},
    ),
    (
        "Office space chahiye Sector V mein, budget 80 lakh se 1 crore.",
        {"location": "sector v", "property_type": "office"},
    ),
    (
        "আমি গড়িয়াতে একটা তিন বেডরুমের ফ্ল্যাট ভাড়া নিতে চাই।",
        {"location": "garia", "bhk": 3, "property_type": "flat", "purpose": "rent"},
    ),
    ("Just looking for now, no budget fixed.", {"budget_inr": None, "bhk": None}),
    (
        "2 BHK chahiye, budget 55 lakh, aaj shaam ko visit ho sakta hai?",
        {"bhk": 2, "budget_inr": 5500000, "visit_day": "today"},
    ),
]


def ask(text):
    base = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:3001/v1").rstrip("/")
    body = {
        "model": os.environ.get("LLM_MODEL", "auto"),
        "temperature": 0,
        "messages": [{"role": "system", "content": PROMPT}, {"role": "user", "content": text}],
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {os.environ.get('LLM_API_KEY', '')}"},
    )
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read())
    content = data["choices"][0]["message"]["content"]
    match = re.search(r"\{.*\}", content, re.S)
    return (json.loads(match.group(0)) if match else {}), time.perf_counter() - start, data.get("model", "?")


def same(expected, got):
    if expected is None:
        return got in (None, "", "null")
    if isinstance(expected, str):
        return isinstance(got, str) and expected in got.lower()
    try:
        return int(got) == expected
    except (TypeError, ValueError):
        return False


def score(expected, got):
    """Return {field: True/False} for the fields a case checks."""
    return {f: same(v, got.get(f)) for f, v in expected.items()}


def run():
    OUT.mkdir(exist_ok=True)
    per_field = {f: [0, 0] for f in FIELDS}
    rows, times, model = [], [], "?"
    for text, expected in CASES:
        try:
            got, secs, model = ask(text)
        except Exception as exc:
            sys.exit(f"LLM call failed ({exc}). Is FreeLLMAPI running with provider keys? See poc/README.md")
        times.append(secs)
        result = score(expected, got)
        for f, ok in result.items():
            per_field[f][0] += ok
            per_field[f][1] += 1
        rows.append((text, json.dumps(got, ensure_ascii=False), sum(result.values()), len(result)))
    total_ok = sum(v[0] for v in per_field.values())
    total = sum(v[1] for v in per_field.values())
    lines = [
        "# AI extraction PoC report",
        "",
        f"Model: `{model}` · Cases: {len(CASES)} · "
        f"Overall field accuracy: **{total_ok}/{total} ({total_ok / total:.0%})** · "
        f"Median latency: {sorted(times)[len(times) // 2] * 1000:.0f} ms",
        "",
        "| Field | Correct |",
        "|---|---|",
    ]
    lines += [f"| {f} | {ok}/{n} |" for f, (ok, n) in per_field.items() if n]
    lines += ["", "| Said | Extracted | Score |", "|---|---|---|"]
    lines += [f"| {t} | `{g}` | {ok}/{n} |" for t, g, ok, n in rows]
    lines += ["", "Free models are for development only; the Phase 4 gate re-runs this on the production model."]
    (OUT / "ai_report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:3]))


def selftest():
    expected = {"location": "new town", "bhk": 2, "budget_inr": 7000000, "visit_day": None}
    got = {"location": "New Town, Kolkata", "bhk": "2", "budget_inr": 7000000, "visit_day": None}
    assert all(score(expected, got).values())
    assert not score({"budget_inr": 7000000}, {"budget_inr": 700000})["budget_inr"]
    assert not score({"bhk": None}, {"bhk": 3})["bhk"]
    print("selftest ok")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else run()
