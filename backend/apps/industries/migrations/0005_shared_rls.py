from django.db import migrations

from apps.core.sql import shared_rls

TABLES = ["fielddefinition", "catalogtype", "appointmenttype", "leadstatus", "scoringrule"]


class Migration(migrations.Migration):
    dependencies = [("industries", "0004_seed_phase3")]
    operations = [shared_rls(f"industries_{t}") for t in TABLES]
