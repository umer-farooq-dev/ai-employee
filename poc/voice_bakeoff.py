"""Phase 0 voice PoC: compare STT / TTS providers for Hindi, English and Bengali.

For every language and sentence:
  * TTS: each provider speaks the sentence -> request latency + a WAV file saved for human listening
  * STT: each provider transcribes reference audio (TTS output of another provider) -> latency + character error rate

DEFERRED (owner decision): run after the system is built. Provider keys are never put in .env;
when Voice Providers exist in Super Admin (Phase 5) this script will read them from there.
Until then providers run only when their key is set in the process environment:
  SARVAM_API_KEY, GOOGLE_API_KEY (Cloud Speech-to-Text + Text-to-Speech enabled), ELEVENLABS_API_KEY
  optional: ELEVENLABS_VOICE_ID, ELEVENLABS_TTS_MODEL (default eleven_v3), SARVAM_TTS_MODEL (default bulbul:v4-flash)

Run:  python poc/voice_bakeoff.py            -> writes poc/output/voice_report.md and WAV files
      python poc/voice_bakeoff.py --selftest -> checks the scoring helpers, no network

Note: plain REST calls, so latency is full-response time. Streaming time-to-first-audio is measured in Phase 5.
"""

import base64
import io
import json
import os
import statistics
import sys
import time
import unicodedata
import urllib.request
import uuid
import wave
from pathlib import Path

OUT = Path(__file__).parent / "output"
RATE = 16000

SENTENCES = {
    "hi-IN": [
        "नमस्ते, मैं एबीसी प्रॉपर्टीज़ की एआई असिस्टेंट सारा बोल रही हूँ।",
        "मुझे न्यू टाउन में दो बीएचके फ्लैट चाहिए, बजट लगभग सत्तर लाख है।",
        "क्या आप इस रविवार को साइट विज़िट के लिए आ सकते हैं?",
        "मुझे New Town में 2BHK चाहिए, budget around 70 lakh है।",
    ],
    "en-IN": [
        "Hello, this is Sara, the AI assistant from ABC Properties.",
        "I am looking for a two bedroom flat in New Town under seventy lakh rupees.",
        "Can you visit the site this Sunday at eleven in the morning?",
    ],
    "bn-IN": [
        "নমস্কার, আমি এবিসি প্রপার্টিজের এআই সহকারী সারা বলছি।",
        "আমার নিউ টাউনে দুই বিএইচকে ফ্ল্যাট চাই, বাজেট প্রায় সত্তর লাখ।",
        "আপনি কি এই রবিবার সাইট দেখতে আসতে পারবেন?",
    ],
}


# ---------------------------------------------------------------- helpers


def http(url, body=None, headers=None, files=None):
    """POST JSON or multipart; returns (bytes, seconds)."""
    headers = dict(headers or {})
    if files is not None:
        boundary = uuid.uuid4().hex
        parts = []
        for name, value in (body or {}).items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        for name, (filename, data, ctype) in files.items():
            head = f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            parts.append(head.encode() + f"Content-Type: {ctype}\r\n\r\n".encode() + data + b"\r\n")
        data = b"".join(parts) + f"--{boundary}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    else:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = resp.read()
    return payload, time.perf_counter() - start


def pcm_to_wav(pcm, rate=RATE):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def wav_to_pcm(wav_bytes):
    with wave.open(io.BytesIO(wav_bytes)) as w:
        return w.readframes(w.getnframes()), w.getframerate()


def normalize(text):
    text = unicodedata.normalize("NFC", text).lower()
    keep = [c if (c.isalnum() or unicodedata.category(c).startswith("M") or c.isspace()) else " " for c in text]
    return " ".join("".join(keep).split())


def cer(reference, hypothesis):
    """Character error rate (Levenshtein distance / reference length) after normalisation."""
    ref, hyp = normalize(reference), normalize(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, rc in enumerate(ref, 1):
        cur = [i]
        for j, hc in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc)))
        prev = cur
    return prev[-1] / len(ref)


# ---------------------------------------------------------------- providers (return WAV bytes / transcript)
def tts_sarvam(text, lang):
    body = {
        "text": text,
        "language_code": lang,
        "model": os.environ.get("SARVAM_TTS_MODEL", "bulbul:v4-flash"),
        "speech_sample_rate": RATE,
        "output_audio_codec": "wav",
    }
    raw, secs = http(
        "https://api.sarvam.ai/text-to-speech", body, {"api-subscription-key": os.environ["SARVAM_API_KEY"]}
    )
    return base64.b64decode(json.loads(raw)["audios"][0]), secs


def tts_google(text, lang):
    body = {
        "input": {"text": text},
        "voice": {"languageCode": lang},
        "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": RATE},
    }
    raw, secs = http(f"https://texttospeech.googleapis.com/v1/text:synthesize?key={os.environ['GOOGLE_API_KEY']}", body)
    return base64.b64decode(json.loads(raw)["audioContent"]), secs  # LINEAR16 content includes a WAV header


def tts_elevenlabs(text, lang):
    voice = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=pcm_{RATE}"
    body = {"text": text, "model_id": os.environ.get("ELEVENLABS_TTS_MODEL", "eleven_v3")}
    raw, secs = http(url, body, {"xi-api-key": os.environ["ELEVENLABS_API_KEY"]})
    return pcm_to_wav(raw), secs


