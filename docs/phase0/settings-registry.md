# Settings Registry (Phase 0 deliverable)

Rule: **no business value is hard-coded.** Two kinds of configuration exist:

1. **Settings registry** — single values stored in `platform_settings` (key, typed value, schema, category). Super Admin forms are generated from the schema. Companies may tighten some values but never exceed a platform limit (marked *company may override*).
2. **Configuration data** — lists and records with their own Super Admin screens (plans, industries, statuses …), listed at the end.

Seed defaults below are inserted by a data migration and are editable afterwards.

---

## A. General Settings (SA-21 … SA-27) — Phase 1 · screen: Super Admin → General Settings

| Key | Type | Default | Used by |
|---|---|---|---|
| `general.platform_name` | text | "AI Employee" | website, panels, emails, invoices, page titles |
| `general.short_name` | text | "AIE" | PWA, small spaces |
| `general.tagline` | text | "Hire an AI Employee for your business" | website, emails |
| `general.logo_light` / `general.logo_dark` | image | eSoft / Rizz logos | website header, panel sidebar, emails, invoices |
| `general.logo_small` | image | Rizz small logo | collapsed sidebar |
| `general.favicon` | image | template favicon | all pages (sizes generated on upload) |
| `general.app_icon` | image | — | PWA manifest, future Flutter app |
| `general.login_image` | image | — | login / register pages |
| `general.color_primary` / `general.color_secondary` | colour | eSoft purple `#6534F4` / `#101537` | CSS variables on website and panels |
| `general.widget_powered_by` | text | "Powered by AI Employee" | chat widget |
| `contact.support_email` | email | — | footer, emails, contact page |
| `contact.support_phone` / `contact.whatsapp` | phone (E.164) | — | footer, contact page |
| `contact.address` | textarea | — | footer, invoices |
| `contact.legal_name` / `contact.gstin` / `contact.pan` | text | — | GST invoices |
| `contact.social_links` | list[platform, URL] | — | website footer |
| `contact.copyright` | text | "© {year} AI Employee" | footers |
| `locale.timezone` | choice | Asia/Kolkata | display of all times (storage stays UTC) |
| `locale.currency` | choice | INR | prices, invoices |
| `locale.number_format` | choice | Indian (lakh / crore) | prices |
| `locale.default_language` | choice | en | panels, emails |
| `seo.meta_title` / `seo.meta_description` / `seo.og_image` | text / image | — | default for every page |
| `seo.analytics_ids` | list[text] | — | website head |
| `email.sender_name` / `email.sender_address` | text / email | platform name / no-reply@… | all emails |
| `email.header_html` / `email.footer_html` | rich | — | email layout |
| `maintenance.enabled` | boolean | false | website and panels (Super Admin stays open) |
| `maintenance.message` | rich | — | maintenance page |

## B. Registration & Accounts — Phase 1/2 · screen: Settings → Registration

| Key | Type | Default |
|---|---|---|
| `registration.enabled` | boolean | true |
| `registration.mobile_otp_required` | boolean | false |
| `registration.email_verification` | choice (mandatory / optional) | mandatory |
| `registration.trial_enabled` / `registration.trial_days` | boolean / number | true / 14 |
| `registration.default_plan` | plan reference | Starter |

## C. Security — Phase 1 · screen: Settings → Security

| Key | Type | Default | Notes |
|---|---|---|---|
| `security.password_min_length` | number | 10 | |
| `security.lockout_attempts` / `security.lockout_minutes` | number | 5 / 15 | |
| `security.session_timeout_minutes` | number | 120 | |
| `security.staff_2fa_required` | boolean | true | cannot be switched off in production |
| `security.company_2fa_enforced` | boolean | false | *company may override* (enable) |
| `security.admin_ip_allowlist` | list[CIDR] | [] | empty = open in local / staging only |
| `security.upload_max_mb` | number | 25 | per file |
| `security.upload_allowed_types` | list[mime] | pdf, docx, xlsx, csv, png, jpg, webp, svg | |

## D. Data retention & privacy — Phase 7/8 · screen: Settings → Data & Privacy

| Key | Type | Default | Notes |
|---|---|---|---|
| `retention.recordings_days` | number | 90 | *company may override* (shorter) |
| `retention.transcripts_days` | number | 365 | *company may override* (shorter) |
| `retention.audit_logs_days` | number | 730 | |
| `retention.account_deletion_grace_days` | number | 30 | |

## E. Voice & calling defaults — Phase 5/6 · screen: Settings → Calling

| Key | Type | Default | Notes |
|---|---|---|---|
| `calling.window_start` / `calling.window_end` | time | 09:00 / 21:00 | *company may override* (narrower) |
| `calling.max_attempts_per_lead_per_day` | number | 2 | *company may override* (lower) |
| `calling.max_attempts_per_campaign` | number | 3 | |
| `calling.dnd_check_enabled` | boolean | true | |
| `calling.allowed_country_codes` | list | ["+91"] | toll-fraud protection |
| `calling.recording_enabled_default` | boolean | true | *company may override* |
| `calling.recording_consent_text` | text per language | — | |
| `calling.ai_disclosure_text` | text per language | — | runtime inserts it, not the model |
| `calling.max_call_minutes` | number | 15 | |
| `voice.latency_alert_p95_ms` | number | 2000 | quality alerts |
| `whatsapp.opt_out_keywords` | list | STOP, UNSUBSCRIBE, BAND KARO | |

## F. AI — Phase 4 · screen: Super Admin → AI Providers

| Key | Type | Default | Notes |
|---|---|---|---|
| `ai.fallback_message` | text per language | — | when facts are missing |
| `ai.sentiment_min_confidence` | number 0–1 | 0.7 | below → not stored |
| `ai.kb_top_k` | number | 5 | retrieved chunks per turn |
| `ai.block_test_only_in_production` | boolean | true | **locked** — FreeLLMAPI never in production |

## G. Billing — Phase 7 · screen: Settings → Billing

| Key | Type | Default |
|---|---|---|
| `billing.gst_rate` | percent | 18 |
| `billing.supplier_state` | choice (Indian states) | — |
| `billing.invoice_prefix` | text | "AIE" |
| `billing.grace_period_days` | number | 7 |
| `billing.usage_alert_thresholds` | list[percent] | [80, 100] |

---

## Configuration data (own Super Admin screens, not single settings)

| Data | Screen | Phase |
|---|---|---|
| Website pages, sections and content | Website Content (CMS) | P1 |
| Plans, prices, limits, overage prices | Plans & Pricing | P1 (payments P7) |
| Roles and permissions | Roles & Permissions | P1 |
| Email and notification templates | Settings → Templates | P1 |
| AI providers, models per task, fallback order, Test-only flag | AI Providers | P1 (screen) / P4 (use) |
| Industries and industry template versions | Industries | P3 |
| Lead fields, statuses, sources, scoring rules | CRM Configuration | P3 |
| Catalogue types and fields, appointment types, holidays | Industries / Calendar | P3 |
| Employee roles and tool registry | Roles & Tools | P3/P4 |
| Languages, voices, STT / TTS routes, telephony and WhatsApp providers | Languages & Voices / Providers | P5/P6 |
| Feature flags | Feature Flags | P7 |
