from django.db import migrations

from apps.core.sql import tenant_rls

TABLES = ["leadcounter", "lead", "leadactivity", "leadnote", "leadscoreevent", "task", "assignmentrule",
          "consentrecord", "leadimport", "savedview"]


class Migration(migrations.Migration):
    dependencies = [("crm", "0001_initial")]
    operations = [tenant_rls(f"crm_{t}") for t in TABLES]
