"""Per-turn metrics for voice calls — CDS-grade observability.

Emits one JSONL row per turn to a path sink (default `/tmp/sally_turns.jsonl`).
Captures enough to compute CDS offline: personality/arm (which Sally variant
answered), phase + phase_changed (progression), latency per observable stage
(asr_ms, engine_ms, tts_first_frame_ms), and which Gemini model Layer 1 actually
used on this turn (primary vs fallback).

Layer-level L1/L2/L3 breakdown is NOT emitted today — the frozen engine doesn't
expose per-layer timings, and adding timers there violates CLAUDE.md §2. Day 5+
can either backfill that by extending engine_adapter with layer-aware timing
probes, or accept `engine_ms` as the aggregate.

Why a module global for L1 model capture (not a ContextVar):
    `run_comprehension` logs "Layer 1 completed with model: X" but doesn't
    return the model name. A logging.Filter on `sally.comprehension` reads
    that log and stashes the model name; the voice-side turn metrics
    consume it at emit time. Non-invasive — no frozen-file changes.

    ContextVar was the first instinct but it's wrong here: the comprehension
    call runs via `asyncio.to_thread`, which COPIES the current context into
    the worker thread and discards the copy on return. So mutations inside
    the thread (the filter's `.set()`) never reach the main asyncio thread
    where `consume_turn_l1_model()` runs — metrics rows would all show
    `l1_model=null`. A plain module global survives because both threads
    share module state; the filter write in the executor thread is visible
    to the main-thread read once the executor returns. Safe without locking
    because (a) turn_lock in the runner serializes turns per runner, so
    there's at most one in-flight engine call per subprocess, and (b)
    attribute writes to a module-level Optional[str] are atomic under the
    Python GIL.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


_last_l1_model: Optional[str] = None

_L1_MODEL_RE = re.compile(r"Layer 1 completed with model:\s*(\S+)")


class _ComprehensionLogFilter(logging.Filter):
    """Captures the L1 model for the current turn.

    Returns True unconditionally — this is a tap, not a suppressor. The
    frozen comprehension logger keeps emitting its usual records; we
    just piggyback on the model-name announcement to populate a
    ContextVar the voice layer can read.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        global _last_l1_model
        msg = record.getMessage()
        m = _L1_MODEL_RE.search(msg)
        if m:
            _last_l1_model = m.group(1)
        return True


_installed = False


def install_comprehension_capture() -> None:
    """Attach the logging tap once per process.

    Idempotent — callable from every prewarm subprocess entrypoint
    without double-registering.
    """
    global _installed
    if _installed:
        return
    logging.getLogger("sally.comprehension").addFilter(_ComprehensionLogFilter())
    _installed = True


def consume_turn_l1_model() -> Optional[str]:
    """Read the L1 model for the just-completed turn, then clear.

    Call at the end of on_user_turn, after adapter.turn() has returned.
    Returns None if Layer 1 didn't log a model (e.g. JSON-parse fallback
    path took over) — in that case the metrics row records l1_model=null.
    """
    global _last_l1_model
    value = _last_l1_model
    _last_l1_model = None
    return value


@dataclass
class TurnMetrics:
    """One row per completed user turn.

    `call_id` is the LiveKit job.id, stable for a voice call. Rows from
    different calls (and different prewarm subprocesses writing to the
    same file) can be demuxed via this key.

    Latency decomposition (2026-04-24 rework):
      user_latency_ms = engine_dispatch_ms + engine_ms + tts_first_frame_ms
      where engine_dispatch_ms ≈ asr_ms (they differ by a few ms of
      coroutine scheduling overhead between "FINAL_TRANSCRIPT received"
      and "adapter.turn() starts"). `user_latency_ms` is the canonical
      user-perceived number; the components decompose it.

      `asr_ms` semantics were silently broken before 2026-04-24: it was
      measuring inter-utterance gap, not the actual post-speech tail.
      New code in sally.py computes it as `max(0, final_t -
      end_of_speech_t)` — see the _read_transcripts comment for why.

      Fields added 2026-04-24 default to None so older sink rows still
      load cleanly in cds_rollup.
    """

    call_id: str
    turn_index: int
    personality: str
    arm: str
    phase: str
    phase_changed: bool
    user_text: str
    sally_text: str
    asr_ms: Optional[float]
    engine_ms: Optional[float]
    l1_model: Optional[str]
    tts_first_frame_ms: Optional[float]
    ended: bool
    utterance_duration_ms: Optional[float] = None
    engine_dispatch_ms: Optional[float] = None
    user_latency_ms: Optional[float] = None
    timestamp: float = field(default_factory=time.time)


class MetricsSink:
    """Append-only JSONL writer.

    Each prewarm subprocess gets its own sink instance but they all
    write to the same path. Rows interleave across subprocesses — that's
    fine because each row is self-describing via `call_id`. One process
    opens and closes the file per emit (append mode); for Day 5 volumes
    (~40 sessions × ~15 turns = 600 rows total) this is cheaper than
    holding a file handle across jobs and managing its lifecycle.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def emit(self, metrics: TurnMetrics) -> None:
        line = json.dumps(asdict(metrics), default=str, ensure_ascii=False)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


DEFAULT_SINK_PATH = Path("/tmp/sally_turns.jsonl")


def default_sink() -> MetricsSink:
    return MetricsSink(DEFAULT_SINK_PATH)
