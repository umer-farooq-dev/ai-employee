# Phase 0 Proofs of Concept — run DEFERRED

Owner decision: voice and AI testing happens **after the system is built**. Providers and their keys are added in
**Super Admin** (AI Providers in Phase 4, Voice Providers in Phase 5) — never in `.env` or code. When those screens
exist, these scripts are switched to read provider settings from Super Admin and then run.

| Script | Purpose |
|---|---|
| `voice_bakeoff.py` | Sarvam / Google / ElevenLabs TTS + STT for Hindi, English, Bengali: latency, character error rate, WAV files for listening |
| `ai_extraction.py` | 10 Hinglish / Hindi / Bengali / English sentences → CRM fields (location, BHK, budget …) accuracy on any OpenAI-compatible model |

Both scripts use only the Python standard library and have `--selftest` (no network), which runs in CI.
Results go to `poc/output/` (git-ignored). Dummy data only.
