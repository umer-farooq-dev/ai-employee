"""Seed the transfer_call tool (TOOL-08) for the roles and industry templates that hand customers to people, the
handoff alert e-mail and the handoff settings. All editable in Super Admin afterwards."""

from django.db import migrations

from apps.core.sql import tenant_rls
from apps.platform_config.registry import SETTINGS

ROLES = ["sales_executive", "receptionist", "customer_support", "follow_up"]
ALERT = (
    "handoff/alert",
    "Handoff alert to an agent",
    "Live handoff from {{ employee }}: {{ reason }}",
    "<p>Hello {{ name }},</p><p><strong>{{ employee }}</strong> is handing a customer to you now "
    "({{ reason }}).</p><p>{{ summary }}</p>{% if lead %}<p>Lead: {{ lead }}</p>{% endif %}"
    "<p>Open the panel to see the full conversation.</p>",
)


def seed(apps, schema_editor):
    Tool = apps.get_model("roles_tools", "Tool")
    Tool.objects.get_or_create(
        key="transfer_call",
        defaults={
            "name": "Transfer call",
            "category": "crm",
            "handler": "transfer_call",
            "side_effect": "external",
            "config": {},
            "description": "On a phone call, connect the customer to a human agent when they ask for a person or you "
            "cannot help. Say one short sentence first (e.g. you are connecting them).",
            "sort_order": 95,
        },
    )
    Role = apps.get_model("roles_tools", "EmployeeRole")
    for role in Role.objects.filter(key__in=ROLES):
        if role.allowed_tools and "transfer_call" not in role.allowed_tools:
            role.allowed_tools = [*role.allowed_tools, "transfer_call"]
            role.save(update_fields=["allowed_tools"])
    Version = apps.get_model("industries", "TemplateVersion")
    for version in Version.objects.all():
        if version.enabled_tools and "transfer_call" not in version.enabled_tools:
            version.enabled_tools = [*version.enabled_tools, "transfer_call"]
            version.save(update_fields=["enabled_tools"])
    EmailTemplate = apps.get_model("notifications", "EmailTemplate")
    key, name, subject, body = ALERT
    EmailTemplate.objects.get_or_create(key=key, defaults={"name": name, "subject": subject, "body_html": body})
    PlatformSetting = apps.get_model("platform_config", "PlatformSetting")
    for s in SETTINGS:
        if s.key.startswith(("handoff.", "voice.")):
            PlatformSetting.objects.get_or_create(key=s.key, defaults={"value": s.default})


class Migration(migrations.Migration):
    dependencies = [
        ("voice", "0003_handoff"),
        ("agents", "0004_conversation_state"),
        ("roles_tools", "0003_tool"),
        ("notifications", "0004_seed_phase3_templates"),
    ]
    operations = [tenant_rls("voice_handoff"), migrations.RunPython(seed, migrations.RunPython.noop)]
