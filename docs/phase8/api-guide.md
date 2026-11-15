# API Guide — AI Employee Platform

For developers of the mobile app (Flutter) and of integrations. Every feature of the company panel and Super Admin is
available through the same REST API; the web panels and the app share data, permissions and business rules.

- **Interactive reference (always current):** `https://<domain>/api/v1/docs/` (Swagger UI)
- **OpenAPI 3 schema:** `https://<domain>/api/v1/schema/` — generate the Dart client from it
  (e.g. `openapi-generator-cli generate -g dart-dio -i schema.yml`)
- Base URL: `https://<domain>/api/v1/` · JSON in and out · times in UTC (ISO 8601) · money in **paise** (integer) ·
  phone numbers in E.164 (`+91…`) · ids are UUIDs

## 1. Signing in (app)

The app uses allauth's headless API with **JWT Bearer tokens** (web pages use the session cookie instead).

```http
POST /api/v1/auth/app/v1/auth/login
Content-Type: application/json

{"email": "owner@company.in", "password": "…"}
```
Response `200`: `meta.access_token` (short-lived, default 5 min) and `meta.refresh_token` (default 24 h).
If 2FA is on, the response is `401` with a pending flow; finish it with
`POST /api/v1/auth/app/v1/auth/2fa/authenticate` `{"code": "123456"}`.

Every API call then sends `Authorization: Bearer <access_token>`. Refresh before expiry:
```http
POST /api/v1/auth/app/v1/tokens/refresh
{"refresh_token": "…"}
```
Other auth endpoints (sign-up, password reset, e-mail verification, 2FA set-up, sessions, logout) are under
`/api/v1/auth/app/v1/…`; their own OpenAPI document is served at `/api/v1/auth/openapi.html`.

Company and user context: the company comes from the signed-in user's membership — never send a company id. A user's
role decides what they may do (same permissions as the panel); a missing permission returns `403`.

## 2. Conventions

| Topic | Rule |
|---|---|
| Lists | Cursor pagination: `{"next": url|null, "previous": url|null, "results": [...]}`; `?page_size=` up to 100 (default 25). Follow `next` as given |
| Filters / search | Per endpoint, listed in the reference (e.g. `/crm/leads/?search=Ra&status=hot&owner=<id>`) |
| Create / update | `POST` list URL; `PATCH` detail URL for partial updates; `PUT` only where documented |
| Errors | Always `{"error": {"code", "message", "details", "request_id"}}` — show `message`, log `request_id` |
| Validation errors | `400`, `code: "invalid"`, field errors in `details` (`{"phone": ["Enter a valid number."]}`) |
| Request id | Every response has `X-Request-ID`; send your own `X-Request-ID` to trace a call end to end |
| Rate limits | Per user, per company and per IP (Super Admin → System Settings → Security). `429` with `Retry-After` |
| Uploads | `multipart/form-data` with a `file` field; types and size from Super Admin → Security |
| Private files | Recordings and company files come as short-lived signed URLs (`/files/<token>/`); do not store them |

**Special `403` codes** (the app should show a screen for each):

| `error.code` | Meaning | App behaviour |
|---|---|---|
| `company_pending` / `company_rejected` | Company not approved yet / rejected | Status screen |
| `company_suspended` | Suspended by the platform | Contact support |
| `phone_verification_required` | Mobile OTP required | `/me/phone-otp/` flow |
| `mfa_required` | 2FA mandatory but not set up | Ask the user to set up 2FA |
| `billing_hold` | Subscription unpaid | Billing screen (billing, support, notifications stay available) |
| `feature_off` | Feature not in the plan (e.g. API access) | Upgrade message |

## 3. Endpoints by area

Paths are relative to `/api/v1/`. The reference lists every method, field and filter.

