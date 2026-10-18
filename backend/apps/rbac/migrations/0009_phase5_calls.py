from django.db import migrations

from apps.rbac.catalog import AGENT_P5, MANAGER_P5

PLATFORM = ["number_pool.manage", "calls_oversight.view", "recordings_oversight.listen"]
OWNER = MANAGER_P5


def add(apps, schema_editor):
    Role = apps.get_model("rbac", "Role")
    targets = [("platform", "super_admin", PLATFORM), ("company", "owner", OWNER), ("company", "manager", MANAGER_P5)]
    for scope, key, keys in targets + [("company", "agent", AGENT_P5)]:
        role = Role.objects.filter(scope=scope, key=key).first()
        if role:
            role.permissions = sorted(set(role.permissions) | set(keys))
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("rbac", "0008_phase5_voice_settings")]
    operations = [migrations.RunPython(add, migrations.RunPython.noop)]
