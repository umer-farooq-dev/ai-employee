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

## Checks (same as CI)

```bash
ruff check backend && black --check backend && pytest
```
