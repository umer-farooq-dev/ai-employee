"""SEC-08 with SEC-12: the audit log stays append-only, but entries older than the retention can be removed.

The only way to delete is audit_purge(cutoff): it runs as the database owner, refuses anything younger than 90 days
(the lowest retention Super Admin allows) and flags the deletion for the trigger and the row-level policy. The
application role cannot delete or change rows itself (no privilege) and may only call this function.
"""

from django.db import migrations

from apps.core.sql import postgres_only

FORWARD = """
CREATE OR REPLACE FUNCTION audit_block_change() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' AND current_setting('app.audit_purge', true) = 'on' THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'audit log is append-only';
END $$ LANGUAGE plpgsql;

CREATE POLICY audit_purge ON audit_auditlog FOR DELETE USING (current_setting('app.audit_purge', true) = 'on');

CREATE OR REPLACE FUNCTION audit_purge(cutoff timestamptz) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE removed bigint;
BEGIN
    IF cutoff > now() - interval '90 days' THEN
        RAISE EXCEPTION 'audit entries younger than 90 days cannot be removed';
    END IF;
    PERFORM set_config('app.audit_purge', 'on', true);
    PERFORM set_config('app.bypass_rls', 'on', true);
    DELETE FROM audit_auditlog WHERE created_at < cutoff;
    GET DIAGNOSTICS removed = ROW_COUNT;
    PERFORM set_config('app.audit_purge', '', true);
    PERFORM set_config('app.bypass_rls', '', true);
    RETURN removed;
END $$;
REVOKE ALL ON FUNCTION audit_purge(timestamptz) FROM PUBLIC;
"""

REVERSE = """
DROP FUNCTION IF EXISTS audit_purge(timestamptz);
DROP POLICY IF EXISTS audit_purge ON audit_auditlog;
CREATE OR REPLACE FUNCTION audit_block_change() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'audit log is append-only'; END $$ LANGUAGE plpgsql;
"""


class Migration(migrations.Migration):
    dependencies = [("audit", "0002_append_only_and_rls")]
    operations = [postgres_only(FORWARD, REVERSE)]
