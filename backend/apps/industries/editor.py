"""Super Admin editor for the general part of a template version (IND-02): schema ↔ stored JSON.

Uses the same structured editor as the website CMS (repeatable rows).
Languages come from Super Admin → Languages & Voices; texts of switched-off languages are kept.
"""

from django.core.exceptions import ValidationError

from apps.cms.services import clean_content
from apps.providers import languages

# Events the platform raises (AI events arrive in Phases 4–6); each can move a lead to a status.
EVENTS = [
    ("call_started", "Call started"),
    ("call_connected", "Call connected"),
    ("qualified", "Lead qualified"),
    ("appointment_booked", "Appointment booked"),
    ("not_interested", "Customer not interested"),
    ("converted", "Converted"),
]


def f(key, label, type="text", **extra):
    return {"key": key, "label": label, "type": type, **extra}


def schema(lead_fields, statuses):
    langs = languages.choices()
    field_choices = [(d.key, d.label) for d in lead_fields]
    return (
        [f("base_instructions", "AI persona guidelines and base instructions", "textarea")]
        + [f(f"greeting_{c}", f"Greeting — {name}", "textarea") for c, name in langs]
        + [f(f"disclosure_{c}", f"AI-disclosure text — {name}", "textarea") for c, name in langs]
        + [
            f(
                "qualification_flow",
                "Qualification questions (in order)",
                "list",
                fields=[f("field", "CRM field", "select", choices=field_choices)]
                + [f(f"question_{c}", f"Question — {name}") for c, name in langs],
            ),
            f("handoff_rules", "Handoff rules", "list", fields=[f("trigger", "When"), f("action", "Then")]),
            f(
                "default_faqs",
                "Default FAQs",
                "list",
                fields=[
                    f("question", "Question"),
                    f("answer", "Answer", "textarea"),
                    f("language", "Language", "select", choices=langs),
                ],
            ),
            f(
                "whatsapp_templates",
                "Default WhatsApp templates",
                "list",
                fields=[
                    f("name", "Name"),
                    f("category", "Category"),
                    f("language", "Language", "select", choices=langs),
                    f("body", "Body ({{1}}, {{2}} … are variables)", "textarea"),
                ],
            ),
            f(
                "enabled_tools",
                "Enabled tools (tool keys; tool registry in Phase 4)",
                "list",
                fields=[f("key", "Tool key")],
            ),
            f(
                "status_transitions",
                "Automatic status changes",
                "list",
                fields=[
                    f("event", "When", "select", choices=EVENTS),
                    f("status", "Move lead to", "select", choices=[(s.key, s.label) for s in statuses]),
                ],
            ),
            f("hot_threshold", "Hot from score", "number"),
            f("warm_threshold", "Warm from score", "number"),
        ]
    )


def to_content(version):
    c = {"base_instructions": version.base_instructions}
    codes = languages.codes()
    for code in codes:
        c[f"greeting_{code}"] = (version.greetings or {}).get(code, "")
        c[f"disclosure_{code}"] = (version.disclosure_texts or {}).get(code, "")
    c["qualification_flow"] = [
        {
            "field": q.get("field", ""),
            **{f"question_{code}": (q.get("question") or {}).get(code, "") for code in codes},
        }
        for q in version.qualification_flow or []
    ]
    c["handoff_rules"] = version.handoff_rules or []
    c["default_faqs"] = version.default_faqs or []
    c["whatsapp_templates"] = version.whatsapp_templates or []
    c["enabled_tools"] = [{"key": k} for k in version.enabled_tools or []]
    c["status_transitions"] = [{"event": e, "status": s} for e, s in (version.status_transitions or {}).items()]
    thresholds = version.score_thresholds or {}
    c["hot_threshold"], c["warm_threshold"] = thresholds.get("hot", 70), thresholds.get("warm", 40)
    return c


def apply_content(version, the_schema, raw, statuses):
    """Validate the submitted editor content and write it into the version (caller saves)."""
    c = clean_content(the_schema, raw)
    errors = []
    version.base_instructions = c["base_instructions"]
    codes = languages.codes()

    def merged(old, prefix, row):  # edited languages replace, switched-off languages keep their text
        kept = {k: v for k, v in (old or {}).items() if k not in codes}
        return {**kept, **{code: row[f"{prefix}{code}"] for code in codes if row[f"{prefix}{code}"]}}

    version.greetings = merged(version.greetings, "greeting_", c)
    version.disclosure_texts = merged(version.disclosure_texts, "disclosure_", c)
    old_flow = version.qualification_flow or []
    version.qualification_flow = [
        {
            "field": q["field"],
            "question": merged((old_flow[i].get("question") if i < len(old_flow) else {}), "question_", q),
        }
        for i, q in enumerate(c["qualification_flow"])
    ]
    if any(not q["field"] for q in version.qualification_flow):
        errors.append("Every qualification question needs a CRM field.")
    version.handoff_rules = c["handoff_rules"]
    version.default_faqs = c["default_faqs"]
    version.whatsapp_templates = c["whatsapp_templates"]
    version.enabled_tools = [t["key"] for t in c["enabled_tools"] if t["key"]]
    status_keys = {s.key for s in statuses}
    transitions = {}
    for t in c["status_transitions"]:
        if t["event"] not in dict(EVENTS) or t["status"] not in status_keys:
            errors.append("Each automatic status change needs an event and a status.")
        transitions[t["event"]] = t["status"]
    version.status_transitions = transitions
    hot, warm = c["hot_threshold"], c["warm_threshold"]
    if hot is None or warm is None or not (0 <= warm < hot <= 100):
        errors.append("Scores: 0 ≤ warm < hot ≤ 100.")
    version.score_thresholds = {"hot": hot, "warm": warm}
    if errors:
        raise ValidationError(errors)
    return version
