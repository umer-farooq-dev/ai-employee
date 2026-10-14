# START HERE — Development Checklist

Yeh file development shuru karne ki poori checklist hai. Har item ka detail in do docs mein hai:
- `docs/01_AI_Employee_Product_Requirements_and_Phase_Plan.pdf` (PRD-01: features, phases, gates)
- `docs/02_AI_Employee_System_Design_and_Architecture.pdf` (SDD-02: technical design)

Client approval mil chuki hai (architecture, scope, cost, milestones).

---

## Step 0 — Development se pehle (aap ki taraf se)

**Machine**
- [x] Docker Desktop + WSL2 install (Postgres + pgvector, Redis, Mailpit, MinIO, FreeLLMAPI isi mein chalenge)
- [x] Python 3.12, Git, Node (sirf Rizz build ke liye) — installed

**Accounts**
- [ ] GitHub private repo (naam: `ai-employee` ya jo aap rakho)
- [ ] Free LLM keys for FreeLLMAPI: Groq, Google Gemini, Cerebras, Mistral, OpenRouter (har provider ka sirf **ek** account)
- [ ] Voice PoC trials: Sarvam AI, Google Cloud Speech/TTS, ElevenLabs
- [ ] Telephony test account: Exotel ya Plivo (KYC mein waqt lagta hai — abhi apply karo)
- [ ] Razorpay test mode account
- [ ] Meta WhatsApp Business test number
- [ ] AWS account (staging ke waqt chahiye, P1 ke end tak)
- [ ] Domain name (website + `admin.` sub-domain)

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
- [x] `docker-compose.yml`: postgres+pgvector, redis, mailpit, freellmapi (MinIO/S3 jab file uploads aayein, P1)
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
- [ ] FreeLLMAPI dashboard mein free provider keys + client key → `.env` `LLM_API_KEY` (**aap**)
- [x] Voice PoC script ready: `poc/voice_bakeoff.py`
- [ ] Voice PoC run: Sarvam / Google / ElevenLabs keys `.env` mein → report + har language ka provider (**keys aap ki taraf se**)
- [x] AI PoC script ready: `poc/ai_extraction.py` (10 Hinglish / Hindi / Bengali / English cases)
- [ ] AI PoC run on FreeLLMAPI → `poc/output/ai_report.md`
- [ ] Terraform skeleton → staging ke saath (AWS account aane par, P1 ke end tak)

**Phase 0 gate:** CI green · mapping sheet done · PoC report · provider choice per language

---

## Phase 1 — Core + Super Admin pehle (is order mein)

1. [ ] Auth: allauth login, 2FA (staff ke liye mandatory), lockout, password reset, sessions (AUTH-03..06, 08, 11)
2. [ ] Tenancy: `Company` model, `company_id` scoping manager, PostgreSQL RLS, isolation tests (TEN-01..03, 05, 06)
3. [ ] Super Admin layout on Rizz + login + IP allowlist (SA-01, SA-18)
4. [ ] **General Settings**: naam, logo, favicon, colours, contact, footer, SEO, localisation, email sender, maintenance mode (SA-21..27)
5. [ ] **Website CMS**: `index5` ke har section ka editor — headings, text, images, buttons, order, show/hide (WEB-04, WEB-09)
6. [ ] Companies + users screens, suspend, impersonation with audit (SA-03, SA-04)
7. [ ] Roles & permissions (AUTH-11)
8. [ ] Plans & pricing data (SUB-01, SUB-02, SA-12)
9. [ ] Audit logs, system logs (SA-17, SEC-08)
10. [ ] Email templates + account emails (NOTI-01)
11. [ ] AI providers screen with OpenAI-compatible type + Test-only flag (SA-09, SA-28)
12. [ ] Har feature ki REST API + OpenAPI docs + API tests (API-01..04, 06, 07)

**Phase 1 gate:** tests → GitHub CI green → security check → no-hard-coding review → staging UAT → client sign-off

---

## Har phase ke rules (kabhi miss nahi karne)

- **No hard-coding** — har business value Super Admin / database se
- **Django admin nahi** — Super Admin custom, Rizz par
- **Har feature ke saath REST API + tests** (Flutter app ke liye)
- **Business logic sirf service layer mein** — views aur APIs dono wahi call karein
- **Har tenant table par `company_id`**, kabhi user input ya AI output se nahi
- **Light theme**; website eSoft (HR `index5`), panels Rizz
- **Free LLM sirf dev/staging** — production mein `test_only` blocked, dummy data only
- Gate tests (AI quality, voice latency) **asli production model** par

## Technical conventions (pehle din se)

- Primary keys: UUID · Time: UTC store, `Asia/Kolkata` display
- Money: integer paise · Phone: E.164 (+91)
- Secrets: sirf `.env` / secrets manager, kabhi git mein nahi
- Migrations: backward-compatible, CI mein `makemigrations --check`

## Pending (client se)
- AI Marketing Employee ki definition
- Flutter app (future project)
