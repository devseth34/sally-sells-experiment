"""Tests for voice-call per-turn metrics.

Run: source venv/bin/activate && python -m pytest backend/voice_agent/test_metrics.py -v
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import pytest

from backend.voice_agent.metrics import (
    MetricsSink,
    TurnMetrics,
    consume_turn_l1_model,
    install_comprehension_capture,
)


@pytest.fixture(autouse=True)
def _enable_comprehension_info_logs():
    """In production the livekit-agents runtime configures root at INFO
    so sally.comprehension's completion log reaches the filter. Pytest
    starts with root at WARNING — INFO calls get dropped before any
    filter runs. Lift the logger level for the duration of each test."""
    lg = logging.getLogger("sally.comprehension")
    prev = lg.level
    lg.setLevel(logging.INFO)
    try:
        yield
    finally:
        lg.setLevel(prev)


def test_comprehension_capture_reads_model_from_log_message() -> None:
    """The tap installs a logging filter that stashes the model name
    from `sally.comprehension`'s completion log into a ContextVar.
    Simulate what Layer 1 actually logs and verify round-trip."""
    install_comprehension_capture()
    consume_turn_l1_model()  # clear anything stale

    logging.getLogger("sally.comprehension").info(
        "Layer 1 completed with model: gemini-2.5-flash-lite"
    )

    assert consume_turn_l1_model() == "gemini-2.5-flash-lite"


def test_consume_clears_state_between_turns() -> None:
    """Second read without a new log line must return None — otherwise
    a 2.5-flash-lite turn could get misattributed to the previous turn's
    model if L1 silently returned a cached response."""
    install_comprehension_capture()

    logging.getLogger("sally.comprehension").info(
        "Layer 1 completed with model: gemini-2.5-flash"
    )
    assert consume_turn_l1_model() == "gemini-2.5-flash"
    assert consume_turn_l1_model() is None


def test_capture_ignores_unrelated_log_lines() -> None:
    """The filter only matches the model-announcement pattern."""
    install_comprehension_capture()
    consume_turn_l1_model()

    logging.getLogger("sally.comprehension").info("Gemini retry succeeded")
    logging.getLogger("sally.comprehension").warning("some other warning")

    assert consume_turn_l1_model() is None


def test_capture_survives_asyncio_to_thread() -> None:
    """Regression test for the ContextVar bug observed live on 2026-04-21:
    `run_comprehension` runs inside `asyncio.to_thread`, which copies the
    calling context into the executor thread. Mutations inside the thread
    only affect the copy — they don't propagate back. So a ContextVar-
    based capture returns None in the main thread even though the filter
    fired in the executor.

    Mirror that pattern: fire the log from a thread (as if comprehension
    was running via to_thread), then consume from the main thread. This
    MUST succeed — any future refactor that reintroduces a ContextVar
    here will fail this test."""
    import asyncio
    install_comprehension_capture()
    consume_turn_l1_model()  # clear

    async def _run() -> Optional[str]:
        def _log_from_thread() -> None:
            logging.getLogger("sally.comprehension").info(
                "Layer 1 completed with model: gemini-2.5-flash-lite"
            )
        await asyncio.to_thread(_log_from_thread)
        return consume_turn_l1_model()

    result = asyncio.run(_run())
    assert result == "gemini-2.5-flash-lite"


def test_install_is_idempotent() -> None:
    """Prewarmed subprocesses re-enter entrypoint per dispatch; the
    filter must not double-register or we'd burn cycles on duplicate
    regex matches per log record."""
    install_comprehension_capture()
    install_comprehension_capture()
    install_comprehension_capture()

    filters = logging.getLogger("sally.comprehension").filters
    tap_count = sum(1 for f in filters if f.__class__.__name__ == "_ComprehensionLogFilter")
    assert tap_count == 1


def test_metrics_sink_writes_one_jsonl_row_per_emit(tmp_path) -> None:
    sink = MetricsSink(tmp_path / "turns.jsonl")
    m = TurnMetrics(
        call_id="job_xyz",
        turn_index=1,
        personality="sally_warm",
        arm="sally_empathy_plus",
        phase="CONNECTION",
        phase_changed=False,
        user_text="Hey there",
        sally_text="Hey, thanks for jumping on",
        asr_ms=245.0,
        engine_ms=1820.0,
        l1_model="gemini-2.5-flash-lite",
        tts_first_frame_ms=95.0,
        ended=False,
    )
    sink.emit(m)
    sink.emit(m)

    lines = (tmp_path / "turns.jsonl").read_text().strip().split("\n")
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["call_id"] == "job_xyz"
    assert first["arm"] == "sally_empathy_plus"
    assert first["l1_model"] == "gemini-2.5-flash-lite"
    assert first["asr_ms"] == 245.0
    assert first["tts_first_frame_ms"] == 95.0
    assert "timestamp" in first


def test_metrics_sink_creates_parent_dir(tmp_path) -> None:
    """Sink creates intermediate dirs so /tmp/foo/bar works even if
    foo/ doesn't exist yet."""
    sink = MetricsSink(tmp_path / "nested" / "deeper" / "turns.jsonl")
    m = TurnMetrics(
        call_id="c",
        turn_index=1,
        personality="sally_direct",
        arm="sally_direct",
        phase="OWNERSHIP",
        phase_changed=True,
        user_text="ok",
        sally_text="great",
        asr_ms=None,
        engine_ms=None,
        l1_model=None,
        tts_first_frame_ms=None,
        ended=True,
    )
    sink.emit(m)
    assert (tmp_path / "nested" / "deeper" / "turns.jsonl").exists()


def test_metrics_row_serializes_nones_as_null(tmp_path) -> None:
    """Optional fields (asr_ms, l1_model, engine_ms, tts_first_frame_ms)
    must round-trip as null, not omitted — downstream CDS analysis
    counts missing-on-purpose vs missing-from-bug differently."""
    sink = MetricsSink(tmp_path / "turns.jsonl")
    m = TurnMetrics(
        call_id="c",
        turn_index=1,
        personality="sally_confident",
        arm="sally_nepq",
        phase="SITUATION",
        phase_changed=False,
        user_text="yeah",
        sally_text="got it",
        asr_ms=None,
        engine_ms=None,
        l1_model=None,
        tts_first_frame_ms=None,
        ended=False,
    )
    sink.emit(m)
    row = json.loads((tmp_path / "turns.jsonl").read_text())
    assert row["asr_ms"] is None
    assert row["l1_model"] is None
    assert row["engine_ms"] is None
    assert row["tts_first_frame_ms"] is None
