# AI Employee Platform

Django 5.2 backend with the eSoft website template and the Rizz admin template. Design docs and the development checklist are in [docs/](docs/START_HERE.md).

## Run locally

```bash
python -m venv .venv
.venv/Scripts/pip install -r backend/requirements/dev.txt   # Linux/macOS: .venv/bin/pip
cp .env.example .env                                         # then set SECRET_KEY
docker compose up -d                                         # Postgres + pgvector, Redis, Mailpit
python backend/manage.py migrate
python backend/manage.py createsuperuser
python backend/manage.py runserver
```

- Website: http://localhost:8000/ · Super Admin: http://localhost:8000/superadmin/ · Company panel: http://localhost:8000/app/ · API docs: http://localhost:8000/api/v1/docs/
- Emails: http://localhost:8025 (Mailpit)
- Free LLM gateway (testing only, after the system is built): `docker compose --profile ai up -d`; it is connected as a provider in Super Admin (Phase 4)

## Database role and backups (any server)

- Migrations run as the database owner. The application itself connects with a least-privilege role (no superuser, cannot
  bypass row-level security): create it once with
  `python backend/manage.py setup_app_db_role --role aiemployee_app --password <secret>` (owner `DATABASE_URL`), then
  point the running app's `DATABASE_URL` at `aiemployee_app`.
- Daily compressed backups: `docker compose --profile backup up -d` writes `./backups/db-*.dump` and keeps
  `BACKUP_KEEP_DAYS` (default 14). Copy them off the server. Point-in-time recovery is set up on the client's hosting (Phase 8).
- Restore: `pg_restore --clean -d <database> backups/db-<date>.dump`

## Code conventions

- **Service layer:** business logic lives in `apps/<app>/services.py` (plain functions). Page views, REST API views,
  Celery tasks and the voice gateway all call these services; views only handle HTTP and templates.
- **Tenant data:** every company-owned model has `company_id`; never take it from user input or AI output.
- **No hard-coding:** business values come from the settings registry or Super Admin data (`docs/phase0/settings-registry.md`).
- **API with every feature:** each feature ships its DRF endpoint, OpenAPI docs and tests in the same pull request.
- **Templates:** website pages extend `website/landing-layout.html`; Super Admin pages extend `panel/admin/layout.html`;
  company panel pages extend `panel/company/layout.html`. `panel/pages/*` are untouched Rizz reference pages.
- **Conventions:** UUID primary keys, times stored in UTC, money in paise, phones in E.164 (+91).

## Checks (same as CI)

```bash
ruff check backend && black --check backend && pytest
```
