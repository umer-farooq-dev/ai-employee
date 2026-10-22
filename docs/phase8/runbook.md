# Operations Runbook — AI Employee Platform

For the people who run the platform: first deployment, updates, backups, recovery, monitoring and incidents.
Hosting and domain are the client's choice; everything below works on any server that runs Docker
(VPS or cloud VM, 4 vCPU / 8 GB RAM / 80 GB SSD is a sensible start for launch, India region recommended for voice).

Contents: [1 Architecture](#1-what-runs-where) · [2 First deployment](#2-first-deployment) ·
[3 Updates and rollback](#3-updates-and-rollback) · [4 Backups](#4-backups) · [5 Disaster recovery](#5-disaster-recovery-plan) ·
[6 Monitoring](#6-monitoring-and-alerts) · [7 Incidents](#7-incident-playbooks) · [8 Secrets](#8-secrets-and-rotation) ·
[9 Routine tasks](#9-routine-tasks)

---

## 1. What runs where

| Container | Image | Job |
|---|---|---|
| `proxy` | caddy | HTTPS with automatic certificates; serves `/static/` and public `/media/`; routes `<domain>`, `admin.<domain>` → web, `voice.<domain>` → voice |
| `web` | aiemployee-web | Website, company panel, Super Admin, REST API, provider webhooks (gunicorn, 3 workers × 8 threads) |
| `scheduler` | aiemployee-web | Every scheduled job (`run_scheduler`): call retries every minute; reminders, knowledge, idle chats and alerts every 5 min; usage alerts and billing hourly; privacy, tickets and recording retention daily |
| `voice` | aiemployee-voice | Voice Gateway: live phone and browser test calls (one pipeline per call) |
| `migrate` | aiemployee-web | One-off on every rollout: database migrations as the owner, then the least-privilege app role |
| `static` | aiemployee-web | One-off: copies the release's static files for the proxy |
| `db` | pgvector/pgvector:pg16 | PostgreSQL 16 with pgvector — or a managed PostgreSQL (recommended, see §4) |
| `redis` | redis:7 | Cache, sessions, rate limits — or a managed Redis |
| `db-backup` | pgvector/pgvector:pg16 | Daily compressed dump to `deploy/backups/` |

Business settings and **every provider key** (AI, telephony, WhatsApp, Razorpay, e-mail, SMS) live in the database and
are entered in Super Admin. The server only holds infrastructure values (`deploy/.env`).

## 2. First deployment

1. **DNS**: point `<domain>`, `www.<domain>`, `admin.<domain>` and `voice.<domain>` (A / AAAA records) at the server.
2. **Server**: install Docker Engine with the compose plugin; open ports 80 and 443 only (SSH restricted to the team).
3. **Code**: `git clone` the repository (or copy the release), then
   ```bash
   cp deploy/.env.production.example deploy/.env
   ```
   Fill in `deploy/.env`: the domain values, and new random values for `SECRET_KEY`, `FIELD_ENCRYPTION_KEY`,
   `JWT_SIGNING_KEY`, `POSTGRES_PASSWORD`, `APP_DB_PASSWORD`, `REDIS_PASSWORD`
   (`python3 -c "import secrets; print(secrets.token_urlsafe(64))"`). Put the same passwords into the two
   `..._DATABASE_URL` lines and `REDIS_URL`. **Store a copy of `FIELD_ENCRYPTION_KEY` with the backups' secrets** —
   without it the provider keys inside a restored database cannot be read.
4. **Start**:
   ```bash
   docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env up -d --build
   docker compose -f deploy/docker-compose.prod.yml ps        # all "running" / "healthy"; migrate and static "exited (0)"
   curl https://<domain>/healthz/                               # {"status": "ok", "database": "ok", "cache": "ok", "scheduler": "ok"}
   ```
5. **First Super Admin user**:
   `docker compose -f deploy/docker-compose.prod.yml exec web python manage.py createsuperuser`
   then sign in at `https://admin.<domain>/superadmin/` and set up 2FA.
6. **Go-live settings**: work through [go-live-checklist.md](go-live-checklist.md) (providers, security switches,
   GST, plans, e-mail templates).

Using managed PostgreSQL / Redis instead of the containers: create the database with the `vector` extension enabled,
set `OWNER_DATABASE_URL` (owner / admin user), `DATABASE_URL` (the `APP_DB_USER` role, created by `migrate`) and
`REDIS_URL`, and start only `migrate static web scheduler voice proxy`.

## 3. Updates and rollback

Every release is a git tag with a green CI pipeline (tests, security scans, image build, Trivy, production-stack smoke
test, restore drill, load test, ZAP). Deploy to **staging first**, test, then production.

```bash
git fetch --tags && git checkout vX.Y.Z
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env build
docker compose -f deploy/docker-compose.prod.yml --env-file deploy/.env up -d      # migrate runs first, then the new web
```

- Migrations are always backward-compatible (CI checks), so the old code keeps working while they run.
- The Voice Gateway gets 10 minutes (`stop_grace_period`) for calls in progress. Deploy outside calling hours when
  possible.
- **Rollback**: `git checkout <previous tag>` and the same two commands. Database migrations are not reversed (they are
  backward-compatible); if a release's migration itself is faulty, restore per §5.
- Tag the images by version (`IMAGE_WEB=registry/aiemployee-web:vX.Y.Z`) when a registry is used, so production runs
  exactly the image tested on staging.

## 4. Backups

| What | How | Kept |
|---|---|---|
| Database | `db-backup` container: daily `pg_dump -Fc` into `deploy/backups/` | `BACKUP_KEEP_DAYS` (14) |
| Database, point in time | **Managed PostgreSQL with PITR** (target: RPO ≤ 5 min, 35 days) — the daily dump alone gives RPO 24 h | per host |
| Files | Docker volumes `media` (logos, website images) and `private_media` (company files, recordings, exports) | host volume snapshots / daily `tar` (below) |
| Secrets | `deploy/.env` (above all `FIELD_ENCRYPTION_KEY`) | password manager / host secret store |

Off-site copy (daily, from the server):
```bash
docker run --rm -v aiemployee_media:/m -v aiemployee_private_media:/p -v "$PWD/deploy/backups:/b" alpine \
  tar czf /b/files-$(date +%Y%m%d).tgz -C / m p
# then copy deploy/backups/* to storage outside this server (object storage, another region)
```
(Volume names carry the compose project prefix; `docker volume ls` shows them.)

**Restore drill** (quarterly, and after any backup change):
```bash
sh deploy/restore_drill.sh deploy/docker-compose.prod.yml            # takes a fresh dump
sh deploy/restore_drill.sh deploy/docker-compose.prod.yml deploy/backups/db-20261022-0200.dump
```
It restores into a scratch database next to the live one, compares tables, row counts of companies / leads /
invoices, migrations and row-level-security tables, prints the time taken and `RESULT: PASS`. Record the result in the
drill log (§9). The drill also runs on every CI build.

## 5. Disaster recovery plan

Targets: **RPO ≤ 5 minutes** (with managed PITR; 24 h with dumps only), **RTO ≤ 4 hours**.

| Situation | Action |
|---|---|
| A container crashes | Docker restarts it (`restart: unless-stopped`); check `docker compose logs <service>` |
| Bad release | Roll back (§3) |
| Data damaged by a mistake (e.g. wrong bulk delete) | Managed PITR to a new instance just before the mistake, copy the affected rows back; without PITR restore the last dump into a scratch database (`restore_drill.sh` steps) and copy the rows |
| Database server lost | Managed: promote replica / PITR restore. Self-hosted: new server, steps below |
| Whole server / region lost | Steps below |

**Rebuild on a new server** (practised in the restore drill):
1. New server in a healthy region; install Docker; DNS records to the new IP (low TTL helps — set 300 s at launch).
2. Copy the repository at the running release tag and `deploy/.env` from the secret store.
3. `docker compose ... up -d db redis` then restore the latest dump:
   `docker compose ... exec -T db pg_restore -U aiemployee -d aiemployee --clean --if-exists --no-owner < db-<date>.dump`
4. Restore the files archive into the `media` / `private_media` volumes.
5. `docker compose ... up -d` (migrate re-creates the app role and grants), then check `/healthz/`, sign in to Super
   Admin, open a company panel, make a browser test call.
6. Re-point telephony / WhatsApp / Razorpay webhooks only if the domain changed (normally unchanged).
7. Tell companies about the incident if data newer than the backup was lost (time window from the backup time).

## 6. Monitoring and alerts

| Signal | Where |
|---|---|
| Liveness | `https://<domain>/healthz/` → 200 with `"status": "ok"`; `"scheduler": "ok"` when the scheduler ran in the last 5 min. Add an external uptime monitor (e.g. UptimeRobot, Better Stack — free tiers) on this URL with a keyword check for `"scheduler": "ok"`, alerting the on-call phone / e-mail |
| Voice Gateway | `https://voice.<domain>/healthz` |
| Platform alerts | `ops_watch` (scheduler, every 5 min) e-mails the team about error bursts and failing providers, once per cool-down. Super Admin → System Settings → **Monitoring & alerts** sets recipients and thresholds |
| Errors | Super Admin → Logs → Errors (every server error with traceback and request id); optional Sentry with `SENTRY_DSN` |
| API traffic | Super Admin → Logs → API (method, path, status, time, company) |
| Business / health overview | Super Admin dashboard: companies, calls, MRR, billing issues, errors (24 h), provider health |
| Container logs | `docker compose -f deploy/docker-compose.prod.yml logs -f web` (JSON lines with `request_id`; rotated, 5 × 20 MB per container) |
| Usage alerts to companies | Hourly (`send_usage_alerts`), levels in System Settings → Team alerts |

Every response carries `X-Request-ID`; search the logs and Super Admin → Logs by it when a user reports a problem.

## 7. Incident playbooks

**Site down / 502**: `docker compose ps` → which service is unhealthy → `logs --tail 200 <service>`. Database or cache
down → `/healthz/` shows which. Disk full → `df -h`; prune old images `docker image prune -a` (keeps running ones) and
old backups after copying them off-site.

**AI not answering**: Super Admin → AI Settings → provider health / key; check the routes' fallback order; Logs →
Errors for provider messages. Companies on billing hold or with no AI credits are paused on purpose (Billing pages).

**Calls fail**: Voice Settings → provider health; `voice` container logs; `wss://voice.<domain>` reachable from the
internet (provider console shows media errors); `PUBLIC_BASE_URL` / `VOICE_GATEWAY_URL` correct.

**WhatsApp / Razorpay webhooks failing**: Logs → API for `/webhooks/...` statuses (401/403 = wrong secret in Super
Admin); the provider's console re-sends failed events once fixed.

**E-mails not arriving**: Voice & Channels → E-mail (SMTP) health, sender address verified with the mail provider
(SPF / DKIM on the domain); `.env` `EMAIL_URL` is only the fallback.

**Security incident** (leaked key, suspicious admin activity): rotate the key in Super Admin (provider) or `.env` (§8);
Super Admin → Sessions → end the sessions; Users → lock the account; Logs → Audit to see what was done; tell the client.

**Maintenance window**: Super Admin → General Settings → Maintenance mode shows the maintenance page to websites and
company panels while Super Admin keeps working.

## 8. Secrets and rotation

| Secret | Where | Rotation |
|---|---|---|
| Provider keys (AI, telephony, WhatsApp, Razorpay, SMTP, SMS) | Super Admin, encrypted in the database | Replace in Super Admin, then revoke the old key at the provider |
| `SECRET_KEY` | `deploy/.env` | Change and restart `web scheduler voice`: everyone signs in again, signed links expire |
| `JWT_SIGNING_KEY` | `deploy/.env` | Change and restart: app users sign in again |
| `FIELD_ENCRYPTION_KEY` | `deploy/.env` + secret store | Do not change casually: stored provider keys become unreadable; re-enter all provider keys after a change |
| Database / Redis passwords | `deploy/.env` (+ managed service) | Change in the service and `.env`, restart |
| Staff accounts | Super Admin → Users | 2FA required for staff (go-live checklist); remove leavers the same day |

`.env` files are never committed (gitleaks checks every push).

## 9. Routine tasks

| When | Task |
|---|---|
| Daily | Check the uptime monitor and the ops alert inbox; Super Admin dashboard errors (24 h) near zero |
| Weekly | Confirm the newest backup files reached the off-site storage; review Logs → Errors; disk space (`df -h`) |
| Monthly | Apply the latest release (security fixes from Dependabot / pip-audit / Trivy); review Super Admin users and roles |
| Quarterly | Restore drill (§4) and record it below; access review of staff; test the DR steps on staging |
| Yearly | External penetration test |

**Drill log**

| Date | Dump | Restore time | Result | By |
|---|---|---|---|---|
| 2026-10-22 | Development database (744 KB) | 26 s (drill 30 s) | PASS — 102 tables, counts and 54 RLS tables equal | Dev team |
