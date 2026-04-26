"""Thin async wrapper around the frozen SallyEngine.

`SallyEngine.process_turn()` in backend/app/agent.py is a synchronous
static method that takes conversation state as scalars + lists and
returns a dict of (response_text, new_phase, new_profile_json, ...,
session_ended, ...). The voice runner needs to:

    1. Maintain per-call state across turns (the phase, profile JSON,
       counters, history) because the engine is stateless.
    2. Not block the asyncio event loop with the engine's ~1.5-2.5s
       sync call (Gemini + Claude sequential).

This adapter owns the per-call state and runs the sync engine call in
the default asyncio thread executor. Callers get an `async turn()` that
feels native to the LiveKit worker coroutine world.

**Nothing in `backend/app/*` is modified.** This module only imports
from it. Frozen-file rule from CLAUDE.md §2 is respected.

Import bridge:
    `app.agent` uses `from app.schemas import NepqPhase` (absolute
    import, assumes `backend/` is on sys.path). Our voice_agent code
    uses `from backend.voice_agent.*` (assumes repo root is on path).
    Day 4 resolves this by prepending `backend/` to sys.path at
    module-load time, BEFORE importing app.*. See CLAUDE.md Day 4
    notes for why this bridge exists instead of modifying app/.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Bridge: make `app.*` importable alongside `backend.voice_agent.*`.
# `backend/` must precede repo-root on sys.path so "app" resolves first.
# Kept here (not in sally.py) so unit tests that import this adapter
# standalone also work.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# Load .env BEFORE importing app.* — `app.layers.comprehension` lazily
# calls `_ensure_gemini_configured()` which raises if GEMINI_API_KEY
# is missing. Livekit-agents' `start` mode prewarms multiple subprocess
# workers via multiprocessing spawn; each child re-imports this module
# but doesn't necessarily inherit os.environ from the parent's
# post-load state. Calling load_dotenv here (not just in sally.py's
# top level) guarantees engine imports see the keys regardless of how
# the subprocess was spawned.
_REPO_ROOT = _BACKEND_DIR.parent
# override=True because livekit-agents' prewarmed subprocesses inherit
# os.environ from the parent with some keys pre-set to empty strings
# (observed: GEMINI_API_KEY and ANTHROPIC_API_KEY both empty in child
# despite .env having them). Without override=True, load_dotenv leaves
# those empties alone and Layer 1's _ensure_gemini_configured() raises.
load_dotenv(_REPO_ROOT / ".env", override=True)

from app.agent import SallyEngine  # noqa: E402  -- bridge first
from app.schemas import NepqPhase  # noqa: E402

from backend.voice_agent.personalities import PERSONALITIES  # noqa: E402

logger = logging.getLogger("sally-engine-adapter")


class SallyEngineAdapter:
    """Per-call state holder + async-friendly wrapper around SallyEngine.

    One adapter instance per voice call. Owns:
        - conversation_history: list of {"role", "content"} dicts,
          appended to on every turn.
        - current_phase: advances through NepqPhase as the engine signals.
        - profile_json: prospect profile as JSON string, updated per turn.
        - turn counters and tracking state (five of them — see
          SallyEngine.process_turn() docstring for what each means).
        - conversation_start_time: frozen at construction, used by the
          engine for pacing / pressure heuristics.

    The adapter is NOT thread-safe. Voice calls are single-threaded on
    the asyncio loop per job, so this is fine. If we ever fan out
    per-call, give each fanout its own adapter.
    """

    def __init__(self, personality: str) -> None:
        if personality not in PERSONALITIES:
            raise ValueError(f"Unknown personality {personality!r}")
        self._personality = personality
        self._arm_key = PERSONALITIES[personality]["engine_arm"]

        # Fresh state per call. Matches the defaults the chat route uses
        # at session creation (main.py:820+).
        self._history: list[dict[str, str]] = []
        self._phase: NepqPhase = NepqPhase.CONNECTION
        self._profile_json: str = "{}"
        self._turn_number: int = 0
        self._retry_count: int = 0
        self._consecutive_no_new_info: int = 0
        self._turns_in_current_phase: int = 0
        self._deepest_emotional_depth: str = "surface"
        self._objection_diffusion_step: int = 0
        self._ownership_substep: int = 0
        self._start_time: float = time.time()
        # Memory context (cross-session memory) is DB-backed. Day 4 runs
        # without it; voice calls are treated as first-time for now.
        # Day 5 will populate this from app/memory.py once voice sessions
        # are persisted and the visitor can be identified.
        self._memory_context: str = ""

        self._ended: bool = False

        # Last-turn observability. Populated at the end of each `turn()`
        # call so the voice runner can emit metrics without having to
        # reach into the frozen engine's internals or re-derive state
        # from the adapter's private fields.
        self._last_turn_stats: dict = {}

        # Per-turn user emotion (for sally_emotive expression layer).
        # Extracted from the engine's thought_log_json — Layer 1's
        # ComprehensionOutput is serialized into that JSON string under
        # `comprehension.emotional_tone`. We parse it post-engine and
        # cache here so the runner can pass it to expression.decorate()
        # without doing its own JSON parsing.
        #
        # `emotional_tone` is the field from app/models.py:ComprehensionOutput
        # — a free-form string like "engaged, frustrated, defensive".
        # Substring matching in expression.py routes it to the right tag
        # pool (frustrated → [sighs]/[empathetic], etc.).
        self._last_user_emotion: Optional[str] = None

    @property
    def personality(self) -> str:
        return self._personality

    @property
    def arm_key(self) -> str:
        return self._arm_key

    @property
    def ended(self) -> bool:
        return self._ended

    @property
    def current_phase(self) -> str:
        """NEPQ phase the adapter is ABOUT to process the next turn in.

        Before any turn has run, returns "CONNECTION". After turn N
        completes, returns the phase that turn N advanced to (which is
        also the phase turn N+1 starts in). Needed by the backchannel
        trigger — CONNECTION is explicitly excluded from backchannel
        firing (Addendum §B6 rule: performative this early).
        """
        return self._phase.value

    @property
    def last_turn_stats(self) -> dict:
        return dict(self._last_turn_stats)

    @property
    def last_user_emotion(self) -> Optional[str]:
        """Emotional tone L1 detected on the most recent user turn.

        None if no turn has run yet, or if `thought_log_json` was
        missing/malformed/lacked an emotional_tone field. The expression
        layer treats None as "use phase pool only" — graceful degradation,
        not an error.
        """
        return self._last_user_emotion

    def opener(self) -> str:
        """Return the fixed greeting Sally uses to open a chat.

        The frozen engine exposes `SallyEngine.get_greeting()` (static,
        personality-agnostic) — see agent.py:72-78. Memory-personalized
        greetings (_generate_memory_greeting in main.py:839) require
        the DB-backed visitor memory layer, which Day 4 doesn't have,
        so we fall straight to the default. Openers do NOT count as a
        turn — the engine only processes turns when the user speaks.
        """
        return SallyEngine.get_greeting()

    async def turn(self, user_message: str) -> tuple[str, bool]:
        """Run one turn through the engine, return (response_text, ended).

        Threads all per-call state in and out of the sync engine call,
        run in the default asyncio executor so it doesn't block the
        event loop (engine is Gemini + Claude sequential, ~1.5-2.5s).
        """
        if self._ended:
            # Engine shouldn't be called after TERMINATED — guard in
            # case the runner misses a session_ended signal.
            logger.warning("turn() called after session ended, returning empty")
            return "", True

        self._turn_number += 1
        self._history.append({"role": "user", "content": user_message})

        t0 = time.monotonic()
        result = await asyncio.to_thread(
            SallyEngine.process_turn,
            current_phase=self._phase,
            user_message=user_message,
            conversation_history=list(self._history),
            profile_json=self._profile_json,
            retry_count=self._retry_count,
            turn_number=self._turn_number,
            conversation_start_time=self._start_time,
            consecutive_no_new_info=self._consecutive_no_new_info,
            turns_in_current_phase=self._turns_in_current_phase,
            deepest_emotional_depth=self._deepest_emotional_depth,
            objection_diffusion_step=self._objection_diffusion_step,
            ownership_substep=self._ownership_substep,
            memory_context=self._memory_context,
            arm_key=self._arm_key,
        )
        engine_ms = (time.monotonic() - t0) * 1000

        response_text = result["response_text"]
        ended = bool(result.get("session_ended", False))

        # Thread updated state back for the next turn.
        self._phase = NepqPhase(result["new_phase"])
        self._profile_json = result["new_profile_json"]
        self._retry_count = int(result.get("retry_count", self._retry_count))
        self._consecutive_no_new_info = int(
            result.get("consecutive_no_new_info", self._consecutive_no_new_info)
        )
        self._turns_in_current_phase = int(
            result.get("turns_in_current_phase", self._turns_in_current_phase)
        )
        self._deepest_emotional_depth = result.get(
            "deepest_emotional_depth", self._deepest_emotional_depth
        )
        self._objection_diffusion_step = int(
            result.get("objection_diffusion_step", self._objection_diffusion_step)
        )
        self._ownership_substep = int(
            result.get("ownership_substep", self._ownership_substep)
        )
        self._history.append({"role": "assistant", "content": response_text})
        self._ended = ended

        # Extract user emotional tone from the engine's thought log.
        # Layer 1 (comprehension) writes `emotional_tone` into the
        # ComprehensionOutput, which the engine serializes into the
        # `thought_log_json` field of its result dict. Parse defensively:
        # if the JSON is missing, malformed, or lacks the emotion key,
        # fall back to None and log a warning (don't raise — voice calls
        # must keep flowing even if a single turn's metadata is bad).
        self._last_user_emotion = _parse_user_emotion(result.get("thought_log_json"))

        self._last_turn_stats = {
            "turn": self._turn_number,
            "engine_ms": engine_ms,
            "phase": self._phase.value,
            "phase_changed": bool(result.get("phase_changed", False)),
            "ended": ended,
            "user_emotion": self._last_user_emotion,
        }

        logger.info(
            "Turn processed",
            extra={
                "turn": self._turn_number,
                "engine_ms": round(engine_ms),
                "phase": self._phase.value,
                "phase_changed": bool(result.get("phase_changed", False)),
                "ended": ended,
                "personality": self._personality,
                "arm_key": self._arm_key,
            },
        )
        return response_text, ended

    def snapshot_state(self) -> dict:
        """Small state dump for debug logging. Not for persistence.

        Day 5's DB session writes will need a much richer snapshot;
        keep this as a lightweight observability helper only.
        """
        return {
            "turn": self._turn_number,
            "phase": self._phase.value,
            "history_len": len(self._history),
            "ended": self._ended,
            "profile": json.loads(self._profile_json) if self._profile_json else {},
        }


def _parse_user_emotion(thought_log_json: object) -> Optional[str]:
    """Pull `emotional_tone` from the engine's thought_log JSON string.

    The engine puts ComprehensionOutput at `thought_log["comprehension"]`
    when Layer 1 ran successfully. Field of interest:
      thought_log_json -> "comprehension" -> "emotional_tone"
    On the fast-path or fallback path, comprehension may be absent or
    have a different shape; we tolerate every variation by defaulting
    to None and logging at debug level (not warning — these aren't
    error conditions).

    Returns the raw string from L1 (e.g. "engaged, frustrated,
    defensive"). The expression layer does its own substring matching
    against EMOTION_TAG_OVERRIDES keys; we don't normalize here.
    """
    if not thought_log_json or not isinstance(thought_log_json, str):
        return None
    try:
        parsed = json.loads(thought_log_json)
    except (ValueError, TypeError):
        logger.debug("thought_log_json failed to parse; emotion → None")
        return None
    if not isinstance(parsed, dict):
        return None

    # The exact path depends on the engine's serialization. Try
    # common shapes in order of likelihood, return the first hit.
    comp = parsed.get("comprehension")
    if isinstance(comp, dict):
        tone = comp.get("emotional_tone")
        if isinstance(tone, str) and tone.strip():
            return tone.strip()

    # Some engine paths flatten: emotional_tone at the top level.
    tone = parsed.get("emotional_tone")
    if isinstance(tone, str) and tone.strip():
        return tone.strip()

    return None
