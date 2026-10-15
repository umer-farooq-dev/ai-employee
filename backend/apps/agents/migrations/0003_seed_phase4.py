"""Seed Phase 4 data: tool registry (TOOL-01 … 07, 15), Follow-up role (ROLE-05), tools per role and per industry
template, AI e-mail templates and AI / knowledge settings. All editable in Super Admin afterwards."""

from django.db import migrations

from apps.agents.seeds import EMAILS, FOLLOW_UP_ROLE, GENERIC, INDUSTRY_TOOLS, ROLE_TOOLS, TOOLS
from apps.platform_config.registry import SETTINGS


def seed(apps, schema_editor):
    Tool = apps.get_model("roles_tools", "Tool")
    Industry = apps.get_model("industries", "Industry")
    for order, (key, name, category, handler, side, config, industries, desc) in enumerate(TOOLS, start=1):
        tool, created = Tool.objects.get_or_create(
            key=key,
            defaults={
                "name": name,
                "category": category,
                "handler": handler,
                "side_effect": side,
                "config": config,
                "description": desc,
                "sort_order": order * 10,
            },
        )
        if created and industries:
            tool.industries.set(Industry.objects.filter(key__in=industries))

    Role = apps.get_model("roles_tools", "EmployeeRole")
    key, name, desc, instructions, channels = FOLLOW_UP_ROLE
    Role.objects.get_or_create(
        key=key,
        defaults={
            "name": name,
            "description": desc,
            "instructions": instructions,
            "allowed_channels": channels,
            "sort_order": (Role.objects.count() + 1) * 10,
        },
    )
    for role in Role.objects.filter(key__in=ROLE_TOOLS, allowed_tools=[]):
        role.allowed_tools = ROLE_TOOLS[role.key]
        role.save(update_fields=["allowed_tools"])

    Version = apps.get_model("industries", "TemplateVersion")
    for version in Version.objects.select_related("industry").filter(enabled_tools=[]):
        version.enabled_tools = GENERIC + INDUSTRY_TOOLS.get(version.industry.key, [])
        version.save(update_fields=["enabled_tools"])

    EmailTemplate = apps.get_model("notifications", "EmailTemplate")
    for key, name, subject, body in EMAILS:
        EmailTemplate.objects.get_or_create(key=key, defaults={"name": name, "subject": subject, "body_html": body})

    PlatformSetting = apps.get_model("platform_config", "PlatformSetting")
    for s in SETTINGS:
        if s.key.startswith(("ai.", "knowledge.")):
            PlatformSetting.objects.get_or_create(key=s.key, defaults={"value": s.default})


class Migration(migrations.Migration):
    dependencies = [
        ("agents", "0002_rls"),
        ("roles_tools", "0003_tool"),
        ("industries", "0005_shared_rls"),
        ("notifications", "0004_seed_phase3_templates"),
        ("providers", "0002_seed_vendors"),
    ]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
