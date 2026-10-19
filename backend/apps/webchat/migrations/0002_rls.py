from django.db import migrations

from apps.core.sql import tenant_rls


class Migration(migrations.Migration):
    dependencies = [("webchat", "0001_initial")]
    operations = [tenant_rls("webchat_chatwidget")]
