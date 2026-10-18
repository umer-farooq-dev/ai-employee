from django.db import migrations

from apps.core.sql import tenant_rls


class Migration(migrations.Migration):
    dependencies = [("voice", "0001_initial")]
    operations = [tenant_rls("voice_call")]
