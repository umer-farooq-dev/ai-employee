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

- Website: http://localhost:8000/ · Panel: http://localhost:8000/panel/ · API docs: http://localhost:8000/api/v1/docs/
- Emails: http://localhost:8025 (Mailpit)
- Free LLM gateway (dev only): `docker compose --profile ai up -d`, dashboard at http://localhost:3001

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
