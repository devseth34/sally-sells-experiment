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

from backend.voice_agent.backchannel import (
    pick_backchannel,
    should_fire_mid_engine,
)
from backend.voice_agent.engine_adapter import SallyEngineAdapter
from backend.voice_agent.metrics import (
    MetricsSink,
    TurnMetrics,
    consume_turn_l1_model,
)
from backend.voice_agent.personalities import PERSONALITIES
from backend.voice_agent.pronunciation import preprocess

logger = logging.getLogger("sally-voice-runner")


def _safe_ms_between(earlier: float | None, later: float | None) -> float | None:
    """Clamp-to-zero ms delta between two monotonic() timestamps.

    Returns None if either endpoint is missing. Clamps negative deltas
    to 0 so a rarely-seen "later event recorded before earlier event"
    (race between event channels) doesn't produce nonsense negatives
    in the metrics sink.
    """
    if earlier is None or later is None:
        return None
    return max(0.0, (later - earlier) * 1000)

# Delay after engine.turn() starts before the backchannel fires. If the
# engine returns before this elapses (fast path / cached responses), the
# task is cancelled and nothing plays. 500ms chosen to overlap with
# typical engine latency (~3.5s on 2.5-flash-lite) while skipping the
# rare sub-500ms returns.
_BACKCHANNEL_DELAY_S = 0.5

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
        metrics_sink: MetricsSink | None = None,
        call_id: str = "",
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
        # Serializes any audio emission into the shared AudioSource.
        # Backchannel fillers and Sally's real TTS response compete for
        # this lock — the filler takes it first (scheduled at the start
        # of on_user_turn) and releases when its synthesis is done;
        # Sally's _speak then acquires it after engine.turn() returns.
        # Without this, a slow engine could have the filler still
        # playing when Sally starts, producing audible overlap.
        self._audio_lock = asyncio.Lock()
        self._on_session_end = on_session_end
        self._metrics_sink = metrics_sink
        self._call_id = call_id
        self._turn_index = 0
        # Backchannel state — lives across the whole call, not per turn.
        # `_recently_used_backchannels` caps at the last 2 entries so
        # pick_backchannel can avoid immediate repeats. `_last_backchannel_at`
        # enforces MIN_INTERVAL_SEC gating across turns.
        self._recently_used_backchannels: list[str] = []
        self._last_backchannel_at: float = 0.0

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

    async def on_user_turn(
        self,
        transcript: str,
        *,
        asr_ms: float | None = None,
        speech_end_t: float | None = None,
        utterance_duration_ms: float | None = None,
    ) -> None:
        """Drive one engine turn end-to-end. Safe to call from an STT
        final handler; if a turn is already in flight, this transcript
        is dropped with a log line (see module docstring on turn-taking).

        Timing params (all monotonic-based, all optional):
          `asr_ms`: transcript-available tail after END_OF_SPEECH, i.e.
              how long the user waited post-speech-end for the
              transcript. See sally.py _read_transcripts for derivation.
              Previously mismeasured as inter-utterance gap; fixed
              Day 6 2026-04-24 alongside the richer event logging.
          `speech_end_t`: monotonic() timestamp of END_OF_SPEECH for
              this utterance. Used to compute engine_dispatch_ms and
              user_latency_ms (the real user-perceived metrics).
          `utterance_duration_ms`: SPEECH_STARTED → END_OF_SPEECH delta.
              Not latency — useful for correlating asr_ms with how
              long the user actually spoke.
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
            response_text = ""
            ended = False
            first_frame_ms: float | None = None
            first_frame_t: float | None = None
            engine_ms: float | None = None
            engine_start_t: float | None = None
            # Start the backchannel task concurrently with the engine
            # call. It sleeps _BACKCHANNEL_DELAY_S before firing, so a
            # fast engine return cancels it before any audio goes out.
            bc_task = asyncio.create_task(
                self._fire_backchannel_during_engine(),
                name=f"backchannel-turn-{self._turn_index + 1}",
            )
            try:
                engine_start_t = time.monotonic()
                response_text, ended = await self._adapter.turn(transcript)
                engine_ms = (time.monotonic() - engine_start_t) * 1000
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
                await self._cancel_backchannel(bc_task)
                await self._speak(_ENGINE_FALLBACK)
                self._emit_metrics(
                    user_text=transcript,
                    sally_text=_ENGINE_FALLBACK,
                    asr_ms=asr_ms,
                    engine_ms=None,
                    tts_first_frame_ms=None,
                    utterance_duration_ms=utterance_duration_ms,
                    engine_dispatch_ms=_safe_ms_between(speech_end_t, engine_start_t),
                    user_latency_ms=None,
                    ended=False,
                    phase_stats=self._adapter.last_turn_stats,
                )
                return
            finally:
                # Whether engine succeeded or raised, the backchannel task
                # must be cancelled/awaited so it doesn't leak into the
                # next turn's audio window.
                await self._cancel_backchannel(bc_task)

            if response_text:
                first_frame_ms, first_frame_t = await self._speak(response_text)
            # Pacing: post-response pause scales with personality.
            # sally_direct is terser + faster to re-engage; sally_warm
            # lingers. Do this BEFORE checking `ended` so a farewell
            # line plus pause feels natural before teardown.
            await asyncio.sleep(self._pause_s)

            # user_latency_ms is THE user-perceived number: from the
            # moment the user stopped speaking to the moment Sally's
            # first audio frame landed. Everything else (asr, engine,
            # tts) decomposes this total.
            user_latency_ms = _safe_ms_between(speech_end_t, first_frame_t)
            engine_dispatch_ms = _safe_ms_between(speech_end_t, engine_start_t)

            self._emit_metrics(
                user_text=transcript,
                sally_text=response_text,
                asr_ms=asr_ms,
                engine_ms=engine_ms,
                tts_first_frame_ms=first_frame_ms,
                utterance_duration_ms=utterance_duration_ms,
                engine_dispatch_ms=engine_dispatch_ms,
                user_latency_ms=user_latency_ms,
                ended=ended,
                phase_stats=self._adapter.last_turn_stats,
            )

            if ended and self._on_session_end is not None:
                logger.info("Session ended by engine — signaling teardown")
                await self._on_session_end()

    def _emit_metrics(
        self,
        *,
        user_text: str,
        sally_text: str,
        asr_ms: float | None,
        engine_ms: float | None,
        tts_first_frame_ms: float | None,
        utterance_duration_ms: float | None,
        engine_dispatch_ms: float | None,
        user_latency_ms: float | None,
        ended: bool,
        phase_stats: dict,
    ) -> None:
        """One JSONL row per completed turn (or engine-failure fallback).

        Safe to call with a None sink — callers that don't wire metrics
        (tests, parrot.py) get a no-op path. `consume_turn_l1_model` is
        called on every turn so captured model state doesn't leak across
        turns even when the sink is absent.
        """
        l1_model = consume_turn_l1_model()
        if self._metrics_sink is None:
            return
        self._turn_index += 1
        try:
            self._metrics_sink.emit(
                TurnMetrics(
                    call_id=self._call_id,
                    turn_index=self._turn_index,
                    personality=self._personality,
                    arm=self._adapter.arm_key,
                    phase=str(phase_stats.get("phase", "")),
                    phase_changed=bool(phase_stats.get("phase_changed", False)),
                    user_text=user_text,
                    sally_text=sally_text,
                    asr_ms=asr_ms,
                    engine_ms=engine_ms,
                    l1_model=l1_model,
                    tts_first_frame_ms=tts_first_frame_ms,
                    utterance_duration_ms=utterance_duration_ms,
                    engine_dispatch_ms=engine_dispatch_ms,
                    user_latency_ms=user_latency_ms,
                    ended=ended,
                )
            )
        except Exception:  # noqa: BLE001
            logger.exception("Metrics emit failed (non-fatal)")

    async def _speak(self, text: str) -> tuple[float | None, float | None]:
        """Synthesize through the personality's TTS and publish.

        Returns (first_frame_ms, first_frame_t) where:
          first_frame_ms: TTS first-frame latency in ms, measured from
              the _speak start (≈ engine-done). Kept for backward-compat
              with the `tts_first_frame_ms` metric and log line.
          first_frame_t: absolute monotonic() timestamp when the first
              audio frame landed. Lets the caller compute
              user_latency_ms = first_frame_t - speech_end_t cleanly
              without re-deriving from deltas.

        Both are None if the TTS failed before emitting a frame.
        Swallows TTS failures — same rationale as parrot._speak: a
        single bad synthesis must not tear down the call.

        Acquires `_audio_lock` for the entire synthesis so concurrent
        backchannel emission never overlaps with Sally's real response
        on the shared AudioSource.
        """
        processed = preprocess(text, self._tts_provider)
        first_frame_ms: float | None = None
        first_frame_t: float | None = None
        async with self._audio_lock:
            t0 = time.monotonic()
            try:
                async for chunk in self._tts.synthesize(processed):
                    if first_frame_ms is None:
                        first_frame_t = time.monotonic()
                        first_frame_ms = (first_frame_t - t0) * 1000
                        logger.info(
                            "TTS first-frame",
                            extra={"first_frame_ms": round(first_frame_ms), "text": processed[:80]},
                        )
                    await self._audio_source.capture_frame(chunk.frame)
            except Exception as exc:  # noqa: BLE001
                logger.warning("TTS failed for %r: %s", processed[:60], exc)
        return first_frame_ms, first_frame_t

    async def _fire_backchannel_during_engine(self) -> None:
        """Sleep _BACKCHANNEL_DELAY_S then, if still gated-in, emit one
        filler phrase through the same TTS/AudioSource as Sally.

        This coroutine is scheduled as a task at the start of
        on_user_turn and cancelled after engine.turn() returns. Two
        cancellation paths:
            1. Engine returned before the sleep elapsed — task cancelled
               mid-sleep, nothing synthesized, no audio played.
            2. Engine returned mid-synthesis — task cancelled, but the
               audio_lock ensures Sally waits for the backchannel to
               finish before starting her own TTS.

        CancelledError must be re-raised so the asyncio.Task ends in a
        cancelled state and the runner's `_cancel_backchannel` can
        await it cleanly.
        """
        try:
            await asyncio.sleep(_BACKCHANNEL_DELAY_S)
        except asyncio.CancelledError:
            raise

        current_phase = self._adapter.current_phase
        now = time.monotonic()
        seconds_since_last = (
            now - self._last_backchannel_at if self._last_backchannel_at > 0 else float("inf")
        )
        if not should_fire_mid_engine(
            personality=self._personality,
            phase=current_phase,
            seconds_since_last=seconds_since_last,
        ):
            return

        phrase = pick_backchannel(
            self._personality,
            self._recently_used_backchannels,
        )
        logger.info(
            "Backchannel firing",
            extra={
                "phrase": phrase,
                "phase": current_phase,
                "personality": self._personality,
            },
        )
        # _speak acquires audio_lock — if Sally's real response raced
        # us to it, _speak would have to wait for us; but _speak is
        # awaited AFTER engine.turn(), and cancel-on-completion means
        # we're already cancelled by that point unless we started
        # emitting before cancellation.
        try:
            await self._speak(phrase)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Backchannel synthesis failed (non-fatal)")
            return
        self._last_backchannel_at = time.monotonic()
        self._recently_used_backchannels.append(phrase)
        self._recently_used_backchannels = self._recently_used_backchannels[-2:]

    async def _cancel_backchannel(self, task: asyncio.Task[None]) -> None:
        """Cancel + await a backchannel task without raising.

        If the task already completed (either fired a phrase cleanly
        or gated out), cancel is a no-op. If it's still sleeping or
        mid-synthesis, cancel interrupts it. Awaiting surfaces any
        exceptions except CancelledError, which we swallow.
        """
        if task.done():
            return
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
