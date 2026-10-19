from django.db import migrations

from apps.rbac.catalog import AGENT_P6, MANAGER_P6

PLATFORM = ["whatsapp_templates.manage"]


def add(apps, schema_editor):
    Role = apps.get_model("rbac", "Role")
    targets = [
        ("platform", "super_admin", PLATFORM),
        ("company", "owner", MANAGER_P6),
        ("company", "manager", MANAGER_P6),
        ("company", "agent", AGENT_P6),
    ]
    for scope, key, keys in targets:
        role = Role.objects.filter(scope=scope, key=key).first()
        if role:
            role.permissions = sorted(set(role.permissions) | set(keys))
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("rbac", "0009_phase5_calls")]
    operations = [migrations.RunPython(add, migrations.RunPython.noop)]
