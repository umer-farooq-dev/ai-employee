from django.db import migrations

from apps.rbac.catalog import AGENT_P4, COMPANY_KEYS, MANAGER_P4

PLATFORM = ["tools.manage", "ai_oversight.view", "ai_oversight.manage"]
COMPANY = {"owner": COMPANY_KEYS, "manager": MANAGER_P4, "agent": AGENT_P4}


def add(apps, schema_editor):
    Role = apps.get_model("rbac", "Role")
    targets = [("platform", "super_admin", PLATFORM)] + [("company", k, v) for k, v in COMPANY.items()]
    for scope, key, keys in targets:
        role = Role.objects.filter(scope=scope, key=key).first()
        if role:
            role.permissions = sorted(set(role.permissions) | set(keys))
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("rbac", "0006_phase4_ai_providers")]
    operations = [migrations.RunPython(add, migrations.RunPython.noop)]
