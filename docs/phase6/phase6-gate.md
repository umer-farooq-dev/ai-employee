# Phase 6 Gate — WhatsApp, Website Chat, Appointments, Handoff & Campaigns

Scope from PRD-01 Phase 6. **Done** = built and tested; **Next** = a later part of this phase.
Phase 6 is built in parts: **1. Website chat + shared inbox** → **2. WhatsApp** → **3. Appointment confirmations and
reminders** → 4. Campaigns → 5. Notifications, PWA and push.

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
| WA-04 | Automated approved messages | Done | Lead follow-up after a call (rule per AI Employee); property / product details with photo; templates from the lead page and the inbox; appointment confirmation, reminder and cancellation (part 3) |
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

## Part 3 — Appointment confirmations, reminders and team alerts

| ID | Feature | Status | Where |
|---|---|---|---|
| CAL-07 | Confirmations | Done | Every booking or new time — by the AI Employee (call, chat, WhatsApp), the team or the API — is confirmed to the customer on WhatsApp (approved "Appointment confirmation" template, in the customer's language) and by e-mail. A cancellation is told on the same channels (new library template "Appointment cancelled"). Sent after the booking is saved, never for one that failed |
| CAL-07 | Reminders | Done | Reminder times in hours before (default 24 and 2; 0.5 = 30 minutes) on WhatsApp ("Appointment reminder" template) and / or e-mail. Each reminder goes once per appointment time; a moved appointment gets them again for the new time; reminder times that were already past when the booking was made are skipped; if the job was stopped, only the latest due reminder goes. Cron: `send_appointment_reminders` every 5 minutes |
| CAL-07 | Settings | Done | Platform defaults in System Settings → Calendar; each company can choose its own in Calendar → Confirmations & reminders (warnings when the needed WhatsApp template is not approved yet), or go back to the defaults |
| CAL-10 | Team alerts | Done | The person the appointment is with gets an e-mail for new, moved and cancelled bookings (who changed it, customer, link to the appointment) — not when they made the change themselves |
| — | Message log | Done | Appointment page → Messages: every confirmation, reminder and team alert with channel, recipient, WhatsApp delivery status, or the reason it was not sent (no e-mail address, opted out, no approved template, e-mail template switched off). "Send confirmation again" button |

Rules kept: WhatsApp opt-out / opt-in and e-mail opt-out are respected; test conversations send nothing; a failed
message never breaks the booking. E-mail texts (5, editable in Super Admin → Email Templates): confirmation, new time,
cancellation, reminder, team alert.

### Also changed

- WhatsApp template dates now use the calendar's own timezone (same as the e-mails).

### REST API added

`/api/v1/calendar/messages/` (GET; PATCH any setting or `{"use_platform": true}`) · appointments now include `notices`
· `/api/v1/calendar/appointments/<id>/resend/`

### Tests

`tests/test_appointment_messages.py` (6): WhatsApp + e-mail confirmation and team alert after commit (nothing for a
rolled-back booking), new time and cancellation (no alert to the person who changed it, skipped WhatsApp without a
template), reminders once per offset / latest only / not before the booking / not for cancelled or suspended,
company choices and validation (also the Super Admin value), AI booking tool vs test conversation, panel page / API /
resend / permissions. Browser check: Calendar → Confirmations & reminders (desktop and phone, save, wrong value,
back to defaults), appointment Messages card, Super Admin → System Settings → Calendar.

## Part 4 — Campaigns and outbound compliance

| ID | Feature | Status | Where |
|---|---|---|---|
| CAMP-01 | Create campaign | Done | Campaigns → New campaign: name, description, what the AI says and offers (added to its instructions on these calls), AI Employee, lead list (lead-list filter — "Call these in a campaign" on the lead list —, saved view, CSV / Excel file, or leads picked with Leads → With selected → Add to campaign), dates, weekdays, time windows, attempts / gap / outcomes to call again, property / product collection (the AI is told to offer them), follow-up (WhatsApp template after the call, another call for hot / warm / cold leads after N days), calls at the same time, calls per day |
| CAMP-02 | Controls | Done | Draft → (Send for approval) → Approve & start → Scheduled / Running → Pause / Resume → Stop; Completed when everyone is done or the end date passed. Statuses Draft, Scheduled, Running, Paused, Completed, Stopped |
| CAMP-03 | Compliance before every dial | Done | The scheduler (`dial_due_calls`, every minute) dials through the same voice checks: calling hours, opt-out / Do-not-call, allowed countries, attempts per lead / per day, the company's daily cap, the plan's calls / minutes / concurrent calls; plus the campaign's windows, days, concurrency and daily limit. A block about one lead skips it with the reason; a company-wide block waits ("Waiting: …" on the campaign) |
| CAMP-04 | Live progress | Done | Total, to call, dialled, connected, qualified, hot, appointments, not reached, skipped — refreshed every 10 seconds; per-lead result, attempts, last call (link), outcome, summary |
| CAMP-05 | Report & export | Done | CSV / Excel per lead (result, attempts, last call, outcome, connected, qualified, hot, appointment, reason skipped, summary) with the campaign summary; audit-logged; needs "Export leads" |
| CAMP-06 | Test mode | Done | Calls only internal test numbers that belong to team members (up to the setting), as test conversations (nothing written to the CRM) |
| COMP-03 | DND / opt-out check | Done | Before every outbound call (campaign or not); the lead's Do-not-call / opt-out consent records. A DND-registry provider is an integration point in `voice.check_outbound` |
| COMP-04 | Calling hours & attempt caps | Done | Platform limits in System Settings → Calling; the company tightens them in Settings → Calling; campaigns cannot exceed them |
| COMP-05 | No unauthorised robocalling | Done | Only leads with a source or consent (setting: recorded opt-in only); every campaign needs a company admin's approval ("Approve campaigns" permission, owners) |
| SCORE-05 | Hot-lead actions | Done | Settings → CRM → "When a lead becomes Hot": assign a salesperson (assignment rules) and alert them (or everyone who assigns leads); handing over the live call / chat is the AI Employee rule. Platform defaults in System Settings → CRM |

Plan limit "Active campaigns" is enforced on approval / resume. Permissions: Campaigns view / manage (owner, manager),
approve (owner).

### REST API added

`/api/v1/campaigns/` (GET, POST) · `<id>/` (GET, PATCH, DELETE draft) · `build/` · `request-approval/` · `approve/` ·
`pause/` · `resume/` · `stop/` · `progress/` · `members/` · `export/`

### Tests

`tests/test_campaigns.py` (10, telephony faked): validation against calling rules / plan / team numbers; list from
filter, CSV and picked leads; manager asks → admin approves, plan limit, pause / resume / stop; scheduled start;
dialling one at a time, campaign retry after the gap, connected, completed with alert; DND / no-source skipped,
opt-in setting; waiting outside windows / days / company cap; results and follow-ups from the conversation, the
campaign brief in the AI prompt; test mode; export, API, panel, company isolation.

## Part 5 — Team alerts, installable app and push

| ID | Feature | Status | Where |
|---|---|---|---|
| NOTI-02 | In-app notifications | Done | The bell (unread count, latest alerts, mark all read) and the Alerts page (unread / kind filters); opening an alert marks it read |
| CP-03 / NOTI-03 | Alerts to people | Done | Transfer requests, hot leads, bookings (CAL-10), campaigns (approval needed, finished / stopped) and usage alerts — in the bell, and by e-mail, WhatsApp ("Alert to your team" template to the person's mobile) and push as each person chooses in Profile → Alerts (platform default: System Settings → Team alerts). Delivery per channel is kept on each alert |
| — | Usage alerts | Done | `send_usage_alerts` (hourly): voice minutes, calls, WhatsApp conversations and AI credits against the plan; company admins alerted once a month per limit and level (80 %, 100 % by setting) |
| MOB-03 / CP-07 | Installable app | Done | Web app manifest (name, colour and icon from Branding), service worker (push alerts, offline page), "Install the app" button, app badge with the unread count, bottom navigation on phones (Leads, Follow-ups, Inbox, Calendar, Alerts) |
| API-05 | Push devices | Done | `/api/v1/devices/` register / list / remove (web, Android, iPhone), `/api/v1/push/config/`; Web Push (VAPID key pair generated by the platform, RFC 8291 encryption) and Firebase Cloud Messaging for the mobile app — both in Super Admin → Voice & Channels |

### Also changed

- Plain-text e-mails keep link addresses ("Open in the panel (https://…)").
- Handoff and booking alerts now go through the same alerts (one place, the person's channels).
- Lead export writing moved to a shared table writer (also used by campaigns).

### REST API added

`/api/v1/notifications/` · `<id>/read/` · `read-all/` · `unread-count/` · `settings/` (GET, PATCH) ·
`/api/v1/devices/` (GET, POST, DELETE) · `devices/remove/` · `/api/v1/push/config/`

### Tests

`tests/test_alerts.py` (10): bell + chosen channels, preferences validation, WhatsApp needs number / template /
setting; Web Push encrypted for the browser (decrypted in the test as RFC 8291) and VAPID-signed, expired
subscription removed; FCM message; hot lead assigned and alerted, no repeat, company switches; usage alerts once per
level; API, centre, open-link safety, isolation, profile; manifest, service worker, offline page; test push.
Browser check: bell, Alerts page, Profile → Alerts, Super Admin Web Push key generation, phone layouts (no sideways
scroll) for dashboard, leads, follow-ups, inbox, calendar, alerts, campaigns.

## Needed from the client for Phase 6 to go live

- Meta: business verification, WhatsApp number, access token, app secret, App ID (Super Admin) and template approvals
  (including "Alert to your team" and "Appointment cancelled").
- A telephony provider with an outbound number (Super Admin → Phone Numbers) for campaigns.
- Firebase project service account (only for the mobile app's push); Web Push needs nothing (keys are generated).
