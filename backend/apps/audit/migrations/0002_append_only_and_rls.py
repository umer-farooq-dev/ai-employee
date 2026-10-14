from django.db import migrations

from apps.core.sql import TENANT_CONDITION, postgres_only

# SEC-08: the audit log cannot be changed or deleted, not even by the application.
APPEND_ONLY = """
CREATE OR REPLACE FUNCTION audit_block_change() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'audit log is append-only'; END $$ LANGUAGE plpgsql;
CREATE TRIGGER audit_no_change BEFORE UPDATE OR DELETE ON audit_auditlog
FOR EACH ROW EXECUTE FUNCTION audit_block_change();
"""

# Companies only read their own entries; anyone may append.
RLS = f"""
ALTER TABLE audit_auditlog ENABLE ROW LEVEL SECURITY; ALTER TABLE audit_auditlog FORCE ROW LEVEL SECURITY;
CREATE POLICY audit_read ON audit_auditlog FOR SELECT USING ({TENANT_CONDITION});
CREATE POLICY audit_append ON audit_auditlog FOR INSERT WITH CHECK (true);
"""


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]
    operations = [
        postgres_only(APPEND_ONLY, "DROP TRIGGER IF EXISTS audit_no_change ON audit_auditlog;"),
        postgres_only(RLS, "DROP POLICY IF EXISTS audit_read ON audit_auditlog; "
                           "DROP POLICY IF EXISTS audit_append ON audit_auditlog; "
                           "ALTER TABLE audit_auditlog DISABLE ROW LEVEL SECURITY;"),
    ]
