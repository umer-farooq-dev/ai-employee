# Phase 0 Proofs of Concept

Two small scripts, Python standard library only. Results go to `poc/output/` (git-ignored). Use dummy data only.

## 1. AI extraction (free LLM via FreeLLMAPI)

1. `docker compose --profile ai up -d`, open http://localhost:3001
2. Add free provider keys in the FreeLLMAPI dashboard (Groq, Gemini, Cerebras, Mistral, OpenRouter — one account each) and create an API key for clients.
3. In `.env`: `LLM_API_KEY=<that key>` (optional `LLM_BASE_URL`, `LLM_MODEL`)
4. `python poc/ai_extraction.py` → `poc/output/ai_report.md`

## 2. Voice bake-off (Hindi, English, Bengali)

1. In `.env` set any of: `SARVAM_API_KEY`, `GOOGLE_API_KEY`, `ELEVENLABS_API_KEY`
2. `python poc/voice_bakeoff.py` → `poc/output/voice_report.md` + WAV files
3. Listen to the WAV files, fill in naturalness, pick the best provider per language.

Both scripts have `--selftest` (no network).

Phase 0 gate needs: provider choice per language (VOICE-08) and an extraction accuracy baseline. Final latency targets (P50 ≤ 1.2 s, streaming) are measured in Phase 5 on the production providers.
