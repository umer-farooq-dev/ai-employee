from django.db import migrations

from apps.core.sql import tenant_rls

TABLES = ["aiemployee", "configversion", "conversation", "message", "toolinvocation", "usageevent"]


class Migration(migrations.Migration):
    dependencies = [("agents", "0001_initial")]
    operations = [tenant_rls(f"agents_{t}") for t in TABLES]
