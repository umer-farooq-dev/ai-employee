from django.db import migrations

ADD = ["crm_config.manage", "employee_roles.manage", "holidays.manage"]


def add(apps, schema_editor):
    Role = apps.get_model("rbac", "Role")
    role = Role.objects.filter(scope="platform", key="super_admin").first()
    if role:
        role.permissions = sorted(set(role.permissions) | set(ADD))
        role.save(update_fields=["permissions"])


class Migration(migrations.Migration):
    dependencies = [("rbac", "0003_phase2_permissions")]
    operations = [migrations.RunPython(add, migrations.RunPython.noop)]