| Area | Endpoints |
|---|---|
| Me & company | `me/` (profile, availability), `me/phone-otp/`, `company/`, `company/hours/`, `company/onboarding/`, `company/template/`, `company/team/`, `company/team/members/`, `company/team/invitations/`, `company/team/transfer-ownership/` |
| CRM | `crm/leads/` (+ notes, activities, assign, status), `crm/tasks/`, `crm/fields/`, `crm/scoring-rules/`, `crm/assignment-rules/`, `crm/imports/`, `crm/config/` |
| Catalogue | `catalog/items/`, `catalog/collections/`, `catalog/types/`, `catalog/imports/` |
| Calendar | `calendar/appointments/`, `calendar/resources/`, `calendar/config/`, `calendar/messages/` |
| AI Employees | `ai-employees/` (+ test chat, activate, pause), `ai-employees/<id>/widget/`, `conversations/` |
| Knowledge | `kb/sources/`, `kb/faqs/`, `kb/unanswered/`, `kb/test-query/` |
| Calls | `calls/` (+ recording link, call now, schedule), `phone-numbers/`, `calling-policy/`, `handoffs/` |
| Inbox & WhatsApp | `inbox/` (website chat and WhatsApp conversations, take over, reply, hand back), `whatsapp/numbers/`, `whatsapp/templates/`, `whatsapp/messages/`, `whatsapp/send/` |
| Campaigns | `campaigns/` (+ members, start, pause, stop, export) |
| Analytics | `analytics/?range=today|7d|30d|custom&from=&to=&employee=&parts=kpis,series,employees,campaigns` |
| Billing | `billing/` (summary), `billing/plans/`, `billing/checkout/`, `billing/confirm/`, `billing/cancel/`, `billing/details/`, `billing/invoices/` (+ `pdf/`), `billing/payments/` |
| Support | `support/tickets/` (list, create with file, detail, reply, close) |
| Notifications | `notifications/` (list, read, read all), `devices/` (register a push token), `push/config/` |
| Super Admin (staff) | `admin/…`: companies, users, roles, plans, industries and templates, lead statuses / sources, holidays, employee roles, AI providers, AI routes, languages / voices, phone and WhatsApp numbers, tools, AI Employees, conversations, CMS, e-mail templates, settings, uploads, sessions, logs |

**Public (no sign-in)**, used by the website and the chat widget: `/public/v1/branding/`, `cms/<key>/`, `plans/`,
`enquiries/`, `registration-options/`, `invitations/<token>/`, and the widget's `chat/<key>/…`. These are rate-limited
per IP.

## 4. Webhooks (providers → platform)

Configured in each provider's console; secrets are entered in Super Admin and every request's signature is checked.

| Provider | URL |
|---|---|
| Telephony (Twilio / Plivo / Exotel) | Answer, status and recording URLs are set per number automatically under `https://<domain>/webhooks/telephony/<provider>/<token>/…`; media streams use `wss://voice.<domain>/media/<vendor>` |
| WhatsApp (Meta Cloud API) | `https://<domain>/webhooks/whatsapp/<provider key>/` — shown on the provider card in Super Admin (verify token and app secret are entered there) |
| Razorpay | `https://<domain>/webhooks/razorpay/` with `subscription.*`, `order.paid`, `payment.failed` |

## 5. Push notifications

Register the device after sign-in: `POST /api/v1/devices/` `{"platform": "android|ios|web", "token": "<FCM token or
web push endpoint>", "name": "Pixel 7"}` (web push also sends its `keys`); remove it on sign-out with
`POST /api/v1/devices/remove/` `{"token": "…"}`. `GET /api/v1/push/config/` returns the public keys the app
needs. Notification kinds (handoff, hot lead, appointment, usage, support…) match the in-app notification centre.

## 6. Versioning and changes

`/api/v1/` changes only in backward-compatible ways (new fields, new endpoints). A breaking change gets `/api/v2/`
with the old version kept for the app's update period. Ignore unknown fields in responses.

## 7. Quick test with curl

```bash
TOKEN=$(curl -s -X POST https://<domain>/api/v1/auth/app/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"you@company.in","password":"…"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['meta']['access_token'])")
curl -s https://<domain>/api/v1/crm/leads/?page_size=5 -H "Authorization: Bearer $TOKEN"
```
