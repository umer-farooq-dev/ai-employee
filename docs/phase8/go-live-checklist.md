# Go-Live Checklist — Production Settings Review

PRD-01 Phase 8: "every configurable value verified in Super Admin, none in code". Work through it on **staging** first,
then repeat on **production**. Tick each line and note who checked it. Infrastructure steps are in [runbook.md](runbook.md).

## A. Server and domain (client decision)

- [ ] Hosting provider, region (India recommended) and server size chosen; managed PostgreSQL with PITR (RPO ≤ 5 min) or
      self-hosted with daily dumps accepted in writing
- [ ] DNS: `<domain>`, `www`, `admin`, `voice` point at the server; HTTPS certificates issued (padlock on all four)
- [ ] `deploy/.env` filled from the example with new random secrets; a copy of `FIELD_ENCRYPTION_KEY` in the secret store
- [ ] `ENVIRONMENT=production` (blocks test-only providers such as FreeLLMAPI and demo data)
- [ ] `/healthz/` shows database, cache and scheduler "ok"; external uptime monitor set up on it
- [ ] Backups: first dump present, off-site copy job running, restore drill passed on this server (record in runbook §9)
- [ ] First Super Admin user created; staff accounts created with their roles (Roles & Permissions); 2FA set up by each

## B. Super Admin → General Settings

- [ ] Branding: platform name, tagline, logo, favicon, colours
- [ ] Contact & company details: legal name, GSTIN, address, support e-mail / phone, **team notification e-mails**
- [ ] Localisation: timezone Asia/Kolkata, date / number formats
- [ ] SEO & e-mail: site title and description, e-mail sender name and address (the verified sender of the e-mail
      provider), e-mail header / footer
- [ ] Maintenance mode **off**

## C. Super Admin → System Settings (every group opened and saved deliberately)

| Group | Check before launch |
|---|---|
| Registration & team | Registration open; **approval required** as agreed; **e-mail verification → Mandatory** (Optional during development); mobile OTP as agreed (needs the SMS provider); trial on/off and trial days; default plan |
| Security | **2FA mandatory for platform staff → on** (off during development); company 2FA policy; lockout attempts / minutes; session timeout; **Super Admin IP allowlist** (office / VPN addresses, if the client wants it); upload size and types; API rate limits back at their normal values (a load test raises them) |
| SMS (mobile OTP) | OTP texts (DLT-approved wording for MSG91) |
| CRM / Calendar | Lead number prefix, statuses and sources (own screens), reminder hours, holidays (own screen) |
| AI / Knowledge base | Request timeouts, evaluation thresholds, knowledge limits |
| Calling / Voice conversations / Human handoff | **Calling hours and attempt caps (legal limits)**, recording default and consent message, voice turn settings, handoff timeouts |
| Website chat / WhatsApp / Team alerts / Campaigns | Widget defaults, WhatsApp defaults, alert levels, campaign pacing |
| Dashboard & analytics | Default range, refresh seconds |
| Billing & GST | **Seller state, SAC code, invoice prefix, GST rate, prices include GST or not** (confirmed by the client's accountant), grace days, trial reminder days, invoice footer (bank details) |
| Support | Ticket categories, auto-close days |
| Data retention & privacy | Recordings / transcripts / logs / audit / alerts days, export link days, deletion grace days (as in the privacy policy) |
| Monitoring & alerts | **Alert e-mails** (on-call inbox), error threshold, window, cool-down |

## D. Providers (client accounts, keys only in Super Admin)

- [ ] AI Settings: production AI provider key(s), models loaded, **every task routed** with a fallback; FreeLLMAPI off;
      `run_ai_eval` passes on the production model
- [ ] Voice & Channels → telephony (Exotel / Plivo / Twilio): live account keys, webhooks pointing at
      `https://<domain>/...`, media at `wss://voice.<domain>`; price per minute filled (margin report)
- [ ] Languages & Voices: STT / TTS routes per language with live keys; speech prices filled
- [ ] Phone Numbers: live numbers in the pool; test inbound and outbound call per language
- [ ] WhatsApp: Meta Cloud API live number, webhook verified, templates approved; prices per category filled
- [ ] Razorpay: **live** key id / secret / webhook secret; webhook URL `https://<domain>/webhooks/razorpay/` with
      `subscription.*`, `order.paid`, `payment.failed`; one real low-value payment and refund
- [ ] E-mail (SMTP): provider account, domain SPF / DKIM / DMARC set, sender verified; test e-mail received
- [ ] SMS: MSG91 with DLT sender ID and template ids (if mobile OTP or SMS is used)
- [ ] Web Push / Firebase: keys if push notifications are used
- [ ] Every provider shows a green health check on its card

## E. Business content

- [ ] Plans & Pricing: monthly / yearly prices, GST rate, trial days, limits with stop / overage and overage prices,
      features per plan; enterprise plan; test plans archived
- [ ] Industries and AI Employee templates published (MVP: Real Estate, Travel & Tours, Education)
- [ ] Website Content: every page and section, legal pages (terms, privacy, refund), contact details
- [ ] Email Templates: every template read once (wording, links, branding)
- [ ] Lead statuses / sources, holidays for the year

## F. Final checks (UAT sign-off)

- [ ] Register a new company end to end → approval → AI Employee from template → test call → lead in CRM → appointment
      → WhatsApp message → invoice and payment
- [ ] Company panel, Super Admin and website checked on desktop, laptop, tablet, Android and iPhone
- [ ] Demo / test data removed (companies "Load test …", demo leads marked "demo")
- [ ] CI pipeline green for the release tag (tests, scans, Trivy, ZAP, restore drill, load test)
- [ ] External penetration test done; critical / high findings fixed and re-tested
- [ ] Client UAT sign-off and go-live approval recorded

| Section | Checked by | Date |
|---|---|---|
| A | | |
| B | | |
| C | | |
| D | | |
| E | | |
| F | | |
