# Phase 2 Gate — Website, Company Registration & Company Panel

Scope from PRD-01 Phase 2 plus decision D25 (Super Admin approval, AUTH-12). **Done** = built and tested; **Done (base)** = the Phase 2 part is built, the rest arrives in the phase named.

## Features

| ID | Feature | Status | Where |
|---|---|---|---|
| WEB-01 | Animated landing page | Done | eSoft index5 sections rendered from the CMS (`templates/website/sections/`), AOS / GSAP animations kept |
| WEB-02 | Website pages | Done | Home, How It Works, AI Employee Types, Industries (+ one page per active industry), Features, Pricing (live plans), About, Contact / Book a Demo, FAQ |
| WEB-03 | Legal pages | Done | Terms, Privacy, Refund, AI Usage — CMS rich text; the legal text itself is written by the client |
| WEB-04 | Website from Super Admin | Done | Every page and section (header, footer, CTA too) from Website Content; drafts private until published |
| WEB-05 | Registration entry | Done | "Get Started" and plan buttons open `/accounts/signup/` (plan passed with `?plan=`) |
| WEB-06 | Contact / demo enquiries | Done | Form → Super Admin → Enquiries (status, notes) + email to the team; honeypot + rate limit |
| WEB-07 | SEO & performance | Done (base) | Meta / OpenGraph / canonical per page, `sitemap.xml`, `robots.txt`, schema.org Organization, lazy images; CDN at hosting (P8) |
| WEB-08 | Responsive & accessible | Done | Template is responsive; skip link, focus outlines, labelled form fields, reduced-motion mode |
| AUTH-01 | Company registration | Done | All PRD fields; terms acceptance stored with time and IP; same form for the website and the app API |
| AUTH-02 | Verification | Done (base) | Email verification Mandatory / Optional from Super Admin; mobile OTP flow and switch built — SMS provider to be chosen by the client (development log until then) |
| AUTH-12 | Super Admin approval | Done | Pending → status page only (panel and API); approve / reject with reason, owner emailed, audited; switch in System Settings |
| AUTH-07 | Team management | Done | Invite by email (hashed single-use token), roles, resend / cancel, deactivate, transfer ownership, plan seat limit |
| AUTH-09 | Company profile | Done | Name, legal name, logo, address, GSTIN, contact, website, timezone, language |
| AUTH-10 | Onboarding checklist | Done (base) | Checklist with progress; profile and team steps complete now, AI Employee / knowledge / channel / test / activate steps are completed by P3–P6 features (`profile.mark_done`) |
| CP-01 | Company panel on Rizz | Done | Own sidebar and accent colour (General Settings → company panel colour) |
| CP-02 | Navigation | Done (shell) | Full menu per role and plan; later-phase screens open "coming soon" |
| CP-06 | Settings | Done (base) | Profile, business hours, holidays; channels and compliance in P5–P7 |
| SA-03 | Companies (approval) | Done | Approval card, pending filter, dashboard counter |
| — | Industries (list) | Done | Super Admin → Industries; templates added in P3 (SA-05) |

## REST API added

`/public/v1/`: `industries/`, `enquiries/`, `registration-options/`, `invitations/<token>/` · signup via `/api/v1/auth/app/v1/auth/signup`
`/api/v1/`: `company/` (GET / PATCH), `company/hours/`, `company/onboarding/`, `company/team/members/`, `company/team/invitations/`, `company/team/transfer-ownership/`, `me/phone-otp/`
`/api/v1/admin/`: `companies/<id>/approve|reject/`, `industries/`, `enquiries/`
Also fixed: API lists are now cursor-paginated (page size 25, `?page_size=` up to 100).

## Notes

- Seed website text describes the product only; no customer numbers, ratings or testimonials were invented. Testimonials stay hidden until real ones are added. Seed images are the template's own images — replace them with your screenshots in Super Admin.
- Rich-text fields accept HTML from Super Admin staff (trusted users), as in Phase 1.
- Form field labels and button captions on the registration and panel screens are interface text in the templates; all marketing content is in the CMS.

## Gate checklist

- [x] E2E test: register → verify (email / mobile) → pending → Super Admin approves → login → invite team member (`tests/test_registration.py`, `tests/test_team_and_company.py`)
- [x] Change any website section in Super Admin → visible without deployment (`tests/test_website.py`)
- [x] No template demo text left (automated check over every page and website template)
- [x] Cross-company tests for the new team endpoints
- [x] Lint, migrations check, Bandit (0 issues), pip-audit (no known vulnerabilities), 104 tests green locally
- [ ] GitHub CI green on the pushed commit
- [ ] Lighthouse ≥ 90 on mobile and desktop (measure on the demo server)
- [ ] Device testing: desktop, laptop, tablet, Android, iPhone
- [ ] Client sign-off
