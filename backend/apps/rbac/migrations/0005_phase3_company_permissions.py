from django.db import migrations

from apps.rbac.catalog import AGENT_P3, COMPANY_KEYS, MANAGER_P3

ADD = {"owner": COMPANY_KEYS, "manager": MANAGER_P3, "agent": AGENT_P3}


def add(apps, schema_editor):
    Role = apps.get_model("rbac", "Role")
    for key, keys in ADD.items():
        role = Role.objects.filter(scope="company", key=key).first()
        if role:
            role.permissions = sorted(set(role.permissions) | set(keys))
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("rbac", "0004_phase3_platform_permissions")]
    operations = [migrations.RunPython(add, migrations.RunPython.noop)]
