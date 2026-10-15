from django.db import migrations

from apps.core.sql import tenant_rls

TABLES = ["catalogitem", "catalogmedia", "catalogcollection", "collectionitem", "catalogimport"]


class Migration(migrations.Migration):
    dependencies = [("catalog", "0001_initial")]
    operations = [tenant_rls(f"catalog_{t}") for t in TABLES]
