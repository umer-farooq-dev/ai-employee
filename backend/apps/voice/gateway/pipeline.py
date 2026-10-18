"""One async pipeline per call (SDD §9.1):

    caller audio → VAD → speech-to-text → user turn (end of speech, barge-in, silence)
                 → AgentBrain (same AI runtime as chat) → text-to-speech → caller audio → metrics / recording

VOICE-03 … 06: streaming STT / TTS, turn detection, filler while a tool runs, interruption.
VOICE-10: the opening (AI disclosure, recording announcement) is said by the platform before anything else.
VOICE-21: STT / TTS fail over through ServiceSwitcher; the reply language follows the caller (voice switches).
VOICE-22: latency per stage, interruptions, silences, recognition confidence and errors are collected per call.
"""

import asyncio
import random
import re
import statistics
import time

import aiohttp
from asgiref.sync import sync_to_async
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    EndFrame,
    ErrorFrame,
    Frame,
    InterimTranscriptionFrame,
    ManuallySwitchServiceFrame,
    MetricsFrame,
    OutputTransportMessageUrgentFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.metrics.metrics import TTFBMetricsData
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.service_switcher import ServiceSwitcher, ServiceSwitcherStrategyManual
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.turns.user_start import TranscriptionUserTurnStartStrategy, VADUserTurnStartStrategy
from pipecat.turns.user_stop import SpeechTimeoutUserTurnStopStrategy
from pipecat.turns.user_turn_processor import UserTurnProcessor
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

from apps.platform_config.services import get as setting

from .. import session as voice_session
from . import speech


def _settings():
    keys = (
        "voice.end_of_speech_ms",
        "voice.barge_in_enabled",
        "voice.filler_after_ms",
        "voice.silence_prompt_seconds",
        "voice.silence_hangup_seconds",
        "voice.stt_min_confidence_percent",
    )
    return {k.split(".", 1)[1]: setting(k) for k in keys}


class CallStats:
    """VOICE-22 per-call quality metrics."""

    def __init__(self):
        self.turns, self.errors, self.confidences = [], [], []
        self.interruptions = self.silences = 0
        self.turn_t0 = None
        self.current = {}
        self.ttfb = {}
        self.bot_speaking = False

    def turn_started(self):
        self.turn_t0 = time.monotonic()
        self.current = {}

    def mark(self, key, ms):
        self.current[key] = round(ms)

    def bot_started(self):
        self.bot_speaking = True
        if self.turn_t0 is not None:
            self.current["total_ms"] = round((time.monotonic() - self.turn_t0) * 1000)
            for kind in ("stt", "tts"):
                if kind in self.ttfb:
                    self.current[f"{kind}_ms"] = self.ttfb[kind]
            self.turns.append(self.current)
            self.turn_t0 = None

    def summary(self, extra=None):
        totals = sorted(t["total_ms"] for t in self.turns if "total_ms" in t)

        def pct(p):
            return totals[min(len(totals) - 1, int(round(p * (len(totals) - 1))))] if totals else None

        return {
            "turns": self.turns[-200:],
            "p50_ms": round(statistics.median(totals)) if totals else None,
            "p95_ms": pct(0.95),
            "interruptions": self.interruptions,
            "silences": self.silences,
            "stt_confidence": round(statistics.mean(self.confidences), 3) if self.confidences else None,
            "errors": self.errors[-50:],
            **(extra or {}),
        }


