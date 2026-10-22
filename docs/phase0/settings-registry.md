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
| `general.color_company_panel` | colour | `#0D9488` | company panel accent (CP-01) |
| `general.widget_powered_by` | text | "Powered by AI Employee" | chat widget |
| `contact.support_email` | email | — | footer, emails, contact page |
| `contact.support_phone` / `contact.whatsapp` | phone (E.164) | — | footer, contact page |
| `contact.address` | textarea | — | footer, invoices |
| `contact.legal_name` / `contact.gstin` / `contact.pan` | text | — | GST invoices |
| `contact.social_links` | list[platform, URL] | — | website footer |
| `contact.team_notify_emails` | list[email] | — (support email) | new registrations, website enquiries |
| `contact.copyright` | text | "© {year} AI Employee" | footers |
| `locale.timezone` | choice | Asia/Kolkata | display of all times (storage stays UTC) |
| `locale.currency` | choice | INR | prices, invoices |
| `locale.number_format` | choice | Indian (lakh / crore) | prices |
| `locale.default_language` | choice | en | panels, emails |
| `seo.meta_title` / `seo.meta_description` / `seo.og_image` | text / image | — | default for every page |
| `seo.analytics_ids` | list[text] | — | website head |
| `seo.allow_indexing` | boolean | true | robots.txt / noindex (off on demo servers) |
| `email.sender_name` / `email.sender_address` | text / email | platform name / no-reply@… | all emails |
| `email.header_html` / `email.footer_html` | rich | — | email layout |
| `maintenance.enabled` | boolean | false | website and panels (Super Admin stays open) |
| `maintenance.message` | rich | — | maintenance page |

## B. Registration & Accounts — Phase 1/2 · screen: Settings → Registration

| Key | Type | Default |
|---|---|---|
| `registration.enabled` | boolean | true |
| `registration.approval_required` | boolean | true (new companies wait for Super Admin approval, AUTH-12) |
| `registration.email_verification` | choice (mandatory / optional) | optional during development → mandatory at launch |
| `registration.mobile_otp_required` | boolean | false |
| `registration.otp_length` / `otp_valid_minutes` / `otp_max_attempts` | number | 6 / 10 / 5 |
| `registration.business_sizes` | list | 1-10, 11-50, 51-200, 201+ |
| `team.invite_valid_days` | number | 7 |
| `registration.trial_enabled` / `registration.trial_days` | boolean / number | true / 14 |
| `registration.default_plan` | plan reference | Starter |

## C. Security — Phase 1 · screen: Settings → Security

| Key | Type | Default | Notes |
|---|---|---|---|
| `security.password_min_length` | number | 10 | |
| `security.lockout_attempts` / `security.lockout_minutes` | number | 5 / 15 | |
| `security.session_timeout_minutes` | number | 120 | |
| `security.staff_2fa_required` | boolean | false | off during development (owner decision); **switch on before launch** (P8) |
| `security.company_2fa_enforced` | boolean | false | *company may override* (enable) |
| `security.admin_ip_allowlist` | list[CIDR] | [] | empty = open in local / staging only |
| `security.upload_max_mb` | number | 25 | per file |
| `security.upload_allowed_types` | list[mime] | pdf, docx, xlsx, csv, png, jpg, webp, svg | |
| `security.signed_url_seconds` | number | 300 | private file link validity |
| `security.api_rate_user` / `security.api_rate_anon` / `security.api_rate_company` | text | 1000/hour / 100/hour / 5000/hour | REST API throttling (API-06) |
| `security.api_rate_public_form` | text | 10/hour | website / app forms per IP |

## C3. CRM & Calendar — Phase 3 · screen: Settings → CRM / Calendar

