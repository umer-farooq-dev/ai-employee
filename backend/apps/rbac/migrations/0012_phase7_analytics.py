from django.db import migrations

KEYS = ["analytics.view"]


def add(apps, schema_editor):
    Role = apps.get_model("rbac", "Role")
    for role in Role.objects.filter(scope="company", key__in=("owner", "manager")):
        role.permissions = sorted(set(role.permissions) | set(KEYS))
        role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("rbac", "0011_phase6_campaigns")]
    operations = [migrations.RunPython(add, migrations.RunPython.noop)]
