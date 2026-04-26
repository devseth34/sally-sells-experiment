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
from dataclasses import dataclass
from typing import Awaitable, Callable, Literal, Optional

from livekit import rtc
from livekit.agents import tts as lk_tts

from backend.voice_agent import expression, tag_director
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
from backend.voice_agent.live_reasoning import LiveReasoningPublisher
from backend.voice_agent.persistence import SessionRecorder
from backend.voice_agent.personalities import PERSONALITIES
from backend.voice_agent.pronunciation import preprocess

logger = logging.getLogger("sally-voice-runner")


@dataclass
class DirectorMetadata:
    """Per-turn record of whether the Haiku tag director ran and outcome.

    Threaded through `_apply_expression` → `_emit_metrics` → JSONL so
    we can compute director used-rate, fallback rate, and latency
    distribution per arm in cds_rollup.
    """
    used: bool                         # True iff director call succeeded
    latency_ms: float                  # 0.0 if director not attempted
    fallback_reason: Optional[str]     # populated when director failed

    @classmethod
    def empty(cls) -> "DirectorMetadata":
        """For arms that never invoke the director (existing 3 arms)."""
        return cls(used=False, latency_ms=0.0, fallback_reason=None)

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
        tts_emotive: Optional[lk_tts.TTS] = None,  # kept for API compat, unused
        audio_source: rtc.AudioSource,
        on_session_end: Callable[[], Awaitable[None]] | None = None,
        metrics_sink: MetricsSink | None = None,
        call_id: str = "",
        recorder: Optional[SessionRecorder] = None,
        publisher: Optional[LiveReasoningPublisher] = None,
    ) -> None:
        if personality not in PERSONALITIES:
            raise ValueError(f"Unknown personality {personality!r}")
        self._personality = personality
        self._tts_provider = PERSONALITIES[personality]["tts_provider"]
        self._pause_s = (
            _BASE_POST_RESPONSE_PAUSE_S
            * float(PERSONALITIES[personality]["post_response_pause_multiplier"])
        )
        # _tts_fast: livekit Flash plugin — used for greeting, backchannels,
        # and non-decorated turns. Low latency (~75ms first-frame).
        # _tts_emotive: our direct HTTP adapter (elevenlabs_v3_tts.py) using
        # eleven_flash_v2_5. The livekit plugin's streaming path does NOT
        # render audio tags like [chuckles]/[sighs] — it reads them as
        # literal text. The direct HTTP REST endpoint does render them.
        self._tts_fast = tts
        self._tts_emotive = tts_emotive  # None for non-emotive personalities
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
        self._recorder: Optional[SessionRecorder] = recorder
        self._publisher: Optional[LiveReasoningPublisher] = publisher
        self._turn_index = 0
        # Backchannel state — lives across the whole call, not per turn.
        # `_recently_used_backchannels` caps at the last 2 entries so
        # pick_backchannel can avoid immediate repeats. `_last_backchannel_at`
        # enforces MIN_INTERVAL_SEC gating across turns.
        self._recently_used_backchannels: list[str] = []
        self._last_backchannel_at: float = 0.0
        # Tag director scratch — written by `_try_tag_director` on
        # success, read by `_apply_expression`. Per-turn; safe because
        # turn_lock serializes. Avoids returning a 6-tuple from the
        # helper to the caller.
        self._last_director_text: str = ""
        self._last_director_tags: list[str] = []

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
                # Optional progress hint to the live UI. Best-effort —
                # if it fails to schedule, the live panel just doesn't
                # show a "thinking…" indicator for this turn.
                if self._publisher is not None:
                    try:
                        asyncio.create_task(
                            self._publisher.publish_progress("engine", "Sally is thinking…"),
                            name="publish-progress-engine",
                        )
                    except Exception:  # noqa: BLE001
                        pass
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
                await self._speak(_ENGINE_FALLBACK, tier="fast")
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

            # Expression layer — runs only for sally_emotive. For all
            # other arms, decorated_text == response_text and tier="fast"
            # so the code path below is identical to pre-Phase-F behavior.
            # Now async because the Haiku tag director (sally_emotive only)
            # makes a network call. We're already inside the turn_lock
            # critical section so awaiting here is safe.
            decorated_text, tags_used, tts_tier, director_meta = (
                await self._apply_expression(response_text)
            )

            if decorated_text:
                if self._publisher is not None:
                    try:
                        asyncio.create_task(
                            self._publisher.publish_progress("tts", "Sally is speaking…"),
                            name="publish-progress-tts",
                        )
                    except Exception:  # noqa: BLE001
                        pass
                first_frame_ms, first_frame_t = await self._speak(
                    decorated_text, tier=tts_tier
                )
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
                sally_text=decorated_text,
                asr_ms=asr_ms,
                engine_ms=engine_ms,
                tts_first_frame_ms=first_frame_ms,
                utterance_duration_ms=utterance_duration_ms,
                engine_dispatch_ms=engine_dispatch_ms,
                user_latency_ms=user_latency_ms,
                ended=ended,
                phase_stats=self._adapter.last_turn_stats,
                tts_tier=tts_tier,
                audio_tags_used=tags_used,
                user_emotion=self._adapter.last_user_emotion,
                expression_decorated=(self._personality == "sally_emotive"),
                tag_director_used=director_meta.used,
                # Latency only meaningful when director was attempted (used or
                # fell back). 0.0 from DirectorMetadata.empty() means not attempted;
                # surface as None in that case so JSONL stays clean.
                tag_director_latency_ms=(
                    director_meta.latency_ms
                    if (director_meta.used or director_meta.fallback_reason is not None)
                    else None
                ),
                tag_director_fallback=director_meta.fallback_reason,
            )

            if ended and self._on_session_end is not None:
                logger.info("Session ended by engine — signaling teardown")
                await self._on_session_end()

    def _recent_history(self, n: int = 2) -> list[dict]:
        """Last n full turns from the engine adapter as alternating
        user/assistant dicts. Used by the tag director for context.

        Returns at most 2*n dicts (one user + one assistant per turn).
        Tolerates a missing or empty history attribute — director
        prompt has a fallback for "(no prior turns)".
        """
        history = getattr(self._adapter, "_history", []) or []
        if not history:
            return []
        # Each "turn" is two history entries (user + assistant), so we
        # take the last 2*n entries to roughly cover n turns.
        return list(history[-(2 * n):])

    async def _apply_expression(
        self, response_text: str
    ) -> tuple[str, list, Literal["fast", "emotive"], DirectorMetadata]:
        """Decide tags + decoration. Returns (text, tags, tier, director_meta).

        Two gates:
          1. If the personality has no allowed_audio_tags (existing 3
             arms), short-circuit immediately with the raw response.
             Zero director cost, zero rules-path cost.
          2. If `tag_director: True`, try Haiku first. On any failure
             (timeout, parse, invalid tag, drift, missing API key),
             fall through to the rules-based expression.decorate().
        """
        cfg = PERSONALITIES.get(self._personality, {})
        allowed_tags = cfg.get("allowed_audio_tags") or []

        # Gate 1: existing 3 arms (empty whitelist) exit free.
        if not allowed_tags:
            return response_text, [], "fast", DirectorMetadata.empty()

        # Gate 2: try Haiku director if personality opts in.
        director_meta = DirectorMetadata.empty()
        if cfg.get("tag_director", False):
            director_meta = await self._try_tag_director(response_text, cfg, allowed_tags)
            if director_meta.used:
                # Director succeeded — use its output. The actual decorated
                # text + tags are stashed on director_meta via the helper.
                tier: Literal["fast", "emotive"] = (
                    "emotive" if self._last_director_tags else "fast"
                )
                logger.info(
                    "Tag director applied",
                    extra={
                        "tags": self._last_director_tags,
                        "tier": tier,
                        "latency_ms": round(director_meta.latency_ms),
                        "phase": self._adapter.current_phase,
                        "emotion": self._adapter.last_user_emotion,
                    },
                )
                return (
                    self._last_director_text,
                    self._last_director_tags,
                    tier,
                    director_meta,
                )
            # Director failed — log once, fall through to rules.
            logger.info(
                "Tag director fell back to rules: %s", director_meta.fallback_reason
            )

        # Rules-based fallback (also used by any future personality with
        # a whitelist but tag_director=False).
        try:
            decorated, tags, tier = expression.decorate(
                response_text,
                phase=self._adapter.current_phase,
                user_emotion=self._adapter.last_user_emotion,
                personality=self._personality,
                allowed_tags=allowed_tags,
                disfluency_density=float(cfg.get("disfluency_density", 0.0)),
            )
        except Exception:  # noqa: BLE001
            logger.exception("expression.decorate failed (non-fatal) — using raw response")
            return response_text, [], "fast", director_meta

        logger.info(
            "Expression layer applied (rules path)",
            extra={
                "tags": tags,
                "tier": tier,
                "phase": self._adapter.current_phase,
                "emotion": self._adapter.last_user_emotion,
            },
        )
        return decorated, tags, tier, director_meta

    async def _try_tag_director(
        self,
        response_text: str,
        cfg: dict,
        allowed_tags: list[str],
    ) -> DirectorMetadata:
        """Call the Haiku director. Returns DirectorMetadata describing
        the outcome; if used=True, also stashes the decorated text and
        tag list on `_last_director_text` / `_last_director_tags` for
        the caller to read (avoids returning a 6-tuple from the
        outer method)."""
        # Defensive: any unexpected exception (anthropic SDK bugs, etc.)
        # falls through to rules. The director itself returns
        # success=False with a reason for normal failure modes.
        try:
            result = await tag_director.direct_tags(
                response_text,
                phase=self._adapter.current_phase,
                user_emotion=self._adapter.last_user_emotion,
                history=self._recent_history(n=2),
                allowed_tags=allowed_tags,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("tag_director raised unexpectedly — falling back")
            return DirectorMetadata(
                used=False, latency_ms=0.0, fallback_reason=f"unexpected: {type(exc).__name__}"
            )

        if result.success:
            self._last_director_text = result.decorated_text
            self._last_director_tags = list(result.tags_used)
            return DirectorMetadata(
                used=True,
                latency_ms=result.latency_ms,
                fallback_reason=None,
            )
        return DirectorMetadata(
            used=False,
            latency_ms=result.latency_ms,
            fallback_reason=result.fallback_reason,
        )

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
        tts_tier: str = "fast",
        audio_tags_used: Optional[list] = None,
        user_emotion: Optional[str] = None,
        expression_decorated: bool = False,
        tag_director_used: bool = False,
        tag_director_latency_ms: Optional[float] = None,
        tag_director_fallback: Optional[str] = None,
    ) -> None:
        """One JSONL row per completed turn (or engine-failure fallback).

        Safe to call with a None sink — callers that don't wire metrics
        (tests, parrot.py) get a no-op path. `consume_turn_l1_model` is
        called on every turn so captured model state doesn't leak across
        turns even when the sink is absent.
        """
        l1_model = consume_turn_l1_model()
        self._turn_index += 1
        metrics = TurnMetrics(
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
            tts_tier=tts_tier,
            audio_tags_used=audio_tags_used,
            user_emotion=user_emotion,
            expression_decorated=expression_decorated,
            tag_director_used=tag_director_used,
            tag_director_latency_ms=tag_director_latency_ms,
            tag_director_fallback=tag_director_fallback,
        )
        if self._metrics_sink is not None:
            try:
                self._metrics_sink.emit(metrics)
            except Exception:  # noqa: BLE001
                logger.exception("Metrics emit failed (non-fatal)")
        if self._recorder is not None:
            try:
                from dataclasses import asdict
                self._recorder.record_turn(asdict(metrics))
            except Exception:  # noqa: BLE001
                logger.exception("Recorder record_turn failed (non-fatal)")
        if self._publisher is not None:
            # Fire-and-forget — never await. Publisher failures must not
            # block the runner; the DB write above is the safety net.
            try:
                from dataclasses import asdict
                asyncio.create_task(
                    self._publisher.publish_turn(asdict(metrics)),
                    name=f"publish-turn-{self._turn_index}",
                )
            except Exception:  # noqa: BLE001
                logger.debug("Failed to schedule publisher.publish_turn (non-fatal)")

    async def _speak(
        self,
        text: str,
        *,
        tier: Literal["fast", "emotive"] = "fast",
    ) -> tuple[float | None, float | None]:
        """Synthesize and publish to the AudioSource.

        tier="emotive": uses the direct HTTP adapter (ElevenLabsV3TTS with
        eleven_flash_v2_5) which renders audio tags as actual sounds.
        tier="fast": uses the livekit Flash plugin — lower latency, but
        reads [chuckles] etc. as literal text (different streaming path).
        Backchannels and non-decorated turns always use tier="fast".

        Falls back to fast tier if the emotive adapter is None or fails.
        Returns (first_frame_ms, first_frame_t). Both None on failure.
        Acquires audio_lock so backchannels never overlap with responses.
        """
        processed = preprocess(text, self._tts_provider)
        first_frame_ms: float | None = None
        first_frame_t: float | None = None

        async with self._audio_lock:
            t0 = time.monotonic()

            if tier == "emotive" and self._tts_emotive is not None:
                try:
                    async for chunk in self._tts_emotive.synthesize(processed):
                        if first_frame_ms is None:
                            first_frame_t = time.monotonic()
                            first_frame_ms = (first_frame_t - t0) * 1000
                            logger.info(
                                "TTS first-frame",
                                extra={"first_frame_ms": round(first_frame_ms), "tier": "emotive", "text": processed[:80]},
                            )
                        await self._audio_source.capture_frame(chunk.frame)
                    return first_frame_ms, first_frame_t
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Emotive TTS failed, falling back to fast: %s", exc)
                    t0 = time.monotonic()

            # Fast tier (livekit plugin) — greeting, backchannels, fallback.
            try:
                async for chunk in self._tts_fast.synthesize(processed):
                    if first_frame_ms is None:
                        first_frame_t = time.monotonic()
                        first_frame_ms = (first_frame_t - t0) * 1000
                        logger.info(
                            "TTS first-frame",
                            extra={"first_frame_ms": round(first_frame_ms), "tier": "fast", "text": processed[:80]},
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
            # Backchannels ALWAYS use the fast tier. Their job is masking
            # latency; using v3 here would add latency instead of hiding it.
            await self._speak(phrase, tier="fast")
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
