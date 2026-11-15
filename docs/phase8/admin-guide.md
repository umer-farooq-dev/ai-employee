# Admin Guide — Super Admin

For the platform team that runs the AI Employee business. Super Admin is at `https://admin.<domain>/superadmin/` — its
own address, so a staff sign-in never mixes with a company or website sign-in in the same browser. Staff sign in with
2FA. Server operations (deployment, backups, recovery) are in [runbook.md](runbook.md); the launch settings review is
[go-live-checklist.md](go-live-checklist.md).

**Golden rule:** nothing business-related is in code. Prices, limits, texts, policies, templates and every provider key
are set on these screens, and changes apply at once.

## Staff roles

| Role | For |
|---|---|
| Super Admin | Everything |
| Support | Support tickets and enquiries; read-only companies, users, plans, subscriptions, website content, logs and dashboard; sign in as a user for support |

Roles and their permissions are edited in **Roles & Permissions** (new roles can be added). Every staff action is in
**Logs → Audit log**.

## Daily work

| Screen | What you do there |
|---|---|
| **Dashboard** | Companies (active, trial, new), active AI Employees, calls and minutes, MRR, revenue and provider cost this month, billing issues, AI / WhatsApp usage, approvals and enquiries waiting, errors (24 h), provider health, revenue chart |
| **Companies** | Approve or reject new registrations (the owner is e-mailed and the ready-made AI Employee is created); edit, suspend, change plan or template version; **Billing** button; **Export data** (ZIP); **Delete** (scheduled purge after the grace days); **Sign in as this user** for support (reason required, banner shown, audited) |
| **Support Tickets** | Filter, reply (e-mail + bell to the company), **internal note** (company never sees it), assign, status. Answered tickets close after the configured days |
| **Enquiries** | Website contact / demo requests |
| **Billing** | Subscriptions (trial, active, overdue, on hold), invoices (PDF, **Mark paid** with method and reference, cancel), payments incl. failed |
| **Usage & Margin** | Per company and per provider each month: usage, provider cost, revenue before GST, margin |
| **Calls** | Every call across companies with recording, transcript and per-stage latency |
| **Logs** | Audit log, API log and server errors (with request id) |
| **Sessions** | Active sign-ins of all users; end any of them |

## Company billing (enterprise and special cases)

Companies → a company → **Billing**:
- **Billing terms**: Razorpay automatic renewal or **by invoice**; custom monthly price; custom limits (each "plan" or
  own value, stop or overage with price); features on / off for this company.
- **AI credits**: add or take back credits for a month, with a reason.
- **Issue an invoice**: one-off (description + amount) or a **plan period** (amount and description come from the plan if
  left empty). GST is added by the company's state (CGST + SGST or IGST); the PDF is e-mailed.
- **Put on hold / Lift billing hold**: the AI pauses and the team only sees Billing and Support while on hold.

## Plans & Pricing

Monthly and yearly price, GST rate, trial days, public (shown on the website) or not, enterprise / custom, limits per
plan (empty = unlimited, 0 = not included) with **Stop** or **Overage** and the overage price, and the features
included. Plans with companies on them are **archived**, not deleted.

## AI and channels

| Screen | Purpose |
|---|---|
| **AI Settings** | AI providers and keys, models and prices; **routes per task** (chat, voice, extraction, summary, scoring, embedding) with fallback order |
| **Voice & Channels** | Telephony (Exotel, Plivo, Twilio), WhatsApp Cloud API, Web Push / Firebase, Razorpay, **E-mail (SMTP)**, **MSG91 SMS** — keys, account details, prices per minute / message, health check |
| **Languages & Voices** | Languages offered, speech-to-text and voice routes per language |
| **Phone Numbers** | The number pool; assign numbers to companies; released numbers return to the pool |
| **WhatsApp Numbers / Templates** | Company WhatsApp numbers and the template library |
| **AI Employee Roles / AI Tools** | What kinds of AI Employee exist and which actions (tools) they may use |
| **AI Employees** | Oversight of every company's AI Employees: pause, conversations with tool logs |

A provider card with a red health mark needs attention (wrong key, expired account); the ops alert e-mail also reports it.

## Industries and templates

**Industries** → template versions (draft → published → archived): base instructions, qualification flow, handoff
rules, greetings, CRM fields, catalogue types, appointment types, lead statuses, scoring rules. Companies stay on their
version until they accept an update. **Clone** an industry to start a new one. **Lead Statuses**, **Lead Sources** and
**Holidays** are the platform defaults.

## Website and e-mails

- **Website Content**: every page and section of the public website (texts, images, legal pages), published at once.
- **Email Templates**: every e-mail the platform sends (welcome, verification, invoices, reminders, alerts, support…)
  with the variables each may use. Header / footer: General Settings → SEO & e-mail.

## Settings

- **General Settings**: branding, contact and company details (seller GSTIN and address on invoices), localisation,
  SEO and e-mail sender, maintenance mode.
- **System Settings** (tabs): Registration & team, Security (2FA for staff, lockout, sessions, IP allowlist, uploads,
  API limits), SMS, CRM, Calendar, AI, Knowledge base, Calling (legal hours and caps), Voice conversations, Human
  handoff, Website chat, WhatsApp, Team alerts, Campaigns, Dashboard & analytics, **Billing & GST** (seller state, SAC,
  invoice prefix, grace days), Support, **Data retention & privacy**, **Monitoring & alerts** (who gets platform alert
  e-mails and when).

Each setting shows its help text; the full list with defaults is in `docs/phase0/settings-registry.md`.

## Good practice

- Keep 2FA on for every staff account; remove leavers the same day (Users → lock / Sessions → end).
- Use **Sign in as this user** only with a reason the customer agreed to; it is audited.
- Change provider keys in Super Admin first, then revoke the old key at the provider.
- Check the dashboard's errors and provider health daily; answer support tickets the same day.
