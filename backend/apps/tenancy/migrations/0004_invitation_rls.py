from django.db import migrations

from apps.core.sql import tenant_rls


class Migration(migrations.Migration):
    dependencies = [("tenancy", "0003_company_approved_at_company_approved_by_and_more")]
    operations = [tenant_rls("tenancy_invitation")]
