"""Voice-call orchestrator: ties the engine adapter, STT, and TTS together.

Day 4 successor to parrot.py's `_speak(text)` middle. Flow per call:

    1. Runner constructed with (personality, tts, audio_source).
    2. On `open()`, synthesize Sally's greeting through the assigned
       personality's TTS and publish to the room.
    3. On each ASR final -> on_user_turn(text):
         - acquire turn_lock (drops concurrent finals — see below).
         - run engine_adapter.turn(text) -> response_text, ended.
         - lexicon-preprocess the response.
         - synthesize + publish through TTS.
         - sleep post_response_pause_multiplier * BASE_PAUSE.
         - release turn_lock.
    4. On session_ended returning True, the runner signals the
       dispatcher to tear down the room.

Turn-taking (Day 4 minimum):
    A single `asyncio.Lock` serializes turn processing. If the user
    keeps talking while Sally is still responding, those ASR finals
    are DROPPED at the gate. This avoids (a) stacking multiple engine
    calls in flight, (b) overlapping TTS audio on the same AudioSource,
    (c) out-of-order history interleaving. It's crude — barge-in /
    proper interruption is a Day 5+ concern (CLAUDE.md §B5). For Day 4
    smoke, dropping is safer than queueing.

Pacing (Day 4 minimum):
    `post_response_pause_multiplier` is honored as a sleep AFTER TTS
    finishes, before re-enabling turn processing. `speaking_rate` and
    `backchannel_density` are NOT honored today — speed control is
    blocked by the Cartesia plugin bug (memory note), backchannel is
    Day 5 scope.

Predecessors in this file:
    Day 2A left a docstring-only stub describing the eventual streaming
    Layer 3 + barge-in-aware design. That design is still the destination
    for Day 5+; today's implementation is the minimal viable turn loop
    that lets Nik hear Sally speak through the three locked voices.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

from livekit import rtc
from livekit.agents import tts as lk_tts

from backend.voice_agent.engine_adapter import SallyEngineAdapter
from backend.voice_agent.personalities import PERSONALITIES
from backend.voice_agent.pronunciation import preprocess

logger = logging.getLogger("sally-voice-runner")

# Base post-response pause in seconds. The personality's
# `post_response_pause_multiplier` scales this: sally_direct (0.85)
# gets ~0.26s; sally_warm (1.2) gets ~0.36s. Low absolute number —
# we're padding between Sally finishing and reopening the ASR gate,
# not the ASR VAD (Deepgram's endpointing_ms=25 handles that). Too
# long and the user feels Sally is unresponsive; too short and
# trailing TTS audio can bleed into the next user utterance's
# transcription.
_BASE_POST_RESPONSE_PAUSE_S = 0.3

# Fallback phrase on engine failure. Kept short, emotionally neutral,
# doesn't commit Sally to an action — just buys time and keeps the
# call alive. Lexicon preprocess runs on it too.
_ENGINE_FALLBACK = "Sorry, one moment."


class SallyVoiceRunner:
    """One runner per voice call. Owns turn serialization + TTS pacing.

    The runner does NOT own the STT stream or the audio I/O tracks —
    those live in `sally.py` and are passed in. This keeps the runner
    testable without a full LiveKit room, and keeps `sally.py` focused
    on dispatch / track wiring.
    """

    def __init__(
        self,
        *,
        personality: str,
        tts: lk_tts.TTS,
        audio_source: rtc.AudioSource,
        on_session_end: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        if personality not in PERSONALITIES:
            raise ValueError(f"Unknown personality {personality!r}")
        self._personality = personality
        self._tts_provider = PERSONALITIES[personality]["tts_provider"]
        self._pause_s = (
            _BASE_POST_RESPONSE_PAUSE_S
            * float(PERSONALITIES[personality]["post_response_pause_multiplier"])
        )
        self._tts = tts
        self._audio_source = audio_source
        self._adapter = SallyEngineAdapter(personality)
        self._turn_lock = asyncio.Lock()
        self._on_session_end = on_session_end

    @property
    def personality(self) -> str:
        return self._personality

    @property
    def adapter(self) -> SallyEngineAdapter:
        return self._adapter

    async def open(self) -> None:
        """Speak the opener under the turn lock.

        Call once, after the room is connected and the agent's audio
        track is published. Locking here matters: the STT task may
        already be running and an ASR final could arrive mid-greeting,
        triggering a concurrent _speak on the same AudioSource — same
        race that caused Day 3's glitchy echo before dedupe. The lock
        serializes the opener against any incoming user turn.
        """
        async with self._turn_lock:
            greeting = self._adapter.opener()
            logger.info(
                "Opening with greeting",
                extra={"personality": self._personality, "greeting": greeting[:60]},
            )
            await self._speak(greeting)

    async def on_user_turn(self, transcript: str) -> None:
        """Drive one engine turn end-to-end. Safe to call from an STT
        final handler; if a turn is already in flight, this transcript
        is dropped with a log line (see module docstring on turn-taking).
        """
        if not transcript.strip():
            return
        if self._adapter.ended:
            return
        if self._turn_lock.locked():
            logger.info(
                "Dropping transcript (turn in progress)",
                extra={"transcript": transcript[:80]},
            )
            return

        async with self._turn_lock:
            try:
                t0 = time.monotonic()
                response_text, ended = await self._adapter.turn(transcript)
                engine_ms = (time.monotonic() - t0) * 1000
                logger.info(
                    "Engine turn complete",
                    extra={
                        "engine_ms": round(engine_ms),
                        "response_len": len(response_text),
                        "ended": ended,
                    },
                )
            except Exception:
                logger.exception("Engine turn failed — using fallback phrase")
                await self._speak(_ENGINE_FALLBACK)
                return

            if response_text:
                await self._speak(response_text)
            # Pacing: post-response pause scales with personality.
            # sally_direct is terser + faster to re-engage; sally_warm
            # lingers. Do this BEFORE checking `ended` so a farewell
            # line plus pause feels natural before teardown.
            await asyncio.sleep(self._pause_s)

            if ended and self._on_session_end is not None:
                logger.info("Session ended by engine — signaling teardown")
                await self._on_session_end()

    async def _speak(self, text: str) -> None:
        """Synthesize through the personality's TTS and publish.

        Swallows TTS failures. Same rationale as parrot._speak: a
        single bad synthesis must not tear down the call.
        """
        processed = preprocess(text, self._tts_provider)
        t0 = time.monotonic()
        first_frame = True
        try:
            async for chunk in self._tts.synthesize(processed):
                if first_frame:
                    dt_ms = (time.monotonic() - t0) * 1000
                    logger.info(
                        "TTS first-frame",
                        extra={"first_frame_ms": round(dt_ms), "text": processed[:80]},
                    )
                    first_frame = False
                await self._audio_source.capture_frame(chunk.frame)
        except Exception as exc:  # noqa: BLE001
            logger.warning("TTS failed for %r: %s", processed[:60], exc)
