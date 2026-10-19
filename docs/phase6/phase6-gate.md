# Phase 6 Gate — WhatsApp, Website Chat, Appointments, Handoff & Campaigns

Scope from PRD-01 Phase 6. **Done** = built and tested; **Next** = a later part of this phase.
Phase 6 is built in parts: **1. Website chat + shared inbox** → **2. WhatsApp** → 3. Appointment confirmations and
reminders → 4. Campaigns → 5. Notifications, PWA and push.

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

## Part 2 — WhatsApp

| ID | Feature | Status | Where |
|---|---|---|---|
| WA-01 / COMP-07 | Official API only | Done | Provider "Meta WhatsApp Cloud API" (Super Admin → Voice & Channels: access token, app secret, App ID). Adapter interface, so an approved BSP is one more vendor class |
| WA-02 | Connect number | Done (pool) | Super Admin → WhatsApp Numbers: phone number ID + business account ID, given to a company, webhook URL and verify token shown. Company → Settings → WhatsApp / wizard step 7 connects it to an AI Employee. Meta embedded signup needs the client's Meta Tech Provider approval — added when the client has it |
| WA-03 | Template management | Done | Company → Settings → WhatsApp: library copy, editor with live WhatsApp preview, variables mapped to data (customer, company, appointment, item, typed text), category, language, header (text / image / PDF), footer, quick replies; submit to Meta (sample upload for media headers), check approval, rejected reason, delete. Super Admin → WhatsApp Templates: the default library (5 templates, en / hi / bn) |
| WA-04 | Automated approved messages | Done (follow-up, item info) | Lead follow-up after a call (rule per AI Employee); property / product details with photo; templates from the lead page and the inbox. Appointment confirmation / reminder templates are ready in the library and are sent automatically with part 3 |
| WA-05 | AI replies | Done | Customer message → the same engine and knowledge; the AI disclosure is sent first in a new conversation; returning customers are matched by number |
| WA-06 | Shared inbox | Done | WhatsApp chats in the Inbox with delivery ticks; outside the 24-hour window the reply box turns into an approved-template sender |
| WA-07 | Human handover | Done | Same rules as chats (customer asks, hand-over tool, keywords, knowledge gap, hot lead, upset); "connecting / joined / back with the AI" phrases are sent on WhatsApp in the customer's language |
| WA-08 | Opt-in / opt-out | Done | Opt-out / opt-in keywords (System Settings → WhatsApp) answered with the language phrase; consent records with evidence; first customer message counts as opt-in (setting); templates refused after opt-out and, by setting, without opt-in |
| WA-09 | Voice notes | Done | Downloaded from Meta and transcribed with the language's speech-to-text routes and failover (OpenAI, Deepgram, Sarvam, ElevenLabs, local Whisper); unreadable notes go to the inbox |
| WA-10 | Delivery tracking & usage | Done | Every message logged with sent / delivered / read / failed and Meta's pricing category; usage metered once per message (`whatsapp_messages`); this month's numbers on the WhatsApp page; plan limit "WhatsApp conversations / month" — over it, chats wait for a person |
| TOOL-09 | send_whatsapp() | Done | In a WhatsApp chat: photos, brochure and location of an item; on calls and other chats: the approved item / follow-up template. Test conversations never send |
| SEC-13 | Webhook verification | Done (WhatsApp) | Verify-token handshake; every POST needs a valid `X-Hub-Signature-256` with the app secret; each message processed once |
| EMP-08 | Wizard: WhatsApp | Done | Step 7 WhatsApp number; Rules: WhatsApp follow-up after a call; readiness and onboarding count a WhatsApp number |

### Also changed

- Super Admin "Voice Settings" is now **Voice & Channels**; providers can hold a webhook secret (also used by payments later).
- Lead page showed the AI Employee as an id; it now shows the name with a link.
- The transfer tool's description covers live chats as well as calls.

### Settings and phrases added

System Settings → WhatsApp: opt-out / opt-in keywords, first message counts as opt-in, templates only with opt-in,
reply window (hours), photos per item, read receipts. Language phrases: reply to opt-out, reply to opt-in.

### REST API added

`/api/v1/whatsapp/numbers/` · `templates/` (+ `submit`, `sync`, `library`, `from-library`) · `send/` · `messages/` ·
`/api/v1/inbox/<id>/template/` · `/api/v1/admin/whatsapp-numbers/` · `/api/v1/admin/whatsapp-library/` ·
webhook `/webhooks/whatsapp/<provider>/`

### Tests

`tests/test_whatsapp.py` (11, Meta faked): webhook handshake and signature, disclosure then AI answer with lead,
opt-in and de-duplication, STOP / START, voice note transcription, delivery status order and usage, takeover on
WhatsApp and the 24-hour window with a template, template rules / library / submit / sync, sending with consent,
values and photo header, send_whatsapp tool and follow-up after a call, pages / API / company isolation, unconnected
number and paused employee.

### Needed from the client to go live

A Meta Business account with a verified business, a WhatsApp number not used in the WhatsApp app, the app's access
token, app secret and App ID (entered in Super Admin), and approval of the templates by Meta.

## Next parts

| Part | IDs |
|---|---|
| 3. Appointments | CAL-07 confirmations and reminders, CAL-10 notifications to humans |
| 4. Campaigns | CAMP-01 … CAMP-06, COMP-03, COMP-04, COMP-05, SCORE-05 |
| 5. Notifications & mobile | CP-03, NOTI-02, NOTI-03, CP-07, MOB-03, API-05 |
