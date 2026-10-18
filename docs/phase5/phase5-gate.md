# Phase 5 Gate — Voice AI

Scope from PRD-01 Phase 5 (45 items). **Done** = built and tested; **Done (base)** = the Phase 5 part is built, the
rest arrives in the phase named.

## Features

| ID | Feature | Status | Where |
|---|---|---|---|
| SA-10 | Voice & channel providers | Done | Super Admin → Voice Settings: STT / TTS / telephony vendor cards (Sarvam, Deepgram, ElevenLabs, Cartesia, Google, Azure, OpenAI, Exotel, Plivo, Twilio; test-only local Whisper / Kokoro), key popup with the vendor's own fields, connection test, health, encrypted keys, test-only blocked in production |
| SA-11 | Languages & voices | Done | Super Admin → Languages & Voices: languages as data (code, locale, script, phrases), STT / TTS route per language with failover, voice catalogue (gender, style, sample, import from the provider) |
| VOICE-20 | Add languages without code | Done (mechanism) | New language row + routes + voices + phrases; detection by script; every form follows the list. Quality test per language in P11 |
| VOICE-07 / 08 / 09 | MVP languages, provider per language, voice catalogue | Done | Hindi / English / Bengali seeded with phrases; providers chosen per language in Super Admin (client's choice) |
| VOICE-16 | Phone-number management | Done | Super Admin → Phone Numbers (pool, give to a company, callback URLs to paste); company → Settings → Calling & numbers / wizard step 7 connects a number to an AI Employee |
| VOICE-01 | Inbound calls | Done | Answer webhook → AI Employee connected to the number → media stream to the Voice Gateway |
| VOICE-02 | Authorised outbound calls | Done | Call now (lead page, API), scheduled follow-up calls, retries; consent / DND, allowed countries, calling window, attempt caps, daily cap, plan limits checked before every dial |
| VOICE-03 … 06 | Real-time pipeline, low latency, natural conversation, barge-in | Done | Voice Gateway (Pipecat, `run_voice_gateway`): Silero VAD → streaming STT → user-turn detection (barge-in, silence prompts) → same AI runtime → streaming TTS; filler while the AI works; spoken-style prompt (setting) |
| VOICE-10 | AI identification | Done | Opening said by the platform: AI disclosure (employee → template → language text) + recording announcement |
| VOICE-11 / TOOL-08 | Call transfer | Done | `transfer_call` tool (calls only); warm transfer (agent hears the summary first), cold for vendors without whisper, next agent on no answer, no agent → message + callback task |
| VOICE-12 / REC-03 / COMP-06 | Recording & compliance | Done | On / off per company and AI Employee, announcement, encrypted storage per company, play / download by permission with short-lived links, every access audited, retention job `apply_voice_retention` |
| VOICE-13 | Transcript | Done | Speaker-labelled, time-stamped messages; unspoken answers, silence prompts, goodbye and voicemail marked |
| VOICE-14 / REC-01 | Post-call analysis / per-call record | Done | Duration, transcript, summary, requirement, score, sentiment / intent (confidence threshold), follow-up needed, appointments booked / moved / cancelled on the call, transfer status, outcome, numbers, language, recording, tools, usage (page + API) |
| VOICE-15 | Call logs | Done | Company → Calls (filters, detail with recording player, transcript, summary, fields, tools, handoff, quality, timeline) |
| VOICE-17 | Voicemail & no answer | Done | Answering-machine detection → voicemail message or hang up (setting); busy / no answer / voicemail retried after the gap within the caps (`dial_due_calls`) |
| VOICE-18 | Call limits | Done | Concurrent calls, calls and minutes per month (plan), calls per day, max duration, calling window (settings; company may tighten) |
| VOICE-19 / EMP-10 | Browser test call, test call to own number | Done | AI Employee test console → Voice test (microphone, live transcript) and "Test call to your phone" (the employee's number calls the tester, draft employees too, test data removed, never retried; plan limits and allowed countries apply) |
| VOICE-21 | Provider failover | Done | STT / TTS ServiceSwitcher failover per language route; LLM fallback from Phase 4 |
| VOICE-22 | Voice quality metrics | Done | Per call: latency per stage per turn, P50 / P95, interruptions, silences, recognition confidence, errors |
| HO-01 … HO-05 | Handoff | Done (voice) | Triggers (customer asks, keywords, knowledge gap, repeated failure, hot lead, upset caller — instruction text in System Settings → Human handoff), routing (assigned → team round robin → available, calendar-aware), screen pop + e-mail, no agent, handoff log. Chat / WhatsApp takeover in P6 |
| EMP-05 | Wizard voice | Done | Voices per language from the catalogue with sample preview, speaking speed |
| EMP-08 | Wizard phone | Done (phone) | Connect the company number; WhatsApp in P6 |
| ENG-07 | Mixed language (voice) | Done | Multilingual STT route; the voice follows the caller's language |
| CRM-11 | Lead detail | Done (+P5) | AI call card (Call now, schedule), calls on the timeline linking to the recording and transcript |
| SA-15 | Calls (all companies) | Done | Super Admin → Calls with 24 h quality summary, slow-call filter, detail, audited recording |
| CP-06 | Settings | Done (calling) | Settings → Calling & numbers: numbers, calling window, attempts, daily cap, recording, retention (within platform limits) |
| SEC-13 | Webhook verification | Done (telephony) | Twilio / Plivo signatures + per-provider URL token; de-duplicated callbacks. WhatsApp / Razorpay in P6 / P7 |
| COMP-02 | Consent records | Done | Every opt-in / opt-out stored per lead and channel with source and time; voice opt-out sets Do-not-call |
| USE-01 | Usage metering (voice) | Done (capture) | Calls, voice minutes (inbound / outbound), STT seconds and TTS characters (with the provider) per company, AI Employee, conversation; display in P7 |
| — | Stuck calls | Done | A call that never reports back (lost webhook, browser test that never connected) is closed by `dial_due_calls` after the ring time / longest call |
| ENGR-05 | Monitoring & alerting | Done (base) | Voice latency over the thresholds logged as a quality alert; Super Admin → Calls summary. Full monitoring stack in P8 |
| ENGR-07 | Load testing | Done (tool) | `voice_load_test --employee <id> --calls N --audio caller.wav` — set-up success, greeting time, answer P50 / P95 |

## Settings added (System Settings)

Calling (window, attempts, retry, voicemail action, ring time, max minutes, calls per day, allowed countries, DND
check, recording default and mode) · Voice conversations (end of speech, barge-in, filler, silence, recognition
confidence, latency alerts, spoken reply style) · Human handoff (ring time, agents tried, repeated failures, callback
delay) · Data retention (recordings, transcripts).

## REST API added

`/api/v1/phone-numbers/` · `/api/v1/calls/` (+ `schedule`, `cancel`, `recording`) · `/api/v1/calling-policy/` ·
`/api/v1/handoffs/` (+ `live`, `accept`) · `/api/v1/ai-employees/<id>/voice-test/` · `/api/v1/ai-employees/<id>/test-call/` · `/api/v1/admin/phone-numbers/` ·
`/api/v1/admin/languages/` (+ `routes`) · `/api/v1/admin/voices/` · `/api/v1/admin/ai-providers/<id>/voices/`

## Processes

Web app · Voice Gateway (`run_voice_gateway`, second process) · cron: `dial_due_calls` (every minute),
`apply_voice_retention` (daily)

## Gate checklist

- [x] Webhook signature + token checks, de-duplication, company isolation of calls / numbers / handoffs (RLS)
- [x] Compliance before every outbound dial (tests); company can only tighten the platform limits
- [x] Barge-in, transfer (warm / no answer / no agent), voicemail and provider failover logic covered by tests
- [x] End-to-end pipeline self-test with free local engines (Whisper + Kokoro + FreeLLMAPI) — audio in, AI answer out
- [x] Lint, migrations check, all tests green locally
- [ ] **Latency P50 / P95 per language on real test calls** with the client's telephony and speech providers (keys in Super Admin)
- [ ] **50+ scripted test calls per language** incl. code-mixed (`voice_load_test` + manual calls)
- [ ] Concurrent-call load test at the target agreed in P0 (`voice_load_test --calls N`)
- [ ] GitHub CI green on the pushed commit
- [ ] Client sign-off

_Decisions for the client: telephony provider and numbers, STT / TTS provider and voice per language._
