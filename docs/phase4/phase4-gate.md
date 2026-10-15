# Phase 4 Gate — AI Employee Engine, Knowledge Base & Tools

Scope from PRD-01 Phase 4. **Done** = built and tested; **Done (base)** = the Phase 4 part is built, the rest arrives in the phase named.

## Features

| ID | Feature | Status | Where |
|---|---|---|---|
| SA-09 / ENG-09 | AI providers | Done | Super Admin → AI Settings: vendor cards with on/off toggle and key popup (no page reload), 12 seeded vendors + any OpenAI-compatible provider, encrypted keys, models with prices, connection test, model per task with fallback order; test-only providers (FreeLLMAPI, OmniRoute) blocked in production |
| TOOL-01 / SA-06 | Tool registry | Done | Super Admin → AI Tools: key, description, handler + configuration, schema, category, industries, roles, on/off. Industry tools are configuration of generic handlers |
| TOOL-02 … 07 | MVP tools | Done | create / update lead, search customer, catalogue search, availability / book / reschedule / cancel, assign salesperson, callback, approved e-mail templates (to the current lead only) |
| TOOL-13 | Per-employee tool control | Done | Wizard step 7; registry switch is platform-wide |
| TOOL-14 | Tool execution log | Done | Input, output, status, duration per call; company transcript view and Super Admin conversation view |
| TOOL-15 | Industry tools | Done | search_property, match_properties, book_site_visit · search_packages, create_booking_enquiry · search_courses, check_eligibility, book_counselling |
| CAT-03 | Property matching | Done | Budget ± tolerance, nearby-area aliases, BHK, type, possession; ranked with reasons. Company rules in Catalogue → AI matching |
| CAL-06 | AI booking tools | Done | Same booking service as the panel (row lock); write tools idempotent per turn |
| KB-01 | Website source | Done | Crawler with page / depth limits, include / exclude patterns, robots.txt, daily / weekly re-sync (`process_knowledge`), private-network block in production |
| KB-02 | Documents | Done | PDF (pypdf) and DOCX; size / count limits from the plan (`kb_storage_mb`, `kb_sources`) |
| KB-03 | FAQs | Done | Editor per language, approval per FAQ, CSV / Excel import; template FAQs copied as drafts |
| KB-04 | Approved text | Done | Editing approved text sends it back to draft |
| KB-05 | Excel / CSV & catalogue | Done | Every sheet row kept as an exact record; products with prices live in the catalogue (exact lookup by tools) |
| KB-06 / KB-07 | Approval & processing | Done | Draft → Approved; Queued → Processing → Ready / Failed with reason; re-process; delete removes it from the AI at once |
| KB-08 | Scope | Done | Company-wide or selected AI Employees |
| KB-09 | Knowledge test | Done | Answer + the exact sources used |
| KB-10 | Unanswered questions | Done | Grouped by normalised text and counted; resolve |
| KB-11 | Citations | Done | [K#] markers → sources stored on each AI message and shown in the transcript |
| TEN-04 | Isolated AI knowledge | Done | Search filtered by company (ORM + RLS), approval and scope; tools take company / employee / conversation from the session |
| ENG-01 / 02 | One engine, layered configuration | Done | `apps.agents.runtime`: guardrails → industry → role → company → employee → lead → knowledge → tools → conversation |
| ENG-03 | Tool calling | Done | JSON-schema validation, unknown / disabled tools denied, limits per turn and conversation |
| ENG-04 | No invented facts | Done | Facts only from knowledge / tools; amounts and percentages in answers are checked against them — an invented one is replaced by the fallback and logged; `cannot_answer` → fallback + unanswered + callback task |
| ENG-05 / COMP-01 | AI disclosure | Done | Said by the runtime at the start of every conversation (template / employee text per language) |
| ENG-06 | Structured extraction | Done | After each conversation from the template's AI-extractable fields; lakh / crore / hazaar (Latin, Hindi, Bengali) and Indian dates (aaj, kal, parso, weekdays, "15 Nov") |
| ENG-07 | Mixed language | Done (text) | Hinglish / Bengali-English; replies in the customer's language within the employee's languages. Voice in P5 |
| ENG-08 | Returning customer | Done | Known number → lead fields, earlier summaries, upcoming appointment |
| ENG-10 / SEC-14 | Guardrails | Done | Platform guardrails setting, restricted topics, knowledge marked as data, no price-changing tools, tool scoping, output validation, phone / e-mail masked in logs |
| ENG-11 / USE-01 | Usage metering | Done (capture) | Tokens, credits and provider cost per company, AI Employee, conversation (display in P7) |
| ENG-12 | Quality evaluation | Done | 17 golden conversations (3 industries × English / Hinglish / Hindi / Bengali, injection, missing fact, booking, hand-over); `run_ai_eval`; CI checks the set and the harness |
| SCORE-01 / 03 / 04 / 06 | AI scoring | Done | AI intent (with confidence threshold) blended with the rules (weight in settings), reason stored, score events on the timeline |
| ROLE-02 … 05 | Employee types | Done | Sales, Receptionist, Appointment, Follow-up (new) with their tools; live call transfer in P5 |
| EMP-01 | My AI Employees | Done | Cards with industry, role, languages, status, calls / chats / leads / appointments; Edit, Settings, Knowledge, Calls, Analytics, Activate / Pause; search, filter, empty state |
| EMP-02 … 04, 06 … 09 | Wizard steps | Done | Industry, type (plan + industry), name / avatar / persona / tone / greetings, languages, knowledge scope, tools (CRM, calendars), rules (hours, after-hours, max duration, transfer targets, escalation, fallback, disclosure, recording / consent, follow-up, qualification questions with reorder, restricted topics) |
| EMP-05 | Voice | Done (base) | Speaking speed saved; voices per language arrive with Languages & Voices in P5 |
| EMP-10 | Test console | Done (text) | Chat with captured CRM fields, tool calls, knowledge used, summary / score at the end; test records removed afterwards. Browser / phone voice test in P5 |
| EMP-11 | Activate | Done | Checklist: template, approved knowledge, test passed for the current version, plan limit; channels shown (P5 / P6) |
| EMP-12 | Edit / versions | Done | Every change = new version (who / when / what), restore, pause, archive |
| EMP-14 | Ready-made employee | Done | Created in draft on approval from the industry template (+ draft template FAQs); Super Admin can create again or change the role |
| SA-08 | AI Employees (all companies) | Done | List, status, pause for abuse (company cannot undo), release, configuration history, conversations with tool logs |
| SEC-11 | Secure files | Done | Private storage, signed links, type / size checks, ClamAV scan when `CLAMAV_ADDRESS` is set |

## REST API added

`/api/v1/ai-employees/` (+ `options`, `tools`, `versions`, `restore-version`, `readiness`, `activate`, `pause`, `test-passed`, `test-sessions`)
`/api/v1/conversations/` (+ `messages`, `end`)
`/api/v1/kb/`: `sources/` (+ `approve`, `unapprove`, `reprocess`), `faqs/` (+ `approve`, `import`), `test-query/`, `unanswered/` (+ `resolve`)
`/api/v1/admin/`: `ai-providers/` (+ `active`, `test`), `ai-routes/<task>/`, `tools/`, `ai-employees/` (+ `pause`, `release`, `change-role`, `versions`), `conversations/<id>/`, `companies/<id>/ai-employee/`

## Scheduled jobs (cron, every 5 minutes)

`process_knowledge` (queued sources, re-sync, re-embedding) · `end_idle_conversations` (summary, CRM update, score)

## Gate checklist

- [x] Grounding: invented prices / discounts never reach the customer (`test_invented_price_is_blocked_and_logged`, eval harness)
- [x] Tool selection and arguments validated server-side; company never taken from the model (`test_server_validates_arguments…`)
- [x] Prompt-injection case in the golden set; cross-tenant knowledge test (`test_only_approved_scoped_knowledge…`)
- [x] Extraction of Indian amounts / dates (`test_end_extracts_fields…`, `test_indian_dates`)
- [x] Company isolation for every new endpoint; RLS on all new company tables
- [x] Lint, migrations check, all tests green locally
- [ ] **AI evaluation on the real production model**: `python backend/manage.py run_ai_eval` after a provider key is added in Super Admin → AI Settings (thresholds in System Settings → AI)
- [ ] GitHub CI green on the pushed commit
- [ ] Client sign-off
