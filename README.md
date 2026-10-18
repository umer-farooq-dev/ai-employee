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

- Website: http://127.0.0.1:8000/ · Company panel: http://127.0.0.1:8000/app/ · API docs: http://127.0.0.1:8000/api/v1/docs/
- Super Admin: http://admin.localhost:8000/superadmin/ — its own host (`ADMIN_HOST`), so staff and company / website logins never mix in one browser
- Emails: http://localhost:8025 (Mailpit)
- Free LLM gateway (testing only): `docker compose --profile ai up -d`, then Super Admin → AI Settings → FreeLLMAPI (test only, blocked in production)
- AI Employees need an AI provider: Super Admin → AI Settings → add a key, load models, switch it on, choose the model per task
- Upload virus scan (optional locally): `docker compose --profile scan up -d` and `CLAMAV_ADDRESS=127.0.0.1:3310` in `.env`
- Voice calls: `python backend/manage.py run_voice_gateway` (second process, `VOICE_GATEWAY_BIND`). Providers and keys:
  Super Admin → Voice Settings; who speaks each language: Languages & Voices; numbers: Phone Numbers.
  Free local testing (no keys): `pip install -r backend/requirements/voice-local.txt`, switch on Whisper (local) and
  Kokoro (local), set them as the routes of a language, then use **Voice test** in the AI Employee's test console.
  Real phone calls need public addresses for the webhooks and the gateway (`PUBLIC_BASE_URL`, `VOICE_GATEWAY_URL`, e.g. a tunnel).

## Database role and backups (any server)

- Migrations run as the database owner. The application itself connects with a least-privilege role (no superuser, cannot
  bypass row-level security): create it once with
  `python backend/manage.py setup_app_db_role --role aiemployee_app --password <secret>` (owner `DATABASE_URL`), then
  point the running app's `DATABASE_URL` at `aiemployee_app`.
- Daily compressed backups: `docker compose --profile backup up -d` writes `./backups/db-*.dump` and keeps
  `BACKUP_KEEP_DAYS` (default 14). Copy them off the server. Point-in-time recovery is set up on the client's hosting (Phase 8).
- Restore: `pg_restore --clean -d <database> backups/db-<date>.dump`
- The knowledge base needs the PostgreSQL `vector` extension (pgvector). The migration creates it as the database owner;
  on managed hosting enable "vector" first.
- Scheduled jobs (cron, every 5 minutes):
  - `python backend/manage.py send_task_reminders --base-url https://<domain>` — follow-up reminder emails (CRM-16)
  - `python backend/manage.py process_knowledge` — queued knowledge, website re-syncs, re-embedding (KB-01, KB-07)
  - `python backend/manage.py end_idle_conversations` — closes idle AI conversations so summary, CRM and score update
  - every minute: `python backend/manage.py dial_due_calls` — call retries (busy / no answer / voicemail) and follow-up calls
  - daily: `python backend/manage.py apply_voice_retention` — deletes recordings / voice transcripts past each company's retention
- Voice load test (ENGR-07): `python backend/manage.py voice_load_test --employee <id> --calls 20 --audio caller.wav` against a running gateway.
- AI quality gate (ENG-12): `python backend/manage.py run_ai_eval [--only real-estate] [--output report.json]` on the
  production model (keys in Super Admin); exit code 1 when the thresholds in AI settings are not met.

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
