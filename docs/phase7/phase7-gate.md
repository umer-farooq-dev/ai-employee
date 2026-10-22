# Phase 7 Gate — Dashboards, Subscription, Billing, Usage & Super Admin Completion

Scope from PRD-01 Phase 7 (client milestone 8: Admin + subscription). **Done** = built and tested; **Client** = needs
the client's account or decision (keys entered in Super Admin, never in .env).
Built in four parts: **1. Dashboard & analytics** → **2. Subscription, GST invoices, usage, credits, feature flags** →
**3. Super Admin billing, usage & margin, platform dashboard** → **4. Support, data export / deletion, retention,
e-mail & SMS providers**.

## Part 1 — Company dashboard and analytics

| ID | Feature | Status | Where |
|---|---|---|---|
| DASH-01 | KPI cards | Done | Dashboard: AI Employees, Calls (today), Connected, Qualified leads, Hot leads, Appointments, Conversions, Human transfers, AI usage — counted from the raw records |
| DASH-02 | Charts + filters | Done | Leads & calls (leads, calls, connected, qualified, appointments), Conversions, AI usage; Today / 7 days / 30 days / Custom; AI Employee filter. Hourly for one day, daily otherwise |
| DASH-03 / EMP-13 | Per-employee analytics | Done | Analytics page table per AI Employee; "Analytics" button on each AI Employee opens the page filtered to it |
| DASH-04 | Campaign funnel | Done | Analytics → Campaign funnels: in list → dialled → connected → qualified → hot → appointments for campaigns that ran in the period |
| DASH-05 | Live counters | Done | Cards and charts refresh in place every `analytics.refresh_seconds` while the page is visible |
| API | `/api/v1/analytics/` | Done | `range`, `from`, `to`, `employee`, `parts=kpis,series,employees,campaigns` |

Permission `analytics.view` (owner, manager). Agents keep the personal cards. Phone layout: 2 cards per row.

## Part 2 — Subscription, GST invoices, usage, credits, feature flags

| ID | Feature | Status | Where |
|---|---|---|---|
| SUB-03 | Razorpay subscriptions | Done (code) · **Client** (keys) | Plans page → Razorpay Checkout (card / UPI / net banking) with auto-renewal; prorated upgrade paid now (one-time order), downgrade and interval change at the next renewal, cancel at the period end and "keep subscription", failed renewals → overdue with grace days → billing hold. Webhook `/webhooks/razorpay/` (signature checked). Tested with a faked Razorpay; a live test waits for the client's test keys |
| SUB-03 | Trial and no-trial | Done | Trial reminder e-mail, trial end → billing hold until a plan is paid; with trials off a new company pays first |
| SUB-04 | Enterprise plans | Done | Super Admin → company → Billing: own price, own limits (with overage), own features, billing by invoice, manual invoices, mark paid |
| SUB-05 | Feature gating | Done | Plan limits enforced in API / UI / channels (hard stop or overage per limit); plan features remove menu, screens and API permissions; AI stops on billing hold or when hard AI credits are used up |
| SUB-06 | GST invoices | Done | CGST + SGST in the seller's state (or unknown buyer state), IGST across states; consecutive numbers per financial year (`INV/26-27/00001`); seller / buyer / place of supply copied at issue; SAC; amount in words; PDF (no extra library) |
| USE-02 | Billing page | Done | Plan, status, period, usage this month with what is left, AI credits, plan limits, usage details (minutes in/out, calls, WhatsApp, AI, speech), features, invoices with PDF, payment history, GST billing details |
| USE-03 | Limits & alerts | Done | Alerts at 80 / 100 % (Phase 6); hard stop or overage per limit; overage so far shown (invoicing of overage is USE-05, Phase 12) |
| USE-04 | Credits | Done | Monthly credits from the plan + Super Admin adjustments (+/−, reason, month) |
| NOTI-01 | Billing e-mails | Done | Receipt with the invoice PDF, invoice due, payment failed, trial ending, account on hold, plan changed |
| API | `/api/v1/billing/…` | Done | summary, plans, checkout, confirm, cancel, details, invoices (+ PDF), payments |

## Part 3 — Super Admin

| ID | Feature | Status | Where |
|---|---|---|---|
| SA-02 | Platform dashboard | Done | Companies, active AI Employees, calls today, minutes, MRR, revenue and provider cost this month, billing issues, AI / WhatsApp usage, approvals and enquiries waiting, errors (24 h), provider health, revenue chart |
| SA-12 | Plans & pricing | Done | Monthly / yearly price, GST rate, trial days, limits with "Stop / Allow overage" and overage price, features in the plan |
| SA-13 | Billing | Done | Subscriptions (overdue, on hold), all invoices (mark paid with method and reference, cancel, PDF), payments incl. failed; company billing page; GST settings in System Settings → Billing & GST |
| SA-14 / USE-06 | Usage & margin | Done | Per company and per provider per month: usage, provider cost, revenue (before GST), margin. Costs stored on every usage row: telephony per minute and WhatsApp per category (price fields in the provider's key popup), speech and AI model prices (model list) |
| SA-20 | Feature flags | Done | Per plan (plan form) and per company (company Billing page: plan / on / off) |

## Part 4 — Support, data, retention, providers

| ID | Feature | Status | Where |
|---|---|---|---|
| CP-05 | Raise tickets | Done | Company → Support: new ticket (category, priority, file), list, conversation, reply, close |
| SA-19 | Support | Done | Super Admin → Support Tickets: filters, reply, internal note, status, assign; team e-mail on new tickets and replies; bell + e-mail to the company on answers; auto close after `support.auto_close_days`. Website enquiries stay under Enquiries |
| TEN-07 / COMP-09 / CP-06 | Export & deletion | Done | Settings → Data & privacy: ZIP export (every table, files, recordings; secrets left out) with an expiring link; owner-only deletion after `privacy.deletion_grace_days`, cancellable; purge keeps invoices (tax law), releases numbers to the pool, removes users of only this company. Super Admin export is the same ZIP; Super Admin delete schedules the purge |
| SEC-12 | Retention | Done | Recordings and transcripts (calls, chats, WhatsApp) per company limits; API / error logs, audit log and alerts by System Settings → Data retention & privacy |
| SA-10 | E-mail, SMS, payment providers | Done · **Client** (accounts) | Voice & Channels: E-mail (SMTP — SES, SendGrid, Brevo, Zoho …), MSG91 SMS (DLT), Twilio SMS sender, Razorpay. All mail goes through the switched-on e-mail provider (.env mail is only the development fallback) |
| API | `/api/v1/support/tickets/…` | Done | list, create, detail, reply, close |

## Crons added (README)

`run_billing` (daily), `run_privacy` (daily), `close_stale_tickets` (daily).

## Client go-live needs for Phase 7

- Razorpay account: key id, key secret, webhook secret in Super Admin → Voice & Channels → Razorpay; webhook URL
  `https://<domain>/webhooks/razorpay/` with `subscription.*`, `order.paid`, `payment.failed`. Then test: subscribe,
  renew, payment failure, upgrade, downgrade, cancel (PRD test list).
- GST: seller state, GSTIN, legal name, address (General Settings → Contact), SAC code and invoice prefix
  (System Settings → Billing & GST) — confirm with the client's accountant.
- E-mail provider (SMTP) and SMS provider (MSG91 with DLT sender and template) accounts.
- Plan prices, yearly prices, limits, overage prices and features per plan.
- Provider prices for the margin report (telephony per minute, WhatsApp per category, model prices).
