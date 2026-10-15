from django.db import migrations

from apps.industries.seeds import ROLES


def seed(apps, schema_editor):
    EmployeeRole = apps.get_model("roles_tools", "EmployeeRole")
    for order, (key, name, description, instructions, channels) in enumerate(ROLES):
        EmployeeRole.objects.get_or_create(key=key, defaults={
            "name": name, "description": description, "instructions": instructions, "allowed_channels": channels,
            "sort_order": order})


class Migration(migrations.Migration):
    dependencies = [("roles_tools", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
