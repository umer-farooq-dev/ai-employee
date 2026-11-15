# Phase 8 Gate — Hardening, Security, Performance & Production Launch

Scope from PRD-01 Phase 8 (client milestone 9: testing + security + deployment). **Done** = built and verified;
**CI** = runs on every push (verified when the branch is pushed); **Staging** / **Client** = needs the client's server,
accounts or decision. Hosting and domain stay the client's choice; nothing provider-specific was built.

## 1. Production deployment (ENGR-03, ENGR-04)

| Item | Status | Where |
|---|---|---|
| Container images | Done · CI builds | `Dockerfile`: `web` (gunicorn, static files collected at build) and `voice` (Voice Gateway) targets, non-root user, health checks |
| Production stack | Done · CI boots it | `deploy/docker-compose.prod.yml`: migrate (owner) → least-privilege app role, web, scheduler, voice, Caddy (automatic HTTPS, static / media, `admin.` and `voice.` hosts), PostgreSQL + pgvector, Redis (password, AOF), daily backups. Managed DB / Redis supported |
| Scheduler | Done | `run_scheduler`: every cron job in one process (one thread per job, skipped while busy); `--once` for smoke tests; heartbeat shown on `/healthz/` |
| Health checks | Done | `/healthz/` checks database + cache (503 when down) and reports the scheduler; gateway `/healthz` |
| Production settings | Done | Refuses missing hosts, weak `SECRET_KEY`, `FIELD_ENCRYPTION_KEY` equal to it; HSTS preload, secure cookies, COOP, referrer policy, framing denied; `check --deploy` has no security warnings (CI) |
| Environments | Done · **Client** (servers) | Local (docker-compose.yml), staging and production from the same compose file and `deploy/.env.production.example` |

## 2. Security (SEC-15)

| Check | Result |
|---|---|
| SAST (bandit) | No findings (CI on every push) |
| Dependencies (pip-audit) | Web / production requirements: no known vulnerabilities. Voice Gateway: pipecat pins `Pillow<13` (8 CVEs in Pillow 12) → the gateway now installs Pillow 13 over it; all voice tests and the bakeoff self-test pass on it |
| Secrets (gitleaks) | Clean (CI). Review: provider keys only in Super Admin (encrypted); `.env` never committed; `FIELD_ENCRYPTION_KEY` now must differ from `SECRET_KEY` so `SECRET_KEY` can rotate without losing stored keys |
| Container scan (Trivy) | **CI**: both images, fails on fixable HIGH / CRITICAL |
| DAST (OWASP ZAP baseline) | **CI**: website and Super Admin on the running production stack, fails on any high-risk alert; reports kept as build artifacts |
| Deployment checks | `manage.py check --deploy` with production settings: 0 security warnings |
| External penetration test | **Client** — before launch, by an outside firm |

## 3. Performance (ENGR-07)

The k6 API test (`deploy/loadtest/`) found that ~45 % of every API request was fixed overhead. Fixed:

| Cause | Fix | Effect (dev server, per request) |
|---|---|---|
| Every setting read fetched and unpickled the whole settings set from Redis (15–45 times per request) | Read once per request | Website home: 55 ms of settings reads removed |
| allauth wrote the session's "last seen" to the database on **every** request | Once a minute, or at once when the IP / browser changes (new-device detection kept) | One write transaction less per request |
| Sessions read from the database | Redis-cached sessions (`cached_db`; revocation clears both) | One query less |

API timings after the fix (single request, dev server): company 106 → 57 ms, leads 238 → 101 ms, calendar 105 → 75 ms,
notifications 150 → 58 ms; 6 fewer queries each.

| Test | Result |
|---|---|
| Local functional run (5 users, 1 min, Windows dev server) | 450 requests, 0 errors, all checks passed |
| CI regression gate (gunicorn production stack, 10 companies, 30 users, 90 s) | **CI** — thresholds: errors < 1 %, API p95 < 800 ms, pages p95 < 1.5 s |
| Launch targets (500 companies, 100 concurrent calls) | **Staging** — same script with `VUS` raised on the client's server size; voice: `voice_load_test --calls 100` with the live speech keys |

Noted, not changed: the billing summary makes ~50 queries (limits read per meter) — a rarely opened page; optimise if
it shows in the staging run.

## 4. Reliability (SEC-10, ENGR-05, ENGR-08)

| Item | Status | Where |
|---|---|---|
| Restore drill | Done (dev: **PASS**, restore 26 s, whole drill 30 s; 102 tables, row counts and 54 RLS tables equal) · CI every build | `deploy/restore_drill.sh` |
| DR plan | Done | runbook §5: RPO ≤ 5 min with managed PITR (24 h with dumps), RTO ≤ 4 h, rebuild steps |
| Platform alerts | Done | `ops_watch` every 5 min: error bursts and failing providers e-mailed once per cool-down; System Settings → Monitoring & alerts; e-mail template "Platform alert" |
| Uptime monitoring | **Client** | External monitor on `/healthz/` with keyword `"scheduler": "ok"` (runbook §6) |
| Error tracking | Done (optional) | Super Admin → Logs → Errors; Sentry with `SENTRY_DSN` |

## 5. Regression of Phases 1–7 and device testing

| Check | Result |
|---|---|
| Automated tests | **327 passed** (lint, format and migrations clean) |
| Crawler, three roles | Visitor 19, company owner 142, Super Admin 254 pages and every link from them: **no server error, no 404**, no raw template text (one intentional "None" choice in the campaign form) |
| Device matrix (Playwright) | 31 main pages of website, company panel and Super Admin × desktop 1920, laptop 1366, tablet 810, Android 412, iPhone 390 = **155 page views: no sideways scroll, no JavaScript error, no failed request** |
| Phase 7 browser test (Chrome) | Plans CRUD, enterprise terms, credits, plan-period invoice, PDF, mark paid, hold / release, cancel, usage & margin, support reply / note / assign / status, settings, providers — 1 bug and 5 design issues found and fixed (commit b800851) |
| OpenAPI | 7 endpoints were missing from the API docs (sessions, uploads, AI routes, knowledge test, calling policy, two admin views) → documented; 2 schema name collisions fixed |

## 6. Documentation and handover

| Document | For |
|---|---|
| [runbook.md](runbook.md) | Operations: deployment, updates / rollback, backups, DR plan, monitoring, incident playbooks, secrets, routine tasks, drill log |
| [go-live-checklist.md](go-live-checklist.md) | Production settings review — every Super Admin screen and provider, sign-off table |
| [user-guide.md](user-guide.md) | Companies (owners, managers, agents) |
| [admin-guide.md](admin-guide.md) | The platform team (Super Admin) |
| [api-guide.md](api-guide.md) | Mobile app and integration developers |
| `docs/phase0/settings-registry.md` | Updated: retention / privacy keys, monitoring group |

## 7. Waiting for the client

- Hosting provider, region, server size; domain and DNS; managed PostgreSQL with PITR (recommended) or dumps only.
- Staging server for UAT, DAST on staging and the launch-size load / voice tests.
- Live provider accounts: AI, telephony, WhatsApp, Razorpay, SMTP, MSG91 (DLT) — then the Phase 7 Razorpay test list.
- GST details, plan prices, provider prices (go-live checklist B–E).
- External penetration test; UAT sign-off and go-live approval.
