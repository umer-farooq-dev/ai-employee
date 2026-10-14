"""SEC-05: create / update the least-privilege PostgreSQL role the application connects with.

Run once per environment as the database owner (the role that runs migrations):
    python manage.py setup_app_db_role --role aiemployee_app --password <secret>
Then point DATABASE_URL at that role. It can read and write data but is not a superuser, cannot bypass row-level
security, cannot create databases or roles, and cannot change the schema.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from psycopg import sql


class Command(BaseCommand):
    help = "Create or update the least-privilege application database role"

    def add_arguments(self, parser):
        parser.add_argument("--role", required=True)
        parser.add_argument("--password", required=False, help="Omit to create a role without login (tests)")

    def handle(self, role, password=None, **options):
        if connection.vendor != "postgresql":
            raise CommandError("PostgreSQL only")
        name = sql.Identifier(role)
        attrs = sql.SQL("NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE")
        login = sql.SQL("LOGIN PASSWORD {}").format(sql.Literal(password)) if password else sql.SQL("NOLOGIN")
        db = sql.Identifier(connection.settings_dict["NAME"])
        with connection.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role])
            verb = "ALTER" if cur.fetchone() else "CREATE"
            cur.execute(sql.SQL(verb + " ROLE {} {} {}").format(name, attrs, login))
            for statement in (
                "GRANT CONNECT ON DATABASE {db} TO {role}",
                "GRANT USAGE ON SCHEMA public TO {role}",
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}",
                "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}",
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {role}",
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {role}",
                "REVOKE UPDATE, DELETE ON audit_auditlog FROM {role}",  # append-only, also enforced by a trigger
            ):
                cur.execute(sql.SQL(statement).format(db=db, role=name))
        self.stdout.write(self.style.SUCCESS(f"{verb.lower()}d least-privilege role {role}"))
