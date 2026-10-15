# Phase 3 Gate — Configuration Engine, CRM, Catalogues & Calendar

Scope from PRD-01 Phase 3. **Done** = built and tested; **Done (base)** = the Phase 3 part is built, the rest arrives in the phase named.

## Features

| ID | Feature | Status | Where |
|---|---|---|---|
| IND-01 | Industry management | Done | Super Admin → Industries: name, key, icon, description, order, active, supported languages |
| IND-02 | Template contents | Done | Instructions, qualification flow mapped to CRM fields, CRM fields, catalogue types + fields, appointment types, statuses, scoring rules, handoff rules, greetings + AI-disclosure per language, WhatsApp templates, FAQs, enabled tools (keys; tool registry in P4) |
| IND-03 | Template versioning | Done | Draft → Published → Archived; companies keep their version until they accept the update (panel banner / API); Super Admin can move a company; rollback = republish an archived version |
| IND-04 | Activate / deactivate | Done | Inactive industries hidden from the website and registration (and the P4 wizard) |
| IND-05 | Clone template | Done | Clone an industry with its published template into a new inactive industry |
| IND-06 | MVP templates | Done (base) | Real Estate, Travel & Tours, Education configured; AI tuning and AI tests in P4 |
| ROLE-01 | Role templates | Done | Super Admin → AI Employee Roles: instructions, channels, tools, default rules, plans, industries, status |
| CRM-01 | Lead record | Done | All common fields; per-company number LD-000123 (prefix / digits in settings); AI employee link ready for P4 |
| CRM-02 | Lead statuses | Done | 11 seeded statuses, label / colour / order editable; automatic changes on events (appointment booked now, AI events from P4–P6) |
| CRM-03 | Lead sources | Done | Super Admin → Lead Sources |
| CRM-04 | Dynamic custom fields | Done | 13 field types with required / AI-extractable / filterable / list / order / help / validation; company fields plan-gated (`custom_fields` entitlement) |
| CRM-05/06/07 | Real Estate / Travel / Education fields | Done | In the seeded templates |
| CRM-09 | Lead list | Done | Table on desktop, cards on phones, search, filters incl. custom fields, sort, saved views, pagination |
| CRM-10 | Pipeline board | Done | Drag and drop by status |
| CRM-11 | Lead detail | Done (base) | Profile, custom fields, timeline, notes, tasks, appointments, score history, next action, follow-up scheduler; calls / WhatsApp / transcripts in P5–P6 |
| CRM-12 | Manual create / edit | Done | Create, edit, soft delete, restore |
| CRM-13 | Import / export | Done | CSV / Excel with column mapping, phone normalisation, duplicate detection, error report; export CSV / Excel permission-controlled and audited |
| CRM-14 | Duplicates | Done | Phone is unique per company (blocked at create / import); email duplicates listed and merged |
| CRM-15 | Assignment | Done (base) | Manual, rule-based, round robin; AI `assign_salesperson` tool in P4 uses the same service |
| CRM-16 | Follow-up tasks | Done | Due dates, reminders by email (`send_task_reminders`), "My follow-ups" |
| CRM-17 | Bulk actions | Done (base) | Assign, status, tag, export, delete; "add to campaign" arrives with campaigns in P6 |
| CRM-18 / SA-07 | Super Admin CRM control | Done | Statuses, sources, default fields, scoring rules, import / export limits |
| SCORE-02 | Scoring rules | Done | Field / event / status conditions, points, forced labels, thresholds per template; companies adjust or add rules |
| CAT-01 | Catalogue engine | Done | Types and fields from the template (same field engine); companies manage items |
| CAT-02 | Property database | Done | All PRD fields |
| CAT-04 | Collections | Done | Manual or by filter |
| CAT-05 / CAT-06 | Travel packages / courses | Done | PRD-proposed fields — **to be confirmed with the client** (editable in Super Admin) |
| CAT-07 | Import & media | Done | CSV / Excel with mapping, photos and brochures (private, signed links), bulk edit |
| CAT-08 | Indian prices | Done | ₹70,00,000 · ₹70 Lakh · ₹1.2 Cr; amounts typed as "70 lakh" or "1.2 Cr" are understood |
| CAL-01 | Built-in calendar | Done | Day, week, month and agenda views; agenda on phones |
| CAL-02 | Resources | Done | Team members, sites, rooms, other |
| CAL-03 | Availability rules | Done | Working hours with breaks, slot length, buffer, bookings per slot, minimum notice, booking window, holidays, leave / blocked / extra time |
| CAL-04 | Appointment types | Done | From the industry template |
| CAL-05 | Appointment record | Done | APT-000123, lead, type, resource, person, time, duration, location / link, status, notes, created by, channel |
| CAL-08 | Manual booking | Done | Book, reschedule, confirm, complete, no-show, cancel with reason |
| CAL-09 | Holidays | Done | Platform holidays in Super Admin; company holidays in company settings |
| CP-04 | Global search | Done | Top bar: name, phone, email or lead ID |
| SA-05 | Industries & templates | Done | See IND-* |

Later-phase items in this area (not Phase 3 in the PRD): CAT-03 property matching (P4), CAL-06 AI booking tools (P4, use `scheduling.services.book`), CAL-07 confirmations / reminders (P6), CRM-08 automobile fields (P9).

## REST API added

`/api/v1/admin/`: `templates/` (+ `publish`), `template-fields/`, `template-catalog-types/`, `template-appointment-types/`, `template-statuses/`, `template-scoring-rules/`, `lead-statuses/`, `lead-sources/`, `holidays/`, `employee-roles/`, `companies/<id>/template/`
`/api/v1/company/template/` (current version, accept update)
`/api/v1/crm/`: `leads/` (+ `status`, `assign`, `follow-up`, `notes`, `timeline`, `merge`, `restore`, `bulk`, `export`, `duplicates`, `search`), `tasks/` (+ `complete`), `imports/`, `config/`, `fields/`, `scoring-rules/`, `assignment-rules/`
`/api/v1/catalog/`: `types/`, `items/` (+ `bulk`, `media`), `collections/`, `imports/`
`/api/v1/calendar/`: `resources/` (+ `availability`, `exceptions`), `appointments/` (+ `reschedule`, `status`), `config/`

## Also fixed in this phase

- Settings cache: a release that adds settings no longer breaks while Redis still holds the older settings.
- Panel layout: wide tables and boards scroll inside the page instead of widening it.

## Gate checklist

- [x] New CRM field and new catalogue field added in Super Admin, visible after the company accepts the update — no deployment (`test_crm.py`, `test_catalog.py`)
- [x] Import 10,000 leads with duplicates and errors; counts and error report verified (`test_import_10000_rows_with_duplicates_and_errors`)
- [x] Double booking prevented under concurrent requests (`test_concurrent_requests_cannot_double_book`)
- [x] Template versioning: publish, upgrade a company, roll back (`test_publish_upgrade_and_rollback`)
- [x] Company isolation tests for every new endpoint; RLS on all new company tables
- [x] Lint, migrations check, Bandit (0 issues), pip-audit (no known vulnerabilities), all tests green locally
- [x] GitHub CI green on the pushed commit (run 38777351768, `46ed2df`)
- [ ] Client confirms travel package and course fields (CAT-05 / CAT-06)
- [ ] Device testing and client sign-off
