# Phase 0 Gate Report

Gate rule (PRD-01 Section 4): a phase exits only when every criterion passes.

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Architecture, scope, cost and milestones approved by client | ✅ Done | Client approval received |
| 2 | Repository, branch `main`, GitHub remote | ✅ Done | github.com/umer-farooq-dev/ai-employee |
| 3 | GitHub CI green (lint, migrations, tests, Bandit, pip-audit, gitleaks) | ✅ Done | Actions run on `main` |
| 4 | Django 5.2 project, custom User in first migration, no Django admin | ✅ Done | `backend/`, tests in `backend/tests/` |
| 5 | Local services (Postgres + pgvector, Redis, Mailpit, FreeLLMAPI) | ✅ Done | `docker compose ps` |
| 6 | Templates imported, website and panel base layouts | ✅ Done | `/` (eSoft HR), `/superadmin/`, `/app/` |
| 7 | Website section mapping sheet | ✅ Done | `docs/phase0/website-section-mapping.md` |
| 8 | Settings registry list | ✅ Done | `docs/phase0/settings-registry.md` |
| 9 | Voice and AI PoC run | ↪ Deferred (owner decision) | Scripts ready in `poc/`; run after the system is built, with providers and keys added in Super Admin (Phase 4 / 5) |

**Owner decisions recorded at this gate**
- Provider keys are entered only in Super Admin, never in `.env` or code.
- Hosting server and domain are the client's choice at deployment (Phase 8); the system stays hosting-agnostic.
- Work follows PRD-01 phase by phase; nothing is pulled into an earlier phase.

Next: **Phase 1 — Core Platform & Super Admin First.**
