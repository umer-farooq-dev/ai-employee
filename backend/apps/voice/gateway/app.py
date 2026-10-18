"""Voice Gateway (SDD §9): a separate asyncio service, one pipeline per call.

    wss /media/<vendor>   telephony media streams (Twilio / Plivo / Exotel), joined from the answer webhook
    wss /browser          browser test call from the company panel (VOICE-19, EMP-10)
    GET /healthz          liveness for any hosting

Every stream carries a signed call link (call id + signature) made by the platform; nothing else is accepted.
Run: python backend/manage.py run_voice_gateway
"""

import json

from asgiref.sync import sync_to_async
from fastapi import FastAPI, WebSocket
from loguru import logger
from pipecat.frames.frames import (
    EndFrame,
    Frame,
    InputAudioRawFrame,
    OutputAudioRawFrame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
)
from pipecat.runner.utils import parse_telephony_websocket
from pipecat.serializers.base_serializer import FrameSerializer
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport

from .. import session as voice_session
from . import speech
from .pipeline import run_call

BROWSER_RATE = 16000
TELEPHONY_RATE = 8000

app = FastAPI(title="AI Employee Voice Gateway", docs_url=None, redoc_url=None)


class BrowserSerializer(FrameSerializer):
    """Browser test call: raw 16-bit PCM both ways (binary), transcript / status messages as JSON text."""

    async def serialize(self, frame: Frame):
        if isinstance(frame, OutputAudioRawFrame):
            return frame.audio
        if isinstance(frame, (OutputTransportMessageFrame, OutputTransportMessageUrgentFrame)):
            return json.dumps(frame.message)
        return None

    async def deserialize(self, data):
        if isinstance(data, (bytes, bytearray)):
            return InputAudioRawFrame(audio=bytes(data), sample_rate=BROWSER_RATE, num_channels=1)
        try:
            message = json.loads(data)
        except (TypeError, ValueError):
            return None
        return EndFrame() if message.get("type") == "hangup" else None


def _telephony_serializer(transport_type, call_data, s):
    p = s.provider
    if transport_type == "twilio":
        from pipecat.serializers.twilio import TwilioFrameSerializer

        return TwilioFrameSerializer(
            stream_sid=call_data["stream_id"],
            call_sid=call_data["call_id"],
            account_sid=p.get("account_sid", ""),
            auth_token=p.get("secret", ""),
        )
    if transport_type == "plivo":
        from pipecat.serializers.plivo import PlivoFrameSerializer

        return PlivoFrameSerializer(
            stream_id=call_data["stream_id"],
            call_id=call_data["call_id"],
            auth_id=p.get("auth_id", ""),
            auth_token=p.get("secret", ""),
        )
    if transport_type == "exotel":
        from pipecat.serializers.exotel import ExotelFrameSerializer

        return ExotelFrameSerializer(stream_sid=call_data["stream_id"], call_sid=call_data["call_id"])
    raise ValueError(f"Unsupported telephony stream: {transport_type}")


async def _open(websocket, call_id, sig, vendor, mode):
    try:
        return await sync_to_async(voice_session.open_session, thread_sensitive=False)(call_id, sig, vendor, mode)
    except voice_session.SessionRefused as exc:
        logger.warning(f"voice: stream refused ({exc})")
        await websocket.close(code=4403)
        return None


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.websocket("/media/{vendor}")
async def media(websocket: WebSocket, vendor: str):
    await websocket.accept()
    transport_type, call_data = await parse_telephony_websocket(websocket)
    params = {**dict(websocket.query_params), **(call_data.get("body") or {})}
    s = await _open(websocket, params.get("call", ""), params.get("sig", ""), vendor, params.get("mode", "talk"))
    if s is None:
        return
    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            serializer=_telephony_serializer(transport_type, call_data, s),
        ),
    )
    try:
        await run_call(transport, s, TELEPHONY_RATE)
    except speech.SpeechUnavailable as exc:
        logger.error(f"voice: call {s.call_id} has no speech provider: {exc}")
        await sync_to_async(voice_session.close_session, thread_sensitive=False)(
            s, {"errors": [{"stage": "setup", "error": str(exc)[:200]}]}, "system"
        )
        await websocket.close(code=1011)


@app.websocket("/browser")
async def browser(websocket: WebSocket, call: str = "", sig: str = ""):
    await websocket.accept()
    s = await _open(websocket, call, sig, "browser", "talk")
    if s is None:
        return
    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            serializer=BrowserSerializer(),
        ),
    )
    try:
        await run_call(transport, s, BROWSER_RATE)
    except speech.SpeechUnavailable as exc:
        await websocket.send_text(json.dumps({"type": "error", "message": str(exc)}))
        await sync_to_async(voice_session.close_session, thread_sensitive=False)(
            s, {"errors": [{"stage": "setup", "error": str(exc)[:200]}]}, "system"
        )
        await websocket.close(code=1011)
