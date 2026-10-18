# START HERE — Development Checklist

Yeh file development shuru karne ki poori checklist hai. Har item ka detail in do docs mein hai:
- `docs/01_AI_Employee_Product_Requirements_and_Phase_Plan.pdf` (PRD-01: features, phases, gates)
- `docs/02_AI_Employee_System_Design_and_Architecture.pdf` (SDD-02: technical design)

Client approval mil chuki hai (architecture, scope, cost, milestones).

---

## Step 0 — Development se pehle (aap ki taraf se)

**Machine**
- [x] Docker Desktop + WSL2 install (Postgres + pgvector, Redis, Mailpit, FreeLLMAPI isi mein chalte hain)
- [x] Python 3.12, Git, Node (sirf Rizz build ke liye) — installed

**Accounts & keys** — aap / client handle karenge. Har provider ki key **sirf Super Admin** mein daali jayegi, jab us provider ki screen apne phase mein banegi (kabhi `.env` mein nahi).
- [x] GitHub private repo: github.com/umer-farooq-dev/ai-employee
- Hosting server aur domain: **client ka faisla**, deployment ke waqt (Phase 8)

**Licenses**
- [x] eSoft aur Rizz ka commercial / SaaS license confirm

---

## Phase 0 — Setup (PRD-01 Phase 0)

**Project skeleton**
- [x] `git init`, `.gitignore` (`.env`, media, `__pycache__`, `node_modules`)
- [x] GitHub remote connect + first commit (CI green)
- [x] Django 5.2 LTS project: `backend/config/settings/{base,local,production}.py`
- [x] **Custom User model PEHLI migration se pehle** (email login, +91 phone, UUID primary key)
- [x] `django.contrib.admin` install **nahi** karna
- [x] Pinned `requirements` (Django, DRF, drf-spectacular, django-allauth[mfa], psycopg, redis, django-environ; Celery / Channels / pgvector apne phase mein)
- [x] `docker-compose.yml`: postgres+pgvector, redis, mailpit, freellmapi
- [x] `.env.example` (koi secret git mein nahi)
- [x] `accounts` app (custom User). Baqi apps (`tenancy`, `rbac`, `platform_config`, `cms`, `audit`) Phase 1 mein code ke saath
- [x] Service layer convention: `apps/<app>/services.py` (README → Code conventions)

**Quality from day 1**
- [x] pre-commit: ruff, black, gitleaks (djLint baad mein, jab templates hamare apne ho jayein)
- [x] pytest + ek smoke test
- [x] GitHub Actions CI: lint → tests → migrations check → security scans (Bandit, pip-audit, Gitleaks) — **green**

**Templates**
- [x] Rizz: `npm install && npm run build` (ek dafa) → compiled CSS/JS
- [x] eSoft → `templates/website/`, `static/website/`
- [x] Rizz → `templates/panel/`, `static/panel/`
- [x] Copy **nahi** karna: Docs folders, `db.sqlite3`, RTL, extra locales, baqi 8 demo homepages, UI-kit showcase pages
- [x] Website base layout: shared header (`partials/header.html`) + CTA + footer; home = `pages/home.html` (index5 sections)
- [x] Panel base layout: `/superadmin/` (staff only) aur `/app/` (company) — alag sidebars, shared topbar + footer