class AgentBrain(FrameProcessor):
    """Turns a finished caller turn into the AI's answer through the platform runtime."""

    def __init__(self, s, tuning, stats, tts_by_language, end_call, **kwargs):
        super().__init__(**kwargs)
        self.s, self.tuning, self.stats = s, tuning, stats
        self.tts_by_language, self.end_call = tts_by_language, end_call
        self.language = s.language
        self.parts, self.pending, self.stale = [], None, set()
        self.closing = False

    def phrase(self, key):
        texts = self.s.phrases.get(self.language) or next(iter(self.s.phrases.values()))
        return texts.get(key)

    async def show(self, role, text):
        """Live transcript for the browser test call (telephony serializers ignore these messages)."""
        await self.push_frame(
            OutputTransportMessageUrgentFrame(message={"type": "transcript", "role": role, "text": text})
        )

    async def speak(self, text, language=None):
        if not text:
            return
        if language and language != self.language and language in self.tts_by_language:
            if self.tts_by_language[language] is not self.tts_by_language.get(self.language):
                await self.push_frame(ManuallySwitchServiceFrame(service=self.tts_by_language[language]))
            self.language = language
        await self.show("ai", text)
        await self.push_frame(TTSSpeakFrame(spoken(text)))

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, TranscriptionFrame):
            text = (frame.text or "").strip()
            if text and direction == FrameDirection.DOWNSTREAM:
                self.parts.append(text)
                confidence = _confidence(frame)
                if confidence is not None:
                    self.stats.confidences.append(confidence)
            return
        if isinstance(frame, InterimTranscriptionFrame):
            return
        # the output transport reports bot speech upstream: latency per turn and interruptions are measured here
        if isinstance(frame, BotStartedSpeakingFrame):
            self.stats.bot_started()
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self.stats.bot_speaking = False
        elif isinstance(frame, ErrorFrame) and direction == FrameDirection.UPSTREAM:
            self.stats.errors.append({"stage": getattr(frame.processor, "name", ""), "error": str(frame.error)[:200]})
        if isinstance(frame, UserStartedSpeakingFrame) and direction == FrameDirection.DOWNSTREAM:
            if self.stats.bot_speaking:
                self.stats.interruptions += 1
            if self.pending and not self.pending.done():  # the caller spoke again: the old answer is stale
                self.stale.add(self.pending)  # the AI thread still finishes; its answer is not spoken
        await self.push_frame(frame, direction)
        if isinstance(frame, UserStoppedSpeakingFrame) and not self.closing:
            text, self.parts = " ".join(self.parts).strip(), []
            if text:
                self.stats.turn_started()
                await self.show("customer", text)
                self.pending = self.create_task(self.answer(text))

    async def answer(self, text):
        filler = self.create_task(self._filler()) if self.tuning["filler_after_ms"] else None
        t0 = time.monotonic()
        try:
            result = await sync_to_async(voice_session.agent_reply, thread_sensitive=False)(self.s, text)
        except Exception as exc:  # noqa: BLE001 — the caller hears the fallback, the error is logged
            logger.exception("voice: AI turn failed")
            self.stats.errors.append({"stage": "llm", "error": str(exc)[:200]})
            result = {"text": self.phrase("fallback"), "language": self.language, "ended": False, "transfer": None}
        finally:
            if filler:
                await self.cancel_task(filler)
        me = asyncio.current_task()
        if me in self.stale:  # superseded by the caller's next words: keep the transcript truthful
            self.stale.discard(me)
            await sync_to_async(voice_session.mark_unspoken, thread_sensitive=False)(self.s)
            return
        self.stats.mark("llm_ms", (time.monotonic() - t0) * 1000)
        await self.speak(result["text"], result.get("language"))
        if result.get("ended"):
            await self.end_call("ai", goodbye=False)

    async def _filler(self):
        await asyncio.sleep(self.tuning["filler_after_ms"] / 1000)
        fillers = self.phrase("fillers") or []
        if fillers:
            await self.push_frame(TTSSpeakFrame(random.choice(fillers)))  # nosec B311 — not security related

    async def say_and_note(self, key):
        """A platform phrase (silence prompt, goodbye) — spoken and kept in the transcript."""
        text = self.phrase(key)
        if text:
            await self.speak(text)
            await sync_to_async(voice_session.note, thread_sensitive=False)(self.s, "ai", text, {key: True})

    async def on_idle(self):
        """Caller silent: ask once per prompt period, hang up after the configured total."""
        if self.closing:
            return
        self.stats.silences += 1
        waited = self.stats.silences * self.tuning["silence_prompt_seconds"]
        if waited >= self.tuning["silence_hangup_seconds"]:
            await self.end_call("system", goodbye=True)
        else:
            await self.say_and_note("silence")


class StatsTap(FrameProcessor):
    """Collects timing and error frames at the end of the pipeline (VOICE-22)."""

    def __init__(self, stats, **kwargs):
        super().__init__(**kwargs)
        self.stats = stats

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, MetricsFrame):
            for data in frame.data:
                if isinstance(data, TTFBMetricsData) and data.value:
                    kind = "stt" if "STT" in data.processor else "tts" if "TTS" in data.processor else None
                    if kind:
                        self.stats.ttfb[kind] = round(data.value * 1000)
        elif isinstance(frame, ErrorFrame):
            self.stats.errors.append({"stage": getattr(frame.processor, "name", ""), "error": str(frame.error)[:200]})
        await self.push_frame(frame, direction)


def spoken(text):
    """Text for the voice: markdown, list markers and links removed (a model may still send them)."""
    text = re.sub(r"https?://\S+", "", text or "")
    text = re.sub(r"[*_`#>]+", "", text)
    text = re.sub(r"\s*\n+\s*(?:[-•]|\d+[.)])?\s*", ". ", text)
    text = re.sub(r"(?:\.\s*){2,}", ". ", text)
    text = re.sub(r"([?!।])\.", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text).strip(" .")
    return text + "." if text and text[-1] not in "?!।" else text