| Key | Type | Default | Notes |
|---|---|---|---|
| `crm.lead_number_prefix` / `crm.lead_number_digits` | text / number | LD- / 6 | LD-000123 |
| `crm.import_max_rows` / `crm.import_max_mb` | number | 10000 / 10 | lead and catalogue imports |
| `crm.export_max_rows` | number | 50000 | |
| `crm.task_reminder_minutes` | number | 30 | reminder before a follow-up is due |
| `calendar.appointment_prefix` | text | APT- | APT-000123 |
| `calendar.confirm_whatsapp` / `calendar.confirm_email` | boolean | on / on | customer confirmation when booked or moved (CAL-07); company can change under Calendar → Confirmations & reminders |
| `calendar.cancel_notice` | boolean | on | tell the customer when a booking is cancelled |
| `calendar.reminder_hours` | list | 24, 2 | reminder times in hours before (0.5 = 30 min) |
| `calendar.reminder_whatsapp` / `calendar.reminder_email` | boolean | on / on | reminder channels |
| `calendar.reminder_max_hours` | number | 168 | limit for companies' own reminder times |
| `calendar.notify_staff` | boolean | on | alert the assigned person about new / moved / cancelled bookings (CAL-10) |
| `crm.hot_lead_notify` / `crm.hot_lead_assign` | boolean | on / on | SCORE-05 hot-lead actions; company can change them in Settings → CRM |
| `campaigns.default_max_attempts` / `default_retry_gap_minutes` / `default_retry_outcomes` | number / number / list | 3 / 120 / busy, no_answer, voicemail | defaults for a new campaign |
| `campaigns.default_max_concurrent` / `default_daily_limit` | number | 1 / 100 | defaults; never above the plan / calling rules |
| `campaigns.require_opt_in` | boolean | off | COMP-05: off = leads with a source or consent; on = recorded opt-in only |
| `campaigns.qualified_labels` | list | hot, warm | score labels counted as "qualified" in campaign results |
| `campaigns.max_test_numbers` / `campaigns.max_leads` | number | 5 / 20000 | test mode numbers; leads per campaign |
| `notifications.default_channels` | list | email, push | alert channels besides the bell (email, whatsapp, push); each person can change theirs |
| `notifications.whatsapp_enabled` | boolean | on | WhatsApp alerts to team members (company's "Alert to your team" template) |
| `notifications.poll_seconds` / `notifications.push_ttl_seconds` | number | 30 / 3600 | bell refresh; how long push services keep an undelivered alert |
| `notifications.usage_alert_percent` | list | 80, 100 | usage alert levels (% of the plan) |
| `locale.default_phone_country` | text | in | flag + dial code pre-selected in phone fields |

## C2. SMS (mobile OTP) — Phase 2 · screen: Settings → SMS

| Key | Type | Default | Notes |
|---|---|---|---|
| `sms.provider` | choice | development log | real provider added when the client chooses one; keys in Super Admin |
| `sms.otp_message` | text | "{{ code }} is your … code" | |

## D. Data retention & privacy — Phase 7/8 · screen: Settings → Data & Privacy

| Key | Type | Default | Notes |
|---|---|---|---|
| `retention.recordings_days` | number | 90 | *company may override* (shorter) |
| `retention.transcripts_days` | number | 365 | *company may override* (shorter) |
| `retention.audit_logs_days` | number | 730 | |
| `retention.account_deletion_grace_days` | number | 30 | |

## E. Voice & calling — Phase 5 · screen: System Settings → Calling / Voice conversations / Data retention

| Key | Type | Default | Notes |
|---|---|---|---|
| `calling.window_start` / `calling.window_end` | time | 09:00 / 21:00 | *company may override* (narrower) |
| `calling.max_attempts_per_lead_per_day` / `calling.max_attempts_per_lead` | number | 2 / 3 | *company may override* (lower) |
| `calling.retry_gap_minutes` / `calling.retry_outcomes` | number / list | 60 / busy, no_answer, voicemail | VOICE-17 |
| `calling.voicemail_action` | choice | leave message | or hang up |
| `calling.ring_timeout_seconds` / `calling.max_call_minutes` | number | 30 / 15 | |
| `calling.max_calls_per_day` | number | 500 | per company; plan sets monthly calls / concurrent calls |
| `calling.allowed_country_codes` | list | ["+91"] | toll-fraud protection |
| `calling.dnd_check_enabled` | boolean | true | |
| `calling.recording_enabled_default` / `calling.recording_mode` | boolean / choice | true / gateway | *company may override* |
| `voice.end_of_speech_ms` / `voice.barge_in_enabled` / `voice.filler_after_ms` | number / boolean / number | 500 / true / 700 | turn-taking (VOICE-05, 06) |
| `voice.silence_prompt_seconds` / `voice.silence_hangup_seconds` | number | 8 / 25 | |
| `voice.stt_min_confidence_percent` | number | 50 | below → ask to repeat |
| `voice.latency_alert_p50_ms` / `voice.latency_alert_p95_ms` | number | 1200 / 2000 | quality alerts |
| `retention.recordings_days` / `retention.transcripts_days` | number | 90 / 365 | *company may override* (shorter) |
| `voice.reply_style` | textarea | short spoken sentences, no lists / markdown | prompt layer on calls |
| `handoff.agent_ring_seconds` / `handoff.max_agents` | number | 25 / 3 | HO-02 routing |
| `handoff.repeat_failures` / `handoff.callback_minutes` | number | 2 / 30 | HO-01 trigger, HO-04 callback task |
| `handoff.upset_prompt` | textarea | "If the customer is clearly angry…" | HO-01 negative-sentiment trigger (added on calls when the employee's rule is on) |
| `chat.require_allowed_domains` | boolean | on | CHAT-05: the widget opens only on the company's listed websites |
| `chat.rate_sessions` / `chat.rate_messages` | text | 20/hour per IP / 20/minute per chat | CHAT-05 rate limits |
| `chat.bot_min_seconds` | number | 2 | CHAT-05: a first message faster than this is refused (bot protection) |
| `chat.poll_seconds` | number | 4 | widget and inbox check for new messages |
| `whatsapp.opt_out_keywords` / `whatsapp.opt_in_keywords` | list | STOP, UNSUBSCRIBE, BAND KARO, बंद करो / START, SUBSCRIBE | WA-08: exact customer message → consent record |
| `whatsapp.inbound_is_opt_in` / `whatsapp.require_opt_in` | boolean | on / on | WA-08, COMP-07: who may receive templates |
| `whatsapp.session_window_hours` | number | 24 | Meta's customer service window for free-form replies |
| `whatsapp.max_item_photos` / `whatsapp.read_receipts` | number / boolean | 3 / on | WA-04 item photos; blue ticks for customers |

Per-language phrases — AI disclosure, recording announcement, default greeting, fillers, transfer, no agent, voicemail, silence, goodbye, and every text of the website chat widget (button, message box, quick actions, "connecting you", form labels) — live on each language in **Languages & Voices** (a new language brings all its texts with it).

## F. AI — Phase 4 · screen: Super Admin → System Settings → AI / Knowledge base (providers: AI Settings)

| Key | Type | Default | Notes |
|---|---|---|---|
| `ai.request_timeout_seconds` | number | 60 | after this the next provider in the fallback order is tried |
| `ai.guardrails` | textarea | platform rules (no invented facts, injection, language, confirmation, citations) | prompt layer 1 |
| `ai.fallback_message` | text per language | en / hi / bn texts | when facts are missing; an AI Employee may set its own |
| `ai.kb_top_k` | number | 5 | retrieved chunks per answer |
| `ai.history_turns` / `ai.memory_conversations` | number | 12 / 3 | recent messages · earlier conversations remembered (ENG-08) |
| `ai.max_tool_calls_per_turn` / `ai.max_tool_calls_per_conversation` | number | 5 / 40 | tool misuse limits |
| `ai.max_turns_per_conversation` / `ai.max_message_chars` | number | 80 / 2000 | abuse limits |
| `ai.conversation_idle_minutes` | number | 30 | idle conversations are closed (summary, CRM, score) |
| `ai.min_confidence_percent` | number | 70 | below → sentiment / intent not stored |
| `ai.intent_weight_percent` | number | 40 | AI intent share of the lead score (SCORE-03) |
| `ai.tokens_per_credit` | number | 1000 | AI credits from tokens (USE-01) |
| `ai.default_employee_name` | text | Sara | ready-made AI Employee on approval (EMP-14) |
| `ai.eval_min_extraction_percent` / `ai.eval_min_tool_percent` / `ai.eval_min_language_percent` | number | 85 / 90 / 90 | ENG-12 gate; grounding and disclosure allow no failures |
| test-only providers in production | — | always blocked | **locked** — enforced in code from `ENVIRONMENT=production` (not a setting): test-only providers (FreeLLMAPI, OmniRoute) are skipped and cannot be switched on |

### F2. Knowledge base — Phase 4

| Key | Type | Default |
|---|---|---|
| `knowledge.crawl_max_pages` / `knowledge.crawl_max_depth` | number | 50 / 2 (a source may set lower) |
| `knowledge.chunk_chars` / `knowledge.chunk_overlap` | number | 1200 / 150 |
| `knowledge.user_agent` | text | AIEmployeeBot/1.0 |

Plan limits (Plans & Pricing): `ai_employees`, `kb_sources`, `kb_storage_mb`.

## G. Billing & analytics — Phase 7 · screen: System Settings → Billing & GST / Dashboard & analytics

| Key | Type | Default |
|---|---|---|
| `billing.gst_rate` | number (%) | 18 (a plan may set its own) |
| `billing.seller_state` | choice (GST state codes) | — (decides CGST + SGST vs IGST) |
| `billing.sac_code` | text | — (ask the accountant) |
| `billing.invoice_prefix` | text (1–5 letters) | "INV" → INV/26-27/00001 |
| `billing.prices_include_gst` | boolean | false |
| `billing.proration` | boolean | true |
| `billing.grace_days` | number | 7 |
| `billing.trial_reminder_days` | number | 3 |
| `billing.invoice_due_days` | number | 7 |
| `billing.invoice_footer` | textarea | — |
| `notifications.usage_alert_percent` | list[percent] | [80, 100] (Team alerts) |
| `analytics.default_range` | choice | 7d |
| `analytics.refresh_seconds` | number | 30 |
| `analytics.max_range_days` | number | 366 |

Seller name, GSTIN, PAN and address come from General Settings → Contact. Razorpay keys: Voice & Channels → Razorpay
(key id, key secret, webhook secret). Provider costs for margin reports: price fields in each telephony / WhatsApp
provider's key popup and the model prices in AI Settings.

---

## Configuration data (own Super Admin screens, not single settings)

| Data | Screen | Phase |
|---|---|---|
| Website pages, sections and content | Website Content (CMS) | P1 |
| Plans, prices, limits, overage prices | Plans & Pricing | P1 (payments P7) |
| Roles and permissions | Roles & Permissions | P1 |
| Email and notification templates | Settings → Templates | P1 |
| AI providers (vendors seeded: OpenAI, Gemini, Anthropic, xAI, Groq, Mistral, DeepSeek, OpenRouter, Together, Cerebras, FreeLLMAPI, OmniRoute), keys, models + prices, model per task, fallback order, Test-only flag | AI Settings | P4 |
| Industries and industry template versions | Industries | P3 |
| Lead fields, statuses, sources, scoring rules | CRM Configuration | P3 |
| Catalogue types and fields, appointment types, holidays | Industries / Calendar | P3 |
| Employee roles and tool registry (tool = handler + configuration, e.g. search_property = catalogue search on "property") | AI Employee Roles · AI Tools | P3/P4 |
| Speech-to-text, voice and telephony vendors (seeded: Sarvam, Deepgram, ElevenLabs, Cartesia, Google, Azure, OpenAI, Exotel, Plivo, Twilio; test-only local Whisper / Kokoro), keys and account ids | Voice Settings | P5 |
| Languages (code, locale, script, phrases), STT / TTS routes per language with failover, voice catalogue | Languages & Voices | P5 |
| WhatsApp providers | Providers | P6 |
| Feature flags | Feature Flags | P7 |