def stt_sarvam(wav, lang):
    raw, secs = http(
        "https://api.sarvam.ai/speech-to-text",
        {"model": "saaras:v4", "language_code": lang},
        {"api-subscription-key": os.environ["SARVAM_API_KEY"]},
        files={"file": ("a.wav", wav, "audio/wav")},
    )
    return json.loads(raw)["transcript"], secs


def stt_google(wav, lang):
    pcm, rate = wav_to_pcm(wav)
    body = {
        "config": {"encoding": "LINEAR16", "sampleRateHertz": rate, "languageCode": lang},
        "audio": {"content": base64.b64encode(pcm).decode()},
    }
    raw, secs = http(f"https://speech.googleapis.com/v1/speech:recognize?key={os.environ['GOOGLE_API_KEY']}", body)
    results = json.loads(raw).get("results", [])
    return " ".join(r["alternatives"][0]["transcript"] for r in results), secs


def stt_elevenlabs(wav, lang):
    raw, secs = http(
        "https://api.elevenlabs.io/v1/speech-to-text",
        {"model_id": "scribe_v1", "language_code": lang[:2]},
        {"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
        files={"file": ("a.wav", wav, "audio/wav")},
    )
    return json.loads(raw)["text"], secs


PROVIDERS = {  # name: (key env var, tts fn, stt fn)
    "sarvam": ("SARVAM_API_KEY", tts_sarvam, stt_sarvam),
    "google": ("GOOGLE_API_KEY", tts_google, stt_google),
    "elevenlabs": ("ELEVENLABS_API_KEY", tts_elevenlabs, stt_elevenlabs),
}


# ---------------------------------------------------------------- run
def run():
    active = {n: p for n, p in PROVIDERS.items() if os.environ.get(p[0])}
    if not active:
        sys.exit("No provider keys found. Voice PoC is deferred until providers are set up in Super Admin.")
    OUT.mkdir(exist_ok=True)
    tts_rows, stt_rows, transcripts = [], [], []
    for lang, sentences in SENTENCES.items():
        refs = {}  # sentence index -> reference WAV (first provider that succeeded)
        for name, (_, tts, _) in active.items():
            times = []
            for i, text in enumerate(sentences):
                try:
                    wav, secs = tts(text, lang)
                except Exception as exc:  # report and continue with the next provider
                    times.append(None)
                    print(f"TTS {name} {lang} #{i}: {exc}")
                    continue
                times.append(secs)
                (OUT / f"tts_{name}_{lang}_{i}.wav").write_bytes(wav)
                refs.setdefault(i, (name, wav))
            ok = [t for t in times if t is not None]
            tts_rows.append((lang, name, len(ok), len(times), statistics.median(ok) * 1000 if ok else None))
        for name, (_, _, stt) in active.items():
            times, errors = [], []
            for i, text in enumerate(sentences):
                if i not in refs:
                    continue
                src, wav = refs[i]
                try:
                    hyp, secs = stt(wav, lang)
                except Exception as exc:
                    print(f"STT {name} {lang} #{i}: {exc}")
                    continue
                times.append(secs)
                errors.append(cer(text, hyp))
                transcripts.append((lang, name, src, text, hyp, errors[-1]))
            stt_rows.append(
                (
                    lang,
                    name,
                    len(times),
                    statistics.median(times) * 1000 if times else None,
                    statistics.mean(errors) if errors else None,
                )
            )
    write_report(tts_rows, stt_rows, transcripts)


def fmt(v, pattern):
    return "—" if v is None else pattern.format(v)


def write_report(tts_rows, stt_rows, transcripts):
    lines = [
        "# Voice PoC report",
        "",
        f"Generated {time.strftime('%Y-%m-%d %H:%M')}. Latency = full REST response time.",
        "",
        "## Text-to-speech",
        "",
        "| Language | Provider | OK | Median latency (ms) | Naturalness 1-5 (fill in after listening) |",
        "|---|---|---|---|---|",
    ]
    lines += [f"| {lang} | {n} | {ok}/{tot} | {fmt(ms, '{:.0f}')} |  |" for lang, n, ok, tot, ms in tts_rows]
    lines += [
        "",
        "## Speech-to-text (loopback on TTS audio)",
        "",
        "| Language | Provider | Samples | Median latency (ms) | CER |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| {lang} | {n} | {cnt} | {fmt(ms, '{:.0f}')} | {fmt(c, '{:.1%}')} |" for lang, n, cnt, ms, c in stt_rows
    ]
    lines += [
        "",
        "## Transcripts",
        "",
        "| Language | STT | Audio from | Reference | Transcript | CER |",
        "|---|---|---|---|---|---|",
    ]
    lines += [f"| {lg} | {n} | {src} | {ref} | {hyp} | {c:.1%} |" for lg, n, src, ref, hyp, c in transcripts]
    lines += [
        "",
        "Listen to `poc/output/tts_*.wav` and fill in naturalness. Decision per language goes into PRD-01 VOICE-08.",
    ]
    (OUT / "voice_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Report: {OUT / 'voice_report.md'}")


def selftest():
    assert cer("hello world", "hello world") == 0
    assert abs(cer("abcd", "abed") - 0.25) < 1e-9
    assert cer("Hello, World!", "hello world") == 0  # punctuation and case ignored
    assert cer("नमस्ते", "नमस्ते") == 0  # Devanagari combining marks kept
    pcm = b"\x01\x00" * RATE
    assert wav_to_pcm(pcm_to_wav(pcm)) == (pcm, RATE)
    print("selftest ok")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else run()
