from django.db import migrations

from apps.core.sql import tenant_rls

TABLES = ["source", "document", "faq", "chunk", "unansweredquestion"]


class Migration(migrations.Migration):
    dependencies = [("knowledge", "0001_initial")]
    operations = [tenant_rls(f"knowledge_{t}") for t in TABLES]
