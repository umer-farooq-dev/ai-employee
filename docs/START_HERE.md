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
- Super Admin → Settings → Security → **"2FA mandatory for platform staff" on karna** (development mein owner ke kehne par off)
- Super Admin → System Settings → Registration → **Email verification = Mandatory** (development mein Optional)
- **SMS provider** chun kar Super Admin mein lagana (client ka faisla) agar mobile OTP on karna hai
- Demo / staging server par **"Allow search engines" off**, live par on

## Pending (client se)
- AI Marketing Employee ki definition
- Flutter app (future project)
