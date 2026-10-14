# Phase 1 Gate — Core Platform & Super Admin First

Scope from PRD-01 Phase 1. Status: **Done**, or **Done (base)**, which means the parts for this phase are built and the rest arrives in the phase named.

## Features

| ID | Feature | Status | Where |
|---|---|---|---|
| AUTH-03 | Login & sessions | Done | allauth login, remember-me, inactivity timeout (setting), active sessions list + sign-out (usersessions) |
| AUTH-04 | Password recovery | Done | reset by email link, change from profile; staff can send a reset |
| AUTH-05 | Two-factor authentication | Done | TOTP + recovery codes; staff enforcement is a setting, **off during development, switched on at launch (P8)**; enforceable per company or platform-wide |
| AUTH-06 | Brute-force protection | Done | lockout per account and per IP, attempts/minutes from Security settings; unlock from Users |
| AUTH-08 | User profile | Done | name, phone (+91), avatar, timezone, notification prefs, availability |
| AUTH-11 | Role-based access control | Done | permission catalogue in code, roles as data, Roles & Permissions screen |
| TEN-01 | Company-level isolation | Done | `company_id` manager (fails closed) + PostgreSQL RLS |
| TEN-02 | Tenant resolution per channel | Done (base) | panels and API from the signed-in user; calls / WhatsApp / widget in P5–P6 |
| TEN-03 | Isolated file storage | Done | private storage per company, short-lived signed URLs |
| TEN-05 | Automated isolation tests | Done | `tests/test_tenancy_isolation.py`, `tests/test_api.py` (run in CI) |
| TEN-06 | Company suspension | Done | suspend / reactivate / soft delete; suspended users blocked at login, panel and API |
| SA-01 | Built on our template | Done | custom Super Admin on Rizz, light theme, no `django.contrib.admin` |
| SA-03 | Companies | Done | list, create, edit, members, suspend, export, support login with banner + audit |
| SA-04 | Users | Done | create, roles, reset password, lock / unlock, reset 2FA, end sessions, deactivate |
| SA-12 | Plans & pricing | Done | plans, prices (paise), GST, trial, limits; payments in P7 |
| SA-16 | System settings | Done (base) | registration, password, session, lockout, 2FA, uploads, API limits; retention / calling in their phases |
| SA-17 | Logs | Done (base) | audit, error and API logs, searchable; webhook and call-event logs in P5–P6 |
| SA-18 | Security | Done | staff roles, mandatory 2FA, IP allowlist, sessions, security events in audit log |
| SA-21 | General Settings menu | Done | Super Admin → General Settings |
| SA-22 | Branding | Done | name, logos, favicon, colours, "Powered by" text |
| SA-23 | Branding shown everywhere | Done (base) | website, panels, login pages, emails; invoices (P7) and widget (P6) read the same values |
| SA-24 | Contact & company details | Done | support email / phone, WhatsApp, address, GSTIN / PAN, social links, copyright |
| SA-25 | Localisation defaults | Done | timezone, currency, number format, language |
| SA-26 | SEO & email defaults | Done | meta title / description / OG image, analytics IDs, sender name and address, email header / footer |
| SA-27 | Maintenance mode | Done | website and company panel show the maintenance page; Super Admin stays open |
| WEB-04 | Website content management | Done | CMS: every section, draft / publish, versions + restore, order, show / hide, SEO, legal pages; the website renders from it in P2 |
| WEB-09 | Section mapping | Done | `docs/phase0/website-section-mapping.md` → 14 section types |
| SUB-01 | Plans managed in Super Admin | Done | |
| SUB-02 | Seed plans | Done | Starter, Business, Pro, Enterprise (seed only, editable) |
| SEC-01 | HTTPS | Done | `settings/production.py`: SSL redirect, HSTS, secure cookies; TLS is set up on the client's hosting (P8) |
| SEC-02 | Secure authentication | Done | Argon2, 2FA, lockout, session controls |
| SEC-03 | Role-based access | Done | checks in panel views, API and object level (company scope) |
| SEC-04 | API key protection | Done (base) | encrypted field ready; provider key screens arrive with their phase (P4–P7), never in `.env` |
| SEC-05 | Database access control | Done | RLS + `setup_app_db_role` (least-privilege role); DB on private network at hosting (P8) |
| SEC-06 | Company-level data isolation | Done | see TEN-01 |
| SEC-07 | Encryption | Done (base) | field encryption (2FA secrets, future keys); disk / backup encryption on the client's hosting (P8) |
| SEC-08 | Audit logs | Done | append-only (DB trigger), who / what / when / IP / impersonator |
| SEC-09 | Rate limiting | Done (base) | per IP, user, company (settings); widget and webhook limits in P5–P6 |
| SEC-10 | Backups | Done (base) | daily `pg_dump` service (`--profile backup`); PITR and restore drill in P8 |
| NOTI-01 | Transactional emails | Done (base) | account emails from DB templates (editable); invoice / usage emails in P7 |
| ENGR-05 | Monitoring & alerting | Done (base) | JSON logs, error log in DB, request IDs, Sentry when `SENTRY_DSN` is set; metrics / alerts at hosting (P8) |
| ENGR-06 / API-03 | API documentation | Done | OpenAPI at `/api/v1/schema/`, docs at `/api/v1/docs/` |
| API-01 | REST API for every feature | Done | `/api/v1/` (admin + company), `/public/v1/` (branding, pages, plans) |
| API-02 | Mobile-ready authentication | Done | allauth headless with JWT access / refresh at `/api/v1/auth/` |
| API-04 | Stable versioning | Done | `/api/v1/`, `/public/v1/` |
| API-06 | Mobile-friendly responses | Done | cursor pagination, filters, signed file URLs, one error format |
| API-07 | API tests every phase | Done | `tests/test_api.py` + isolation tests in CI |

Signup is closed until Phase 2 (company registration, AUTH-01), and the login page hides the sign-up link until then.

## Gate checklist

- [x] Automated tests: `pytest` green on PostgreSQL (RLS and least-privilege role tested)
- [x] Lint and format: ruff, black, `makemigrations --check`
- [x] Security scans: Bandit (0 issues), pip-audit (no known vulnerabilities), gitleaks
- [x] No-hard-coding review: business values come from the settings registry or Super Admin data; `.env` holds only infrastructure
- [x] GitHub CI green on the pushed commit (run 38579579041)
- [ ] Device testing: Super Admin on desktop, tablet and phone browsers
- [x] Client UAT — approved (owner confirmed 2026-10-14)
- [x] Client sign-off — approved (owner confirmed 2026-10-14)
