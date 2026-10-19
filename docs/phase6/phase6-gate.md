# Phase 6 Gate — WhatsApp, Website Chat, Appointments, Handoff & Campaigns

Scope from PRD-01 Phase 6. **Done** = built and tested; **Next** = a later part of this phase.
Phase 6 is built in parts: **1. Website chat + shared inbox** (this part) → 2. WhatsApp → 3. Appointment confirmations
and reminders → 4. Campaigns → 5. Notifications, PWA and push.

## Part 1 — Website chat widget and shared inbox

| ID | Feature | Status | Where |
|---|---|---|---|
| CHAT-01 | Embeddable widget | Done | AI Employee → Website chat: one widget per AI Employee, a one-line `<script … data-key>` snippet with Copy, new key on demand |
| CHAT-02 | Customisation | Done | Name, line under the name, avatar, colour (or platform colour), position, opening language, button text and greeting per language. Every widget text (buttons, placeholder, "connecting you", form labels) is a language phrase in Super Admin → Languages & Voices (en / hi / bn seeded) |
| CHAT-03 | Customer actions | Done | Ask questions and get approved information (same AI engine and knowledge), send an enquiry, request a callback (forms), book an appointment (AI booking tools), talk to a person. Each quick action can be switched off per widget |
| CHAT-04 | Lead capture | Done | The AI's lead tools and the forms create or update the CRM lead with source **Website Chat**; forms add a note and a team task |
| CHAT-05 | Security | Done | Allowed websites per widget (sub-domains included; required unless switched off in System Settings → Website chat), CORS only for those sites, rate limits per IP and per chat, honeypot, minimum time before the first message, signed visitor token (never an id) |
| CHAT-06 | Human takeover | Done | Inbox: take over (the AI pauses), reply, hand back to the AI, assign to a colleague, end |
| CHAT-07 | Lightweight & mobile | Done | No dependencies, ~19 KB (≈6 KB gzipped), loads `async`, Shadow DOM (the site's CSS cannot break it), full screen on phones |
| WA-06 (base) | Shared inbox | Done (chat) | Company → Inbox: Open / Waiting for a person / Mine / AI answering / Ended, search, live updates; WhatsApp conversations join with part 2 |
| HO-01 (chat) | Handoff triggers on chats | Done | "Talk to a person", the AI's hand-over tool, keywords, knowledge gap, repeated failure, hot lead, upset customer (rules per AI Employee) |
| HO-02 … HO-05 (chat) | Routing, agent context, no agent, log | Done | Same routing as calls; screen pop "Take over the chat" + e-mail; next agent after the ring time (widget poll / minute cron); no agent → language phrase to the visitor, callback task, contact form offered when no phone is known; handoff log |
| REC-02 (chat) | Chat records | Done | Summary, requirement, sentiment, intent and score saved when a chat ends (visitor, team or idle timeout); team replies and notices are in the transcript |
| EMP-08 / EMP-11 | Channels in the wizard and readiness | Done (chat) | Step 7 links to Website chat; readiness and onboarding count a website chat placed on a website as a connected channel |

### Fixed on the way

- Handoff alert e-mails were addressed to a list inside a list (would fail on a real mail server).
- The seeded AI disclosure said "This call may be recorded" on every channel; the recording announcement is its own phrase, said only when recording is on. Untouched template texts were corrected by a data migration.

### Settings added (System Settings → Website chat)

Show only on allowed websites · new chats per visitor IP · messages per chat · bot protection (seconds) · poll interval.

### REST API added

Public (widget): `/public/v1/chat/<key>/` (config) · `sessions/` · `messages/` (GET new, POST send) · `human/` ·
`contact/` · `end/`. Company: `/api/v1/ai-employees/<id>/widget/` (GET, PATCH) · `/api/v1/inbox/` ·
`/api/v1/inbox/<id>/` + `take-over` · `hand-back` · `reply` · `assign` · `end`.

### Tests

`tests/test_webchat.py` (13): settings and snippet, appearance from settings / phrases, allowed websites, rate limits,
honeypot and bot timing, AI chat saved with lead source, enquiry / callback forms, take over → reply → hand back,
no agent, next agent after ring time, hand-over tool and keyword trigger, inbox views / permissions / company
isolation, panel pages. Browser check: widget on an external test site (`localhost:5500`) on desktop and phone,
screen pop, inbox reply seen by the visitor, hand back, callback form.

## Next parts

| Part | IDs |
|---|---|
| 2. WhatsApp | WA-01 … WA-10, TOOL-09, EMP-08 WhatsApp, COMP-07, SEC-13 WhatsApp, REC-02 WhatsApp |
| 3. Appointments | CAL-07 confirmations and reminders, CAL-10 notifications to humans |
| 4. Campaigns | CAMP-01 … CAMP-06, COMP-03, COMP-04, COMP-05, SCORE-05 |
| 5. Notifications & mobile | CP-03, NOTI-02, NOTI-03, CP-07, MOB-03, API-05 |
