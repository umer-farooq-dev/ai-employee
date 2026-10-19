from django.db import migrations

from apps.core.sql import tenant_rls


class Migration(migrations.Migration):
    dependencies = [("campaigns", "0001_campaigns")]
    operations = [tenant_rls("campaigns_campaign"), tenant_rls("campaigns_campaignmember")]
