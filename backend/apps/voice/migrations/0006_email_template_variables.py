"""The AI and handoff e-mails were seeded without their "Available variables" list, so Super Admin → Email Templates
showed "None". Fill the list from the variables the seeded subject / body actually use (only where it is empty)."""

import re

from django.db import migrations

KEYS = ["ai/details", "ai/appointment_confirmation", "ai/conversation_summary", "handoff/alert"]


def fill(apps, schema_editor):
    EmailTemplate = apps.get_model("notifications", "EmailTemplate")
    for tpl in EmailTemplate.objects.filter(key__in=KEYS):
        if not tpl.variables:
            used = re.findall(r"\{\{\s*(\w+)|\{%\s*if\s+(\w+)", f"{tpl.subject} {tpl.body_html}")
            tpl.variables = list(dict.fromkeys(a or b for a, b in used))
            tpl.save(update_fields=["variables"])


class Migration(migrations.Migration):
    dependencies = [
        ("voice", "0005_phase5_test_call_upset"),
        ("agents", "0003_seed_phase4"),
        ("notifications", "0004_seed_phase3_templates"),
    ]

    operations = [migrations.RunPython(fill, migrations.RunPython.noop)]
