from django.db import migrations

KEYS = ["tickets.view", "tickets.manage"]


def add(apps, schema_editor):
    Role = apps.get_model("rbac", "Role")
    for role in Role.objects.filter(scope="platform", key__in=("super_admin", "support")):
        role.permissions = sorted(set(role.permissions) | set(KEYS))
        role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("rbac", "0013_phase7_billing_admin")]
    operations = [migrations.RunPython(add, migrations.RunPython.noop)]