**Mapping & PoC**
- [x] Template mapping sheet → `docs/phase0/website-section-mapping.md`
- [x] Settings registry list → `docs/phase0/settings-registry.md`
- [x] FreeLLMAPI container chalu (http://localhost:3001)
- [x] Voice PoC script ready: `poc/voice_bakeoff.py`
- [x] AI PoC script ready: `poc/ai_extraction.py` (10 Hinglish / Hindi / Bengali / English cases)
- ↪ Voice / AI PoC **run deferred** (owner decision): testing poora system banne ke baad, providers aur keys Super Admin se

**Phase 0 gate:** CI green · mapping sheet · settings registry · (PoC run deferred by owner)

---

## Phase 1 — Core + Super Admin pehle (is order mein)

1. [x] Auth: allauth login, 2FA (staff ke liye mandatory), lockout, password reset, sessions (AUTH-03..06, 08, 11)
2. [x] Tenancy: `Company` model, `company_id` scoping manager, PostgreSQL RLS, isolation tests (TEN-01..03, 05, 06)
3. [x] Super Admin layout on Rizz + login + IP allowlist (SA-01, SA-18)
4. [x] **General Settings**: naam, logo, favicon, colours, contact, footer, SEO, localisation, email sender, maintenance mode (SA-21..27)
5. [x] **Website CMS**: `index5` ke har section ka editor — headings, text, images, buttons, order, show/hide (WEB-04, WEB-09)
6. [x] Companies + users screens, suspend, impersonation with audit (SA-03, SA-04)
7. [x] Roles & permissions (AUTH-11)
8. [x] Plans & pricing data (SUB-01, SUB-02, SA-12)
9. [x] Audit logs, system logs (SA-17, SEC-08)
10. [x] Email templates + account emails (NOTI-01)
11. [x] Har feature ki REST API + OpenAPI docs + API tests (API-01..04, 06, 07)

**Phase 1 gate:** tests → GitHub CI green → security check → no-hard-coding review → device testing → client UAT (demo server jo client ke saath tay ho) → client sign-off

_AI Providers screen (SA-09) Phase 4 mein hai, Voice / channel providers (SA-10) Phase 5-7 mein — pehle nahi._

---

## Phase 2 — Website, Company Registration & Company Panel

1. [x] Website (eSoft index5) har section CMS se, animations, Lighthouse 90+ (WEB-01, WEB-04)
2. [x] Website pages: How It Works, AI Employee Types, Industries, Features, Pricing (live plans), About, Contact / Demo, FAQ (WEB-02)
3. [x] Legal pages CMS se (WEB-03)
4. [x] Get Started → registration (WEB-05); Contact / demo form → Platform Enquiries inbox + email (WEB-06)
5. [x] SEO: meta / OG, sitemap.xml, robots.txt, structured data (WEB-07); responsive + accessible + reduced motion (WEB-08)
6. [x] Company registration (AUTH-01) + email verification / mobile OTP switch (AUTH-02)
7. [x] **Super Admin approval** (AUTH-12): pending company sirf status page dekhe; approve / reject with reason, email, audit; `registration.approval_required` setting
8. [x] Team: invite, roles, resend / cancel, deactivate, ownership transfer, plan seat limit (AUTH-07)
9. [x] Company profile (AUTH-09) + settings ka pehla hissa: business hours, holidays (CP-06)
10. [x] Onboarding checklist (AUTH-10)
11. [x] Company panel shell on Rizz, menus per role / plan (CP-01, CP-02)
12. [x] Har feature ki REST API + tests

**Phase 2 gate:** E2E (register → verify → pending → approve → login → invite) · website section badlo → bina deployment dikhe · no hard-coded text review · Lighthouse 90+ · device testing · CI green · client sign-off

_Approval par AI Employee template se khud banna (EMP-14) Phase 4 mein — AI engine wahin banta hai._

---

## Phase 3 — Configuration Engine, CRM, Catalogues & Calendar

1. [x] Industry templates: industries, versions (draft → published → archived), company upgrade / rollback, clone, activate / deactivate (IND-01..05, SA-05)
2. [x] MVP templates: Real Estate, Travel & Tours, Education — fields, catalogue, appointment types, scoring, greetings EN / HI / BN, FAQs, WhatsApp templates (IND-06; AI tuning Phase 4)
3. [x] AI Employee role templates (ROLE-01)
4. [x] CRM: leads, statuses, sources, dynamic fields, list / filters / saved views, pipeline, lead detail, create / edit / delete / restore (CRM-01..07, 09..12)
5. [x] Import / export, duplicates & merge, assignment (manual, rules, round robin), follow-up tasks + reminders, bulk actions (CRM-13..17)
6. [x] Lead scoring rules (SCORE-02) + CRM configuration in Super Admin (CRM-18, SA-07)
7. [x] Catalogues: property / package / course, collections, import & media, Indian prices (CAT-01, 02, 04..08)
8. [x] Calendar: views, resources, availability, appointment types, booking, holidays (CAL-01..05, 08, 09)
9. [x] Global search (CP-04)
10. [x] Har feature ki REST API + tests

**Phase 3 gate:** naya CRM field + catalogue field Super Admin se, bina deployment · 10,000 leads import (duplicates + errors report) · double booking concurrent requests mein bhi nahi · template publish → company upgrade → rollback · CI green · client sign-off

_Client se confirm: travel package aur course catalogue ke fields (CAT-05, CAT-06 abhi PRD ke proposed fields par)._

---

## Phase 4 — AI Employee Engine, Knowledge Base & Tools

1. [x] **AI Settings** (SA-09, ENG-09): vendor cards (on/off toggle, key popup — bina page reload), keys encrypted, models + prices, connection test, model per task + fallback order, test-only providers production mein blocked
2. [x] Tool registry + tools: create / update lead, search customer, catalogue search, availability / book / reschedule / cancel, assign salesperson, callback, e-mail; industry tools as configuration (TOOL-01..07, 13..15, SA-06); property matching (CAT-03); AI booking (CAL-06)
3. [x] Knowledge base: website (crawl, re-sync), PDF / DOCX, FAQs (per language, bulk import), approved text, Excel / CSV records, approval, processing status, scope per AI Employee, test, unanswered report, citations (KB-01..11, TEN-04, SEC-11)
4. [x] AI engine: 9-layer prompt, tool calling, grounding check (no invented prices / discounts), AI disclosure by the runtime, extraction (lakh / crore / Indian dates), Hinglish / Bengali-English, returning customer, guardrails, PII masking in logs, usage metering (ENG-01..11, SEC-14, COMP-01, USE-01)
5. [x] AI Employees: list, 10-step wizard with text test console, readiness checklist, activate / pause / archive, settings versions + restore; approval par template se ready-made employee (EMP-01..12, EMP-14, ROLE-02..05)
6. [x] AI scoring: AI intent + rules (weight in settings), reason, history on the timeline (SCORE-01, 03, 04, 06)
7. [x] Super Admin: AI Employees of all companies (pause for abuse, role change, history, conversations + tool logs) (SA-08)
8. [x] Quality evaluation suite: golden conversations Real Estate / Travel / Education × English / Hinglish / Hindi / Bengali (ENG-12)
9. [x] Har feature ki REST API + tests

**Phase 4 gate:** AI evaluation (3 industries × hi / en / bn) asli production model par · zero invented prices / discounts · extraction ≥ threshold · sahi tool aur arguments · prompt-injection aur cross-tenant knowledge tests · CI green · client sign-off

_Voices (EMP-05) aur phone test (EMP-10 voice) Phase 5 mein; WhatsApp / website chat channels Phase 6 mein._

---

## Phase 5 — Voice AI

1. [x] **Voice providers** (SA-10): STT, TTS, telephony vendor cards (AI Settings jaisa — toggle, key popup, test, health), keys encrypted, test-only (free / local) production mein blocked
2. [x] **Languages & Voices** (SA-11, VOICE-07..09, 20, 21): languages table (code, naam, STT / TTS route + fallback order, greeting / disclosure / consent texts), voice catalogue (gender, style, sample), naya language bina code
3. [x] **Calling settings** (registry E): calling window, attempt caps, retry, max call minutes, allowed country codes, recording default, voice turn-taking, latency alert thresholds, retention _(company ka "sirf tighten" screen CP-06 panels ke saath, item 9)_
4. [x] **Phone numbers & telephony** (VOICE-16, SEC-13): number pool, AI Employee ko assign, inbound routing, webhooks signature check; adapters Exotel / Plivo / Twilio
5. [x] **Calls** (VOICE-01, 02, 17, 18, COMP-02): inbound, authorised outbound ("Call now", follow-up) with consent / opt-out / calling-hour checks, call state machine, voicemail / busy / no-answer retry, concurrent / daily / duration limits, consent records
6. [x] **Voice Gateway** (VOICE-03..06, 10, 21, 22): Pipecat pipeline — VAD, streaming STT, turn detection, same AI runtime, streaming TTS, barge-in, filler jab tool chale, AI disclosure + recording consent, language follow, provider failover, per-stage latency metrics
7. [x] **Transfer & handoff** (TOOL-08, VOICE-11, HO-01..05): triggers, routing (assigned → round robin → available → fallback), agent screen pop + notification, no agent → message + callback task, handoff log
8. [x] **Recording, transcript, post-call** (VOICE-12..14, REC-01, REC-03, COMP-06): recording on / off, consent announcement, retention auto-delete, signed-link playback, listen / download permissions, access audit; speaker-labelled transcript; summary / extraction / score / sentiment
9. [ ] **Panels**: wizard voice step (EMP-05 preview), phone step (EMP-08), browser test call (VOICE-19, EMP-10), call logs (VOICE-15), lead timeline calls + recordings (CRM-11), Super Admin Calls (SA-15), usage: voice minutes / calls / STT / TTS (USE-01)
10. [ ] Monitoring alerts (ENGR-05), concurrent-call load test script (ENGR-07)
11. [ ] Har feature ki REST API + tests

**Phase 5 gate:** latency P50 / P95 per language asli test calls par · 50+ scripted calls per language (code-mixed bhi) · barge-in, transfer (warm / cold / no agent), voicemail tests · provider failover test · concurrent-call load test · CI green · client sign-off

_Telephony aur STT / TTS provider client ka faisla — development mein test account, launch par client ka account (sirf configuration)._

---

## Har phase ke rules (kabhi miss nahi karne)

- **No hard-coding** — har business value Super Admin / database se
- **Django admin nahi** — Super Admin custom, Rizz par
- **Har feature ke saath REST API + tests** (Flutter app ke liye)
- **Business logic sirf service layer mein** — views aur APIs dono wahi call karein
- **Har tenant table par `company_id`**, kabhi user input ya AI output se nahi
- **Light theme**; website eSoft (HR `index5`), panels Rizz
- **Jo cheez jis phase mein hai, usi phase mein** — pehle nahi
- **Provider keys sirf Super Admin mein** (encrypted), kabhi `.env` / code mein nahi
- **Hosting / domain client ka faisla** — system hosting-agnostic (Docker)
- **Free LLM (FreeLLMAPI) sirf testing ke liye**, system banne ke baad, Super Admin se — production mein `test_only` blocked
- Gate tests (AI quality, voice latency) **asli production model** par

## Technical conventions (pehle din se)

- Primary keys: UUID · Time: UTC store, `Asia/Kolkata` display
- Money: integer paise · Phone: E.164 (+91)
- `.env` mein sirf infrastructure values (`SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`, `ENVIRONMENT`), kabhi git mein nahi
- Migrations: backward-compatible, CI mein `makemigrations --check`

## Launch se pehle (Phase 8)
- Server scheduler (cron) mein har 5 minute: `python backend/manage.py send_task_reminders --base-url https://<domain>` (follow-up reminders)
- `.env` mein `ADMIN_HOST=admin.<client domain>` aur dono hosts `ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS` mein (Super Admin alag address par)
- Super Admin → Settings → Security → **"2FA mandatory for platform staff" on karna** (development mein owner ke kehne par off)
- Super Admin → System Settings → Registration → **Email verification = Mandatory** (development mein Optional)
- **SMS provider** chun kar Super Admin mein lagana (client ka faisla) agar mobile OTP on karna hai
- Demo / staging server par **"Allow search engines" off**, live par on
- Cron mein har 5 minute: `process_knowledge` aur `end_idle_conversations` (README dekhein); har minute `dial_due_calls` (call retries / follow-ups); roz `apply_voice_retention` (recordings / transcripts retention)
- `.env` mein `PUBLIC_BASE_URL` (https) aur `VOICE_GATEWAY_URL` (wss); telephony provider console mein Super Admin → Phone Numbers ke callback URLs
- `.env` mein `CLAMAV_ADDRESS` (upload virus scan, SEC-11) — ClamAV hosting par chalana
- Hosting par PostgreSQL **vector** extension (pgvector) on karna
- Super Admin → AI Settings mein **production model** ki key; `run_ai_eval` gate pass (ENG-12)

## Pending (client se)
- AI Marketing Employee ki definition
- Flutter app (future project)
