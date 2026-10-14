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
| 9 | AI extraction PoC report (baseline accuracy) | ⏳ Waiting for keys | `poc/ai_extraction.py` ready; needs FreeLLMAPI provider keys |
| 10 | Voice PoC report + provider per language (VOICE-08) | ⏳ Waiting for keys | `poc/voice_bakeoff.py` ready; needs Sarvam / Google / ElevenLabs keys |
| 11 | Terraform skeleton | ↪ Moved | Built with the staging environment once the AWS account exists (before the Phase 1 gate) |

## What is needed to close the gate
1. FreeLLMAPI: add free provider keys in http://localhost:3001, create a client key, put it in `.env` as `LLM_API_KEY`, run `python poc/ai_extraction.py`.
2. Voice: put at least two of `SARVAM_API_KEY`, `GOOGLE_API_KEY`, `ELEVENLABS_API_KEY` in `.env`, run `python poc/voice_bakeoff.py`, listen to the WAV files and record the provider choice per language.

Phase 1 (Super Admin) work can start in parallel: it does not depend on the PoC results.
