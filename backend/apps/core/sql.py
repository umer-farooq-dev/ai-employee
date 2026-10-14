"""PostgreSQL row-level security helpers used by migrations (TEN-01 / SEC-05)."""

from django.db import migrations

TENANT_CONDITION = (
    "current_setting('app.bypass_rls', true) = 'on' " "OR company_id::text = current_setting('app.company_id', true)"
)


def postgres_only(sql, reverse_sql=""):
    """RunSQL that is skipped on non-PostgreSQL databases."""

    def forward(apps, schema_editor):
        if schema_editor.connection.vendor == "postgresql":
            schema_editor.execute(sql)

    def backward(apps, schema_editor):
        if schema_editor.connection.vendor == "postgresql" and reverse_sql:
            schema_editor.execute(reverse_sql)

    return migrations.RunPython(forward, backward)


def tenant_rls(table):
    """Every company-owned table: rows visible / writable only for the current company (or explicit platform bypass)."""
    return postgres_only(
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY; ALTER TABLE {table} FORCE ROW LEVEL SECURITY; "
        f"CREATE POLICY tenant_isolation ON {table} USING ({TENANT_CONDITION}) WITH CHECK ({TENANT_CONDITION});",
        f"DROP POLICY IF EXISTS tenant_isolation ON {table}; ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;",
    )
