from django.db import migrations


def add(apps, schema_editor):
    Role = apps.get_model("rbac", "Role")
    role = Role.objects.filter(scope="platform", key="super_admin").first()
    if role:
        role.permissions = sorted(set(role.permissions) | {"voice_settings.manage"})
        role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("rbac", "0007_phase4_permissions")]
    operations = [migrations.RunPython(add, migrations.RunPython.noop)]
