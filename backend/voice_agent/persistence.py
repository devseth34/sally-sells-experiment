"""Voice session persistence.

During a call, accumulates per-turn metrics in memory.
On session end (participant disconnect or engine-driven end), ships the full
session to the voice API (voice_main.py) via HTTP POST.

The existing JSONL sink in MetricsSink is preserved — this is additive.
JSONL remains the local-dev fast path; the DB is the production source of truth.

Usage:
    recorder = SessionRecorder(call_id=..., arm=..., personality=..., forced=False)
    recorder.record_turn(turn_metrics_dict)
    ...
    await recorder.flush(session_ended=True)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger("sally.persistence")

# Read env at flush time, not import time — Fly.io secret rotation should
# take effect on next call, not next deploy. Also avoids a class of test
# pollution bugs where one test's env state leaks into another.
_PERSIST_TIMEOUT_S = 10.0

_PHASE_ORDER = [
    "CONNECTION",
    "SITUATION",
    "PROBLEM_AWARENESS",
    "SOLUTION_AWARENESS",
    "CONSEQUENCE",
    "OWNERSHIP",
    "COMMITMENT",
    "TERMINATED",
]


def _phase_rank(phase: str) -> int:
    try:
        return _PHASE_ORDER.index(phase)
    except ValueError:
        return -1


@dataclass
class _SessionAccumulator:
    call_id: str
    arm: str
    personality: str
    forced: bool
    started_at: float
    turns: list[dict[str, Any]] = field(default_factory=list)
    ended_at: Optional[float] = None
    deepest_phase: str = "CONNECTION"
    ended_at_phase: Optional[str] = None
    session_ended: bool = False


class SessionRecorder:
    """One instance per voice call (created in sally.py entrypoint).

    Thread-safe enough for asyncio (single-threaded event loop). If the
    voice agent ever moves to true threads, add a lock around `_acc.turns`.
    """

    def __init__(
        self,
        *,
        call_id: str,
        arm: str,
        personality: str,
        forced: bool,
    ) -> None:
        self._acc = _SessionAccumulator(
            call_id=call_id,
            arm=arm,
            personality=personality,
            forced=forced,
            started_at=time.time(),
        )
        self._flushed = False

    def record_turn(self, turn_dict: dict[str, Any]) -> None:
        """Called from sally_voice_runner._emit_metrics after each completed turn."""
        self._acc.turns.append(turn_dict)

        phase = turn_dict.get("phase") or ""
        if phase and _phase_rank(phase) > _phase_rank(self._acc.deepest_phase):
            self._acc.deepest_phase = phase
        if phase:
            self._acc.ended_at_phase = phase
        if turn_dict.get("ended"):
            self._acc.session_ended = True

    async def flush(self, *, session_ended: bool = False) -> None:
        """Ship the session to the voice API. Idempotent — safe to call twice.

        Falls back to disk if the HTTP call fails so no session is lost
        permanently due to transient network issues between Fly.io and Railway.
        """
        if self._flushed:
            return
        self._flushed = True
        self._acc.ended_at = time.time()
        if session_ended:
            self._acc.session_ended = True

        payload = {
            "call_id": self._acc.call_id,
            "arm": self._acc.arm,
            "personality": self._acc.personality,
            "forced": self._acc.forced,
            "started_at": self._acc.started_at,
            "ended_at": self._acc.ended_at,
            "duration_s": self._acc.ended_at - self._acc.started_at,
            "deepest_phase": self._acc.deepest_phase,
            "ended_at_phase": self._acc.ended_at_phase,
            "session_ended": self._acc.session_ended,
            "n_turns": len(self._acc.turns),
            "turns": self._acc.turns,
        }

        url = os.environ.get("VOICE_PERSIST_URL")
        if not url:
            log.warning(
                "VOICE_PERSIST_URL not set — session %s not persisted to DB",
                self._acc.call_id,
            )
            return

        try:
            import aiohttp  # lazy import — not available in all environments

            async with aiohttp.ClientSession() as http:
                async with http.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=_PERSIST_TIMEOUT_S),
                    headers={
                        "X-Voice-Agent-Token": os.environ.get("VOICE_PERSIST_TOKEN", ""),
                        "Content-Type": "application/json",
                    },
                ) as resp:
                    if resp.status >= 400:
                        body = await resp.text()
                        log.error(
                            "Persist HTTP %d for %s: %s",
                            resp.status,
                            self._acc.call_id,
                            body[:300],
                        )
                        self._fallback_to_disk(payload)
                    else:
                        log.info(
                            "Persisted session %s (%d turns)",
                            self._acc.call_id,
                            len(self._acc.turns),
                        )
        except asyncio.TimeoutError:
            log.error("Persist timed out for %s — writing to disk", self._acc.call_id)
            self._fallback_to_disk(payload)
        except Exception as exc:  # noqa: BLE001
            log.error("Persist failed for %s: %s — writing to disk", self._acc.call_id, exc)
            self._fallback_to_disk(payload)

    def _fallback_to_disk(self, payload: dict[str, Any]) -> None:
        path = f"/tmp/sally_session_{self._acc.call_id}.json"
        try:
            with open(path, "w") as f:
                json.dump(payload, f)
            log.warning("Disk fallback written to %s", path)
        except OSError as e:
            log.error("Disk fallback also failed for %s: %s", self._acc.call_id, e)
