# QA Report — Phases 1 to 5

**Date:** 19 Oct 2026 · **Build:** `main` @ `30b2714` (not pushed) · **Tests:** 254 passing, lint clean, no pending migrations

## 1. What was tested and how

| Area | How it was checked |
|---|---|
| Every page, three roles | Automatic crawler opened all 88 fixed URLs as visitor, Super Admin and company owner, then followed every link (19 website, 184 Super Admin, 53 company pages). It looked for server errors, `None` on screen, raw template tags, placeholder text and missing static files. |
| Design, desktop | Full-page screenshots of all 26 Super Admin pages, 18 company pages and 14 website pages at 1440 px, with JavaScript errors and broken images logged per page. |
| Design, phone | Every website page and 20 panel pages opened as an iPhone (390 px, touch): no page may scroll sideways. |
| Real browser | Chrome: website sections one by one (with animations), Super Admin settings, company calls, recording playback, calling rules, Call now, schedule call, wizard voice/tools/rules, test console. |
| End-to-end flows | Super Admin approves a waiting company → owner e-mailed, AI Employee created from the template · CMS heading changed and published → visible on the website at once → reverted · calling rules wider than the platform limit → refused · Call now → clear provider message · follow-up call scheduled. |
| Requirements | Phase 5 scope compared line by line with the PRD (`docs/source/build_requirements.py`). |
| No hard-coding | Website templates scanned for literal text; logos, colours, images, icons and texts traced back to General Settings, CMS or the database. |

**Demo data** (for testing and client demos, all tagged `demo`): `python manage.py seed_demo --company "Ib Home"` creates 24 leads, 8 tasks, a calendar with 6 site visits, 8 properties, 5 approved FAQs, 3 website enquiries and one company waiting for approval.

## 2. Problems found and fixed

### Bugs (wrong behaviour)

| # | Problem | Fix |
|---|---|---|
| 1 | Phone calls would answer with the fallback message on every turn if Super Admin set only the chat route (the voice task had no fallback). | Calls use the voice route when set, otherwise the chat route. AI Settings now says "Not set — uses Chat conversations". |
| 2 | Calls that never report back (lost status webhook, browser test that never connected) stayed "live" forever and blocked the concurrent-call limit. | `dial_due_calls` closes them after the ring time / longest call (both from settings). |
| 3 | allauth phone API endpoint returned a server error (found in the error log). | Phone hooks mapped to the user's profile phone. |
| 4 | 404 and 500 pages were Django's bare defaults; the templates for them were never used. | 404 is an editable CMS page ("Page not found") with site header/footer; API paths get JSON. 500 is a self-contained page (works even when the database is down). |
| 5 | Getting-started checklist showed "Coming soon" for six steps that were built in Phases 3–5, and never ticked them. | Every step is worked out from real data (AI Employee, approved knowledge, catalogue, connected number, test passed, active). |
| 6 | AI Employee readiness always said "channel not connected". | Checks the connected phone number. |
| 7 | Plans and Industries lists ignored their sort order (Business, Enterprise, Pro, Starter). | Explicit ordering on every counted list. |
| 8 | Four e-mail templates (AI e-mails, handoff alert) showed "Available variables: None". | Variables filled from the templates themselves. |
| 9 | Website JavaScript stopped on the sign-up page (back-to-top script). | Guarded. |
| 10 | Calling rules form lost what was typed after an error; error wording unclear. | Values kept; "cannot be earlier/later/more than the platform limit". |
| 11 | Lead page hid the AI call card entirely when no number was connected. | Card explains how to enable calls. |
| 12 | Calendar events showed only the time, no customer or type. | Titles visible (template padding fixed). |
| 13 | AI test console header pushed the page sideways on phones. | Wraps. |

### Missing Phase 5 items (from the PRD check)

| Item | Added |
|---|---|
| EMP-10 test call to your own phone | "Test call to your phone" in the test console + API |
| HO-01 hand over upset callers | Rule per AI Employee; instruction text in System Settings |
| USE-01 STT / TTS consumption | STT seconds and TTS characters metered per call with the provider |
| VOICE-14 follow-up and appointment in the call record | Shown on call pages and in the API |

### Design and branding

| # | Problem | Fix |
|---|---|---|
| 1 | Website and both panels showed the **eSoft** logo; panels showed the icon twice. | Neutral "AI Employee" logo, icon and favicon as defaults (replace in General Settings). |
| 2 | Website images were the template's demo screenshots (HR dashboards, "Circle Soft", a stock photo, PayPal phone). | Replaced with real screenshots of this product (WebP, 535 KB total). Images set in Super Admin are never overwritten. |
| 3 | Section badges used the eSoft "S" icon. | Platform badge icon. |
| 4 | Template green mixed with brand colours (links, tabs, sidebar marker, toggles, calendar). | Everything follows General Settings: Super Admin = primary colour, company panel = company accent. |
| 5 | Three different date formats. | One format everywhere: 18 Oct 2026 23:44. Calendar headers Indian style (Sun, 18 Oct). |
| 6 | Company dashboard had only a checklist. | Live cards: leads (new this week), hot leads, calls today, upcoming appointments — each shown only with permission. |
| 7 | Development wording visible to users ("arrive in Phase 6", "from Phase 5, call"). | Plain wording everywhere (15 places + model help texts). |
| 8 | Drop-downs started with "---------". | "Choose…". |
| 9 | Missing sidebar icons (Phone Numbers, Sessions) showed grey boxes. | Fixed. |
| 10 | Industry page icon clipped at the screen edge; Education icon invisible (white). | Icon above the heading; coloured icon. |
| 11 | Footer copyright and links touching; light logo invisible in its preview; colour pickers full width. | Spaced; dark preview; compact pickers. |
| 12 | "Default plan key" was free text. | Drop-down of plans. |

### Clean-up

Removed unused template files: 37 Rizz demo pages, two unused `title-meta` partials, unused panel 404/500 pages.

## 3. Checked and fine

- No server errors on any page for any role; no broken images or static files; no JavaScript errors (after fix 9).
- No horizontal scrolling on phones on any website or panel page tested (after fix 13).
- Website text, buttons, images, plans and industries all come from the CMS / Plans / Industries / General Settings.
- Permissions: company pages return 404 to other companies; agents can listen to but not download recordings.
- Recording playback, calling-rule limits, Call now, scheduled calls, wizard voice / number / handoff rules, approval flow and CMS publishing work in the real UI.

## 4. Still open — needs the client or a later phase

| Item | Owner |
|---|---|
| Real logo, legal pages (Terms, Privacy, Refund, AI usage), testimonials | Client content (Super Admin → General Settings / Website) |
| Telephony provider and numbers; STT / TTS provider and voice per language | Client decision, keys in Super Admin |
| Real-call latency, 50+ calls per language, load test | After provider keys (Phase 5 gate) |
| WhatsApp, website chat, campaigns, push notifications | Phase 6 |
| Billing, usage display, payments | Phase 7 |
| Staff 2FA and mandatory e-mail verification | Phase 8 (paused by decision) |
| Push and GitHub CI run | When asked |

Note: `playwright` was installed in the local virtual environment for these checks only; it is not a project dependency.
