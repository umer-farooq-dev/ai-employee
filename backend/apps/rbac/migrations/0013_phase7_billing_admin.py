from django.db import migrations

SUPER_ADMIN = ["subscriptions.view", "subscriptions.manage", "usage_reports.view"]
SUPPORT = ["subscriptions.view"]


def add(apps, schema_editor):
    Role = apps.get_model("rbac", "Role")
    for key, keys in (("super_admin", SUPER_ADMIN), ("support", SUPPORT)):
        role = Role.objects.filter(scope="platform", key=key).first()
        if role:
            role.permissions = sorted(set(role.permissions) | set(keys))
            role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("rbac", "0012_phase7_analytics")]
    operations = [migrations.RunPython(add, migrations.RunPython.noop)]
