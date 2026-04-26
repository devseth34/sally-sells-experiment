"""Custom ElevenLabs adapter for audio-tag-enabled TTS.

Why this exists:
    The `livekit-plugins-elevenlabs` package uses a streaming WebSocket
    path that does NOT render audio tags like [laughs] or [sighs] — it
    reads them as literal text. The ElevenLabs REST API (via the official
    SDK) DOES render them as real sounds when model_id=eleven_v3.

    This adapter wraps `AsyncElevenLabs.text_to_speech.stream()` and
    conforms to the `livekit.agents.tts.TTS` interface so the runner
    can plug it in alongside the livekit Flash plugin transparently.

Model:
    eleven_v3 — required for audio tag rendering. Flash/Turbo models
    read tags literally regardless of endpoint or parameters.

Confirmed working tags (from live testing 2026-04-26):
    [laughs]  [sighs]  [exhales]  [whispers]  [excited]  [crying]
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Optional

from elevenlabs.client import AsyncElevenLabs
from livekit.agents import tts as lk_tts
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions
from livekit.agents.utils import shortuuid

logger = logging.getLogger("sally.voice.eleven_v3")

_MODEL = "eleven_v3"
MAX_CHARS = 4800  # safety margin under ElevenLabs' 5000-char limit


# ── Exceptions ────────────────────────────────────────────────────────

class V3Error(Exception):
    """Base for adapter errors."""

class V3AuthError(V3Error):
    """Bad or missing API key."""

class V3TextTooLongError(V3Error):
    """Text exceeds MAX_CHARS. Runner falls back to Flash."""

class V3RateLimitError(V3Error):
    """429 rate limit."""

class V3ServerError(V3Error):
    """5xx after retry."""


# ── Local types ───────────────────────────────────────────────────────

@dataclass
class VoiceSettings:
    """Local copy — avoids importing from elevenlabs package at module level.

    stability=0.5 corresponds to v3's "Natural" mode per the ElevenLabs
    docs. The "Robust" mode (~0.7+) reduces responsiveness to directional
    prompts (audio tags, [softly], [reassuring], etc.) — exactly what
    we need for sally_emotive's tag director output. Don't raise this
    above 0.5 without re-validating that audio tags still render.
    similarity_boost=0.75 keeps Jessica recognizable across emotive turns.
    """
    stability: float = 0.5
    similarity_boost: float = 0.75


# ── Adapter ───────────────────────────────────────────────────────────

class ElevenLabsV3TTS(lk_tts.TTS):
    """Drop-in TTS using AsyncElevenLabs SDK for audio tag rendering."""

    def __init__(
        self,
        *,
        voice_id: str,
        api_key: str,
        voice_settings: Optional[VoiceSettings] = None,
        sample_rate: int = 24000,
        timeout_s: float = 30.0,
    ) -> None:
        super().__init__(
            capabilities=lk_tts.TTSCapabilities(streaming=False),
            sample_rate=sample_rate,
            num_channels=1,
        )
        if not api_key:
            raise V3AuthError("api_key is required for ElevenLabsV3TTS")
        self._voice_id = voice_id
        self._api_key = api_key
        self._vs = voice_settings or VoiceSettings()
        self._timeout_s = timeout_s
        self._client: Optional[AsyncElevenLabs] = None

    @property
    def model(self) -> str:
        return _MODEL

    @property
    def provider(self) -> str:
        return "elevenlabs"

    def _get_client(self) -> AsyncElevenLabs:
        if self._client is None:
            self._client = AsyncElevenLabs(
                api_key=self._api_key,
                timeout=self._timeout_s,
            )
        return self._client

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> "_V3ChunkedStream":
        return _V3ChunkedStream(
            tts=self,
            input_text=text,
            conn_options=APIConnectOptions(max_retry=0, timeout=conn_options.timeout),
        )

    async def aclose(self) -> None:
        # Let the SDK manage its own connection lifecycle.
        self._client = None


# ── ChunkedStream ─────────────────────────────────────────────────────

class _V3ChunkedStream(lk_tts.ChunkedStream):

    @property
    def _v3(self) -> ElevenLabsV3TTS:
        return self._tts  # type: ignore[return-value]

    async def _run(self, output_emitter: lk_tts.AudioEmitter) -> None:
        text = self._input_text or ""
        if len(text) > MAX_CHARS:
            raise V3TextTooLongError(
                f"Text length {len(text)} exceeds {MAX_CHARS}; falling back to Flash"
            )

        tts = self._v3
        client = tts._get_client()

        output_emitter.initialize(
            request_id=shortuuid(),
            sample_rate=tts.sample_rate,
            num_channels=tts.num_channels,
            mime_type="audio/pcm",
            stream=False,
        )

        from elevenlabs import VoiceSettings as SDKVoiceSettings

        first_chunk = True
        async for chunk in client.text_to_speech.stream(
            voice_id=tts._voice_id,
            text=text,
            model_id=_MODEL,
            output_format=f"pcm_{tts.sample_rate}",
            voice_settings=SDKVoiceSettings(
                stability=tts._vs.stability,
                similarity_boost=tts._vs.similarity_boost,
            ),
        ):
            if isinstance(chunk, bytes) and chunk:
                if first_chunk:
                    logger.debug("v3 first chunk received")
                    first_chunk = False
                output_emitter.push(chunk)

        output_emitter.flush()


# ── Builder ───────────────────────────────────────────────────────────

def make_eleven_v3_from_env(*, voice_id: str) -> ElevenLabsV3TTS:
    api_key = os.environ.get("ELEVENLABS_API_KEY") or os.environ.get("ELEVEN_API_KEY")
    if not api_key:
        raise V3AuthError("ELEVENLABS_API_KEY must be set for v3 TTS")
    return ElevenLabsV3TTS(voice_id=voice_id, api_key=api_key)