def _confidence(frame):
    result = frame.result
    try:
        if isinstance(result, dict):
            return float(result.get("confidence"))
        alt = result.channel.alternatives[0]  # Deepgram
        return float(alt.confidence)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return None


async def run_call(transport, s, sample_rate):
    """Run the pipeline for one call until it ends; then store metrics and the recording."""
    tuning = _settings()
    stats = CallStats()
    recorded = {"pcm": b"", "sample_rate": sample_rate, "channels": 2}
    hangup = {"by": "customer"}
    async with aiohttp.ClientSession() as http:
        plan = s.speech.get(s.language) or {"stt": [], "tts": []}
        stt, stt_errors = speech.chain("stt", plan["stt"], http)
        tts_by_language, built = {}, {}
        for code, routes in s.speech.items():
            if not routes["tts"]:
                continue
            same = speech.describe(routes["tts"]) + str([r.get("voice") for r in routes["tts"]])
            if same in built:  # identical routes (e.g. one multilingual voice): one service, not one per language
                tts_by_language[code] = built[same]
                continue
            try:
                tts_by_language[code] = built[same] = speech.chain("tts", routes["tts"], http)[0]
            except speech.SpeechUnavailable as exc:
                stats.errors.append({"stage": "tts", "error": str(exc)[:200]})
        if s.language not in tts_by_language:
            raise speech.SpeechUnavailable(f"No voice is set for {s.language}.")
        # the call's language speaks first; the others wait for the caller to switch language
        first = tts_by_language[s.language]
        voices = [first] + [v for v in dict.fromkeys(tts_by_language.values()) if v is not first]
        tts = (
            voices[0]
            if len(voices) == 1
            else ServiceSwitcher(services=voices, strategy_type=ServiceSwitcherStrategyManual)
        )
        stats.errors += [{"stage": "stt", "error": e[:200]} for e in stt_errors]

        worker_ref = {}

        async def end_call(by, goodbye=True):
            if brain.closing:
                return
            brain.closing = True
            hangup["by"] = by
            if goodbye:
                await brain.say_and_note("goodbye")
            await worker_ref["worker"].queue_frame(EndFrame())

        brain = AgentBrain(s, tuning, stats, tts_by_language, end_call)
        turns = UserTurnProcessor(
            user_turn_strategies=UserTurnStrategies(
                start=[
                    VADUserTurnStartStrategy(enable_interruptions=bool(tuning["barge_in_enabled"])),
                    TranscriptionUserTurnStartStrategy(enable_interruptions=bool(tuning["barge_in_enabled"])),
                ],
                stop=[SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=tuning["end_of_speech_ms"] / 1000)],
            ),
            user_idle_timeout=tuning["silence_prompt_seconds"],
        )

        @turns.event_handler("on_user_turn_idle")
        async def _idle(_processor):
            await brain.on_idle()

        recorder = AudioBufferProcessor(num_channels=2) if s.recording else None
        steps = [
            transport.input(),
            VADProcessor(vad_analyzer=SileroVADAnalyzer(params=VADParams(stop_secs=tuning["end_of_speech_ms"] / 1000))),
            stt,
            turns,
            brain,
            tts,
            transport.output(),
        ]
        if recorder:
            steps.append(recorder)

            @recorder.event_handler("on_audio_data")
            async def _audio(_buffer, audio, rate, channels):
                recorded.update(pcm=recorded["pcm"] + audio, sample_rate=rate, channels=channels)

        steps.append(StatsTap(stats))
        worker = PipelineWorker(
            Pipeline(steps),
            params=PipelineParams(
                audio_in_sample_rate=sample_rate, audio_out_sample_rate=sample_rate, enable_metrics=True
            ),
            idle_timeout_secs=None,
            enable_rtvi=False,
        )
        worker_ref["worker"] = worker

        @transport.event_handler("on_client_connected")
        async def _connected(_transport, _client):
            if recorder:
                await recorder.start_recording()
            await brain.speak(s.opening)
            if s.mode == "voicemail":
                await end_call("ai", goodbye=False)

        @transport.event_handler("on_client_disconnected")
        async def _disconnected(_transport, _client):
            await worker.cancel()

        async def _max_duration():
            await asyncio.sleep(s.max_seconds)
            await end_call("system", goodbye=True)

        limit = asyncio.create_task(_max_duration())
        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(worker)
        try:
            await runner.run()
        finally:
            limit.cancel()
            if recorder:
                await recorder.stop_recording()
            metrics = stats.summary(
                {
                    "providers": {
                        "stt": speech.describe(plan["stt"]),
                        "tts": speech.describe(s.speech[s.language]["tts"]),
                    }
                }
            )
            await sync_to_async(voice_session.close_session, thread_sensitive=False)(
                s, metrics, hangup["by"], recorded if s.recording else None
            )
