"""ENGR-07 concurrent-call simulation against a running Voice Gateway (browser-test streams, real STT / LLM / TTS).

    python backend/manage.py voice_load_test --employee <id> --calls 20 --audio caller.wav

Each simulated caller opens a test call, waits for the greeting, speaks the WAV (16 kHz mono 16-bit) and waits for
the AI's answer. Reports set-up success, time to greeting and time from end of speech to the first answer audio
(P50 / P95). Test calls are marked as tests and their records are removed like any test conversation.
"""

import asyncio
import json
import statistics
import time
import wave

from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand, CommandError

from apps.agents.models import AIEmployee
from apps.tenancy.context import company_context, platform_context
from apps.voice import services

FRAME = 640  # 20 ms at 16 kHz, 16-bit


def _pct(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, int(round(p * (len(values) - 1))))] if values else None


class Command(BaseCommand):
    help = "Simulate concurrent calls against the Voice Gateway and report latency (ENGR-07)."

    def add_arguments(self, parser):
        parser.add_argument("--employee", required=True, help="AI Employee id")
        parser.add_argument("--calls", type=int, default=5)
        parser.add_argument("--language", default="")
        parser.add_argument("--audio", default="", help="WAV, 16 kHz mono 16-bit, the caller's sentence")
        parser.add_argument("--timeout", type=int, default=60, help="Seconds to wait for each answer")

    def handle(self, *args, **opts):
        with platform_context():
            employee = AIEmployee.all_companies.select_related("company").filter(pk=opts["employee"]).first()
        if not employee:
            raise CommandError("Unknown AI Employee.")
        pcm = b""
        if opts["audio"]:
            with wave.open(opts["audio"], "rb") as w:
                if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (16000, 1, 2):
                    raise CommandError("The WAV must be 16 kHz, mono, 16-bit.")
                pcm = w.readframes(w.getnframes())
        results = asyncio.run(self._run(employee, opts, pcm))
        ok = [r for r in results if r.get("greeting_ms") is not None]
        answers = [r["answer_ms"] for r in results if r.get("answer_ms") is not None]
        report = {
            "calls": len(results),
            "connected": len(ok),
            "setup_success_percent": round(100 * len(ok) / len(results), 1) if results else 0,
            "greeting_p50_ms": _pct([r["greeting_ms"] for r in ok], 0.5),
            "answer_p50_ms": round(statistics.median(answers)) if answers else None,
            "answer_p95_ms": _pct(answers, 0.95),
            "errors": [r["error"] for r in results if r.get("error")][:10],
        }
        self.stdout.write(json.dumps(report, indent=1))

    async def _run(self, employee, opts, pcm):
        def start():
            with company_context(employee.company_id):
                return services.start_browser_test(employee, opts["language"])

        async def one(i):
            import websockets

            out = {}
            try:
                _call, url = await sync_to_async(start)()
                t0 = time.monotonic()
                async with websockets.connect(url, max_size=2**22, open_timeout=15) as ws:
                    first_audio = asyncio.get_running_loop().create_future()
                    answer = {"t": None, "sent": None}

                    async def reader():
                        async for msg in ws:
                            if isinstance(msg, bytes):
                                if not first_audio.done():
                                    first_audio.set_result(time.monotonic())
                                if answer["sent"] and answer["t"] is None:
                                    answer["t"] = time.monotonic()

                    task = asyncio.create_task(reader())
                    out["greeting_ms"] = round((await asyncio.wait_for(first_audio, 30) - t0) * 1000)
                    await asyncio.sleep(4)  # let the greeting play
                    for k in range(0, len(pcm), FRAME):
                        await ws.send(pcm[k : k + FRAME])
                        await asyncio.sleep(0.02)
                    for _ in range(50):  # 1 s of silence ends the turn
                        await ws.send(b"\x00" * FRAME)
                        await asyncio.sleep(0.02)
                    answer["sent"] = time.monotonic()
                    deadline = answer["sent"] + opts["timeout"]
                    while pcm and answer["t"] is None and time.monotonic() < deadline:
                        await ws.send(b"\x00" * FRAME)
                        await asyncio.sleep(0.02)
                    if answer["t"]:
                        out["answer_ms"] = round((answer["t"] - answer["sent"]) * 1000)
                    await ws.send(json.dumps({"type": "hangup"}))
                    task.cancel()
            except Exception as exc:  # noqa: BLE001 — every failure is part of the report
                out["error"] = f"call {i}: {exc.__class__.__name__}: {exc}"[:200]
            return out

        return await asyncio.gather(*(one(i) for i in range(opts["calls"])))
