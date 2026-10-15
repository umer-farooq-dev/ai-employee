from django.db import migrations

from apps.core.sql import tenant_rls

TABLES = ["resource", "availabilityexception", "appointmentcounter", "appointment"]


class Migration(migrations.Migration):
    dependencies = [("scheduling", "0001_initial")]
    operations = [tenant_rls(f"scheduling_{t}") for t in TABLES]
