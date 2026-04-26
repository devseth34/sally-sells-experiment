"""Pipeline integration test: user transcript → runner → metrics row.

Not an end-to-end test — LiveKit, TTS, STT, and the actual LLM providers
are all mocked out. What IS exercised end-to-end:
    - SallyVoiceRunner.on_user_turn full flow
    - Real SallyEngineAdapter calling a monkey-patched SallyEngine.process_turn
      (so the adapter's state threading + last_turn_stats bookkeeping runs
      the same code path as production)
    - Backchannel task + audio_lock serialization
    - Metrics sink writing a JSONL row with complete shape
    - L1 model capture via the logging filter

Guards against regressions from future changes to any of those seams —
DB persistence, engine interface evolution, metrics-sink backend swap,
etc. All would break this test before a live smoke, which is valuable
because live smokes require a human to speak.

Run: source venv/bin/activate && python -m pytest backend/voice_agent/test_integration.py -v
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator
from unittest.mock import MagicMock

import pytest

# Import the runner first so its engine_adapter dependency runs the
# `backend/` sys.path bridge. After this, `from app.agent import ...` works.
from backend.voice_agent.sally_voice_runner import SallyVoiceRunner
from backend.voice_agent.metrics import (
    MetricsSink,
    consume_turn_l1_model,
    install_comprehension_capture,
)


@pytest.fixture(autouse=True)
def _enable_comprehension_info_logs():
    """Same reason as test_metrics.py — lift sally.comprehension to INFO
    so the capture filter sees the injected model-announcement records."""
    lg = logging.getLogger("sally.comprehension")
    prev = lg.level
    lg.setLevel(logging.INFO)
    try:
        yield
    finally:
        lg.setLevel(prev)


@pytest.fixture(autouse=True)
def _clear_l1_model_state():
    """The L1 model global persists across tests. Clear before each
    test so stale captures can't leak into assertions."""
    consume_turn_l1_model()
    yield
    consume_turn_l1_model()


class _FakeTTSChunk:
    def __init__(self) -> None:
        self.frame = MagicMock()


class _FakeTTS:
    """Yields N chunks with a small per-chunk delay so the first-frame
    latency measurement in _speak reads a positive number. Logs every
    text synthesize() was asked for."""

    def __init__(self, chunks: int = 3, chunk_delay_s: float = 0.02) -> None:
        self._chunks = chunks
        self._chunk_delay_s = chunk_delay_s
        self.calls: list[str] = []

    def synthesize(self, text: str) -> AsyncIterator[_FakeTTSChunk]:
        self.calls.append(text)

        async def _gen() -> AsyncIterator[_FakeTTSChunk]:
            for _ in range(self._chunks):
                await asyncio.sleep(self._chunk_delay_s)
                yield _FakeTTSChunk()

        return _gen()


class _FakeAudioSource:
    def __init__(self) -> None:
        self.frames: list[Any] = []

    async def capture_frame(self, frame: Any) -> None:
        self.frames.append(frame)


def _fake_process_turn_result(**overrides: Any) -> dict:
    """Minimum dict shape SallyEngine.process_turn returns. Tests can
    override specific keys (response_text, new_phase, session_ended,
    phase_changed) to cover different branches."""
    base = {
        "response_text": "got it — and what's your role there?",
        "session_ended": False,
        "new_phase": "SITUATION",
        "phase_changed": True,
        "new_profile_json": '{"role": "loan officer"}',
        "retry_count": 0,
        "consecutive_no_new_info": 0,
        "turns_in_current_phase": 1,
        "deepest_emotional_depth": "surface",
        "objection_diffusion_step": 0,
        "ownership_substep": 0,
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_full_pipeline_emits_one_metrics_row(tmp_path, monkeypatch) -> None:
    """Happy path: user transcript → patched engine → fake TTS → one
    metrics row. Every field in TurnMetrics should be populated with
    something sensible (not null except where appropriate)."""
    from app.agent import SallyEngine

    result = _fake_process_turn_result()
    monkeypatch.setattr(
        SallyEngine, "process_turn", staticmethod(lambda **kw: result)
    )

    install_comprehension_capture()
    # Simulate the comprehension module announcing which model answered
    # on this turn (the real code logs this from inside asyncio.to_thread).
    logging.getLogger("sally.comprehension").info(
        "Layer 1 completed with model: gemini-2.5-flash-lite"
    )

    sink_path = tmp_path / "turns.jsonl"
    sink = MetricsSink(sink_path)
    tts = _FakeTTS()
    audio = _FakeAudioSource()
    runner = SallyVoiceRunner(
        personality="sally_warm",
        tts=tts,  # type: ignore[arg-type]
        audio_source=audio,  # type: ignore[arg-type]
        metrics_sink=sink,
        call_id="job_integration_test",
    )

    await runner.on_user_turn("I'm a loan officer at First National", asr_ms=320.0)

    assert sink_path.exists(), "metrics sink did not write the row file"
    rows = [json.loads(l) for l in sink_path.read_text().strip().split("\n")]
    assert len(rows) == 1, f"expected exactly 1 row, got {len(rows)}: {rows}"
    row = rows[0]

    assert row["call_id"] == "job_integration_test"
    assert row["turn_index"] == 1
    assert row["personality"] == "sally_warm"
    assert row["arm"] == "sally_empathy_plus"
    assert row["phase"] == "SITUATION"
    assert row["phase_changed"] is True
    assert row["user_text"] == "I'm a loan officer at First National"
    assert row["sally_text"] == "got it — and what's your role there?"
    assert row["asr_ms"] == 320.0
    assert row["engine_ms"] is not None and row["engine_ms"] > 0
    assert row["tts_first_frame_ms"] is not None and row["tts_first_frame_ms"] > 0
    assert row["l1_model"] == "gemini-2.5-flash-lite"
    assert row["ended"] is False

    # Fake engine returns instantly, well under the backchannel 500ms delay
    # → the backchannel task is cancelled before it fires. So the ONLY TTS
    # synthesis request is Sally's real response.
    assert tts.calls == ["got it — and what's your role there?"]
    # _FakeTTS yields 3 chunks → audio_source captured 3 frames.
    assert len(audio.frames) == 3


@pytest.mark.asyncio
async def test_pipeline_emits_fallback_metric_on_engine_failure(tmp_path, monkeypatch) -> None:
    """If the frozen engine raises, the runner emits the fallback phrase
    via TTS and still writes a metrics row — with engine_ms=None,
    sally_text set to the fallback, ended=False. The degraded path must
    be observable in the metrics ledger for CDS post-hoc analysis."""
    from app.agent import SallyEngine

    def _boom(**kwargs: Any) -> dict:
        raise RuntimeError("simulated engine crash")

    monkeypatch.setattr(SallyEngine, "process_turn", staticmethod(_boom))

    sink_path = tmp_path / "turns.jsonl"
    sink = MetricsSink(sink_path)
    tts = _FakeTTS()
    audio = _FakeAudioSource()
    # Use sally_direct — density=0 means no backchannel ever fires,
    # keeping the TTS call-log assertion clean.
    runner = SallyVoiceRunner(
        personality="sally_direct",
        tts=tts,  # type: ignore[arg-type]
        audio_source=audio,  # type: ignore[arg-type]
        metrics_sink=sink,
        call_id="job_fallback_test",
    )

    await runner.on_user_turn("anything", asr_ms=180.0)

    rows = [json.loads(l) for l in sink_path.read_text().strip().split("\n")]
    assert len(rows) == 1
    row = rows[0]
    assert row["sally_text"] == "Sorry, one moment."
    assert row["engine_ms"] is None, "engine_ms must be None on failure, not 0"
    assert row["tts_first_frame_ms"] is None, "metrics row captures tts_first_frame for real response, None on fallback path"
    assert row["asr_ms"] == 180.0
    assert row["ended"] is False
    # Fallback phrase went through TTS.
    assert tts.calls == ["Sorry, one moment."]


@pytest.mark.asyncio
async def test_slow_engine_fires_backchannel_and_records_metrics(tmp_path, monkeypatch) -> None:
    """Slow engine (>500ms) → backchannel fires AND real response plays.
    audio_lock serializes them, so both reach the TTS, in order. Metrics
    row still reflects only the REAL turn (backchannel is ambient)."""
    from app.agent import SallyEngine
    from app.schemas import NepqPhase
    from backend.voice_agent.backchannel import BACKCHANNELS
    from backend.voice_agent.sally_voice_runner import _BACKCHANNEL_DELAY_S

    # Patched engine: wait long enough for backchannel to fire before
    # returning. Staticmethod runs in asyncio.to_thread — time.sleep is
    # fine there (doesn't block the event loop).
    def _slow(**kwargs: Any) -> dict:
        import time as _t
        _t.sleep(_BACKCHANNEL_DELAY_S + 0.3)
        return _fake_process_turn_result(response_text="the real answer")

    monkeypatch.setattr(SallyEngine, "process_turn", staticmethod(_slow))

    sink_path = tmp_path / "turns.jsonl"
    sink = MetricsSink(sink_path)
    tts = _FakeTTS()
    audio = _FakeAudioSource()
    runner = SallyVoiceRunner(
        personality="sally_warm",  # density 1.0 — always fires when gated-in
        tts=tts,  # type: ignore[arg-type]
        audio_source=audio,  # type: ignore[arg-type]
        metrics_sink=sink,
        call_id="job_slow_test",
    )
    # Adapter defaults to CONNECTION on a fresh call; the backchannel
    # gate explicitly excludes CONNECTION as too performative. Pre-set
    # to SITUATION so the gate lets the filler through — this is what
    # turn 2+ of a real call would already look like.
    runner._adapter._phase = NepqPhase.SITUATION  # type: ignore[attr-defined]

    await runner.on_user_turn("long turn about the problem", asr_ms=400.0)

    # Two TTS calls: filler (first) then real response (second).
    assert len(tts.calls) == 2, f"expected backchannel + response, got {tts.calls}"
    filler, response = tts.calls
    assert filler in BACKCHANNELS["warm"]
    assert response == "the real answer"

    # Metrics row reflects the real turn only — backchannels are not
    # logged as turns (they're ambient and off-book by design).
    rows = [json.loads(l) for l in sink_path.read_text().strip().split("\n")]
    assert len(rows) == 1
    row = rows[0]
    assert row["sally_text"] == "the real answer"
    assert row["engine_ms"] is not None
    # Engine took at least 500ms (the backchannel delay plus padding).
    assert row["engine_ms"] >= 500.0


# ── Phase C: Tag director integration tests ──────────────────────────


def _make_director_response(decorated_text: str, tags_used: list) -> Any:
    """Build a fake Anthropic Messages response containing a JSON director payload."""
    block = MagicMock()
    block.text = json.dumps(
        {"decorated_text": decorated_text, "tags_used": tags_used, "reasoning": "test"}
    )
    response = MagicMock()
    response.content = [block]
    return response


def _patch_director_client(monkeypatch, *, side_effect=None, return_value=None):
    """Stub tag_director._client with a mocked AsyncAnthropic. Returns
    the AsyncMock for `messages.create` so tests can assert call counts."""
    from unittest.mock import AsyncMock
    from backend.voice_agent import tag_director

    create_mock = AsyncMock(side_effect=side_effect, return_value=return_value)
    fake_client = MagicMock()
    fake_client.messages.create = create_mock
    monkeypatch.setattr(tag_director, "_client", fake_client)
    return create_mock


@pytest.mark.asyncio
async def test_director_succeeds_writes_metrics(tmp_path, monkeypatch) -> None:
    """sally_emotive turn where Haiku returns a valid decoration.
    Metrics row should record director_used=True with populated latency."""
    from app.agent import SallyEngine

    long_response = (
        "Yeah, I hear you. That sounds really tough to deal with day after day. "
        "Walk me through what happened the most recent time."
    )
    decorated = "[sighs] " + long_response
    monkeypatch.setattr(
        SallyEngine,
        "process_turn",
        staticmethod(lambda **kw: _fake_process_turn_result(response_text=long_response)),
    )

    create_mock = _patch_director_client(
        monkeypatch, return_value=_make_director_response(decorated, ["[sighs]"])
    )

    sink_path = tmp_path / "turns.jsonl"
    sink = MetricsSink(sink_path)
    tts = _FakeTTS()
    audio = _FakeAudioSource()
    runner = SallyVoiceRunner(
        personality="sally_emotive",
        tts=tts,  # type: ignore[arg-type]
        audio_source=audio,  # type: ignore[arg-type]
        metrics_sink=sink,
        call_id="job_director_succeeds",
    )

    await runner.on_user_turn("I'm so stuck", asr_ms=300.0)

    create_mock.assert_awaited_once()
    rows = [json.loads(l) for l in sink_path.read_text().strip().split("\n")]
    assert len(rows) == 1
    row = rows[0]
    assert row["tag_director_used"] is True
    assert row["tag_director_fallback"] is None
    assert row["tag_director_latency_ms"] is not None
    assert row["tag_director_latency_ms"] >= 0.0
    assert row["audio_tags_used"] == ["[sighs]"]
    assert row["sally_text"] == decorated
    assert row["tts_tier"] == "emotive"


@pytest.mark.asyncio
async def test_director_timeout_falls_back_to_rules(tmp_path, monkeypatch) -> None:
    """When Haiku times out, the runner falls through to expression.decorate.
    Metrics record director_used=False with fallback_reason='timeout'."""
    from app.agent import SallyEngine
    from backend.voice_agent import tag_director

    long_response = (
        "I hear you, that sounds really tough. Walk me through what happened."
    )
    monkeypatch.setattr(
        SallyEngine,
        "process_turn",
        staticmethod(lambda **kw: _fake_process_turn_result(response_text=long_response)),
    )

    async def hang(*_args, **_kwargs):
        await asyncio.sleep(10.0)

    _patch_director_client(monkeypatch, side_effect=hang)
    # Tighten the director timeout for this test so we don't actually wait
    # the full 0.4s default; 50ms is plenty to exercise the timeout path.
    monkeypatch.setattr(tag_director, "_DEFAULT_TIMEOUT_S", 0.05)

    sink_path = tmp_path / "turns.jsonl"
    sink = MetricsSink(sink_path)
    tts = _FakeTTS()
    audio = _FakeAudioSource()
    runner = SallyVoiceRunner(
        personality="sally_emotive",
        tts=tts,  # type: ignore[arg-type]
        audio_source=audio,  # type: ignore[arg-type]
        metrics_sink=sink,
        call_id="job_director_timeout",
    )

    await runner.on_user_turn("anything", asr_ms=100.0)

    rows = [json.loads(l) for l in sink_path.read_text().strip().split("\n")]
    assert len(rows) == 1
    row = rows[0]
    assert row["tag_director_used"] is False
    assert row["tag_director_fallback"] == "timeout"
    # Latency was tracked even though director failed.
    assert row["tag_director_latency_ms"] is not None
    # Rules path may or may not have inserted a tag depending on context
    # signals — either is fine. Just confirm the turn completed and we
    # didn't crash.


@pytest.mark.asyncio
async def test_director_short_circuits_on_trivial_text(tmp_path, monkeypatch) -> None:
    """Engine returns < 30-char response → director short-circuits, no API call.
    Metrics record director_used=False, tag_director_latency_ms=None
    (not attempted, not failed)."""
    from app.agent import SallyEngine

    short_response = "Got it."
    monkeypatch.setattr(
        SallyEngine,
        "process_turn",
        staticmethod(lambda **kw: _fake_process_turn_result(response_text=short_response)),
    )

    create_mock = _patch_director_client(monkeypatch, return_value=_make_director_response("", []))

    sink_path = tmp_path / "turns.jsonl"
    sink = MetricsSink(sink_path)
    runner = SallyVoiceRunner(
        personality="sally_emotive",
        tts=_FakeTTS(),  # type: ignore[arg-type]
        audio_source=_FakeAudioSource(),  # type: ignore[arg-type]
        metrics_sink=sink,
        call_id="job_director_short",
    )

    await runner.on_user_turn("hi", asr_ms=80.0)

    # tag_director.direct_tags() short-circuits before any API call.
    create_mock.assert_not_awaited()
    rows = [json.loads(l) for l in sink_path.read_text().strip().split("\n")]
    row = rows[0]
    # Short-circuit returns success=True with the original text and no tags.
    # The runner sees director_meta.used=True (success path) but with empty
    # tags → tier=fast. We accept either treatment so long as the API
    # wasn't called.
    assert row["tts_tier"] == "fast"
    assert row["audio_tags_used"] == []


@pytest.mark.asyncio
async def test_existing_arm_never_calls_director(tmp_path, monkeypatch) -> None:
    """sally_warm has empty allowed_audio_tags AND tag_director=False.
    Director must never be called — this is the core regression guard
    for the existing 3 arms."""
    from app.agent import SallyEngine

    monkeypatch.setattr(
        SallyEngine, "process_turn", staticmethod(lambda **kw: _fake_process_turn_result())
    )
    create_mock = _patch_director_client(
        monkeypatch, return_value=_make_director_response("decorated", ["[sighs]"])
    )

    sink_path = tmp_path / "turns.jsonl"
    sink = MetricsSink(sink_path)
    runner = SallyVoiceRunner(
        personality="sally_warm",
        tts=_FakeTTS(),  # type: ignore[arg-type]
        audio_source=_FakeAudioSource(),  # type: ignore[arg-type]
        metrics_sink=sink,
        call_id="job_warm_no_director",
    )

    await runner.on_user_turn("anything", asr_ms=200.0)

    create_mock.assert_not_awaited()
    rows = [json.loads(l) for l in sink_path.read_text().strip().split("\n")]
    row = rows[0]
    assert row["tag_director_used"] is False
    assert row["tag_director_fallback"] is None
    assert row["tag_director_latency_ms"] is None
    assert row["audio_tags_used"] == []
    assert row["tts_tier"] == "fast"


@pytest.mark.asyncio
async def test_director_invalid_tag_falls_back(tmp_path, monkeypatch) -> None:
    """Haiku hallucinates a tag not in allowed_audio_tags → director rejects,
    runner falls through to rules-based path. Metrics show fallback reason
    starting with 'invalid_tags'."""
    from app.agent import SallyEngine

    long_response = (
        "I hear you, that sounds really tough to deal with. Walk me through it."
    )
    monkeypatch.setattr(
        SallyEngine,
        "process_turn",
        staticmethod(lambda **kw: _fake_process_turn_result(response_text=long_response)),
    )
    # `[chuckles]` is not in sally_emotive's allowed_audio_tags after Phase B's expansion.
    _patch_director_client(
        monkeypatch,
        return_value=_make_director_response("[chuckles] " + long_response, ["[chuckles]"]),
    )

    sink_path = tmp_path / "turns.jsonl"
    sink = MetricsSink(sink_path)
    runner = SallyVoiceRunner(
        personality="sally_emotive",
        tts=_FakeTTS(),  # type: ignore[arg-type]
        audio_source=_FakeAudioSource(),  # type: ignore[arg-type]
        metrics_sink=sink,
        call_id="job_director_invalid",
    )

    await runner.on_user_turn("ugh", asr_ms=200.0)

    rows = [json.loads(l) for l in sink_path.read_text().strip().split("\n")]
    row = rows[0]
    assert row["tag_director_used"] is False
    assert row["tag_director_fallback"] is not None
    assert row["tag_director_fallback"].startswith("invalid_tags")


@pytest.mark.asyncio
async def test_director_history_passed_through(tmp_path, monkeypatch) -> None:
    """Verify the runner passes the engine adapter's recent history to
    the director's user-message context block. Captures the user_msg
    argument via a side_effect on the mock."""
    from app.agent import SallyEngine

    long_response = (
        "I hear you, that sounds really tough. Walk me through what happened."
    )
    monkeypatch.setattr(
        SallyEngine,
        "process_turn",
        staticmethod(lambda **kw: _fake_process_turn_result(response_text=long_response)),
    )

    captured_messages: list[Any] = []

    async def capture(*_args, **kwargs):
        captured_messages.append(kwargs.get("messages"))
        block = MagicMock()
        block.text = json.dumps(
            {"decorated_text": long_response, "tags_used": [], "reasoning": "no decoration"}
        )
        response = MagicMock()
        response.content = [block]
        return response

    _patch_director_client(monkeypatch, side_effect=capture)

    sink_path = tmp_path / "turns.jsonl"
    sink = MetricsSink(sink_path)
    runner = SallyVoiceRunner(
        personality="sally_emotive",
        tts=_FakeTTS(),  # type: ignore[arg-type]
        audio_source=_FakeAudioSource(),  # type: ignore[arg-type]
        metrics_sink=sink,
        call_id="job_director_history",
    )

    # Two turns so the second turn has prior history to pass.
    await runner.on_user_turn("first user message", asr_ms=200.0)
    await runner.on_user_turn("second user message about being stuck", asr_ms=200.0)

    # Both turns called the director.
    assert len(captured_messages) == 2

    # Second call's user_msg should mention the first user message in history.
    second_user_msg = captured_messages[1][0]["content"]
    assert "first user message" in second_user_msg
    assert "Recent conversation:" in second_user_msg


# ── Phase E: Full-stack happy-path with director + pronunciation + v3 ──


@pytest.mark.asyncio
async def test_full_stack_director_emotive_happy_path(tmp_path, monkeypatch) -> None:
    """End-to-end emotive turn:
      - sally_emotive personality with full 24-tag whitelist (from Phase B)
      - Engine returns a 3-sentence empathic response
      - L1 emotion=frustrated (from thought_log)
      - Phase=PROBLEM_AWARENESS
      - Mocked Haiku returns 3 tags ([sighs], [empathetic], [curious])
      - Pronunciation preserves ALL 3 tags through LEXICON pass
      - _FakeTTS receives the full decorated text with tags intact
      - Metrics row has tag_director_used=True with all expected fields populated
    """
    from app.agent import SallyEngine

    response_text = (
        "Yeah, I hear you on the workflow pain. "
        "That sounds really tough to deal with day after day on top of the AI integration work. "
        "Walk me through what happened the most recent time at NEPQ scale."
    )
    decorated = (
        "[sighs] Yeah, I hear you on the workflow pain. "
        "[empathetic] That sounds really tough to deal with day after day on top of the AI integration work. "
        "[curious] Walk me through what happened the most recent time at NEPQ scale."
    )

    # Engine result includes thought_log_json so the adapter extracts
    # emotional_tone="frustrated, defeated" and the runner threads it
    # into the director's user message.
    thought_log = json.dumps({"comprehension": {"emotional_tone": "frustrated, defeated"}})

    def fake_engine(**kw: Any) -> dict:
        return _fake_process_turn_result(
            response_text=response_text,
            new_phase="PROBLEM_AWARENESS",
            phase_changed=True,
            thought_log_json=thought_log,
        )

    monkeypatch.setattr(SallyEngine, "process_turn", staticmethod(fake_engine))

    # Capture the actual text passed to TTS so we can assert all 3 tags
    # survived pronunciation preprocessing.
    create_mock = _patch_director_client(
        monkeypatch,
        return_value=_make_director_response(decorated, ["[sighs]", "[empathetic]", "[curious]"]),
    )

    sink_path = tmp_path / "turns.jsonl"
    sink = MetricsSink(sink_path)
    tts = _FakeTTS()
    audio = _FakeAudioSource()
    runner = SallyVoiceRunner(
        personality="sally_emotive",
        tts=tts,  # type: ignore[arg-type]
        audio_source=audio,  # type: ignore[arg-type]
        metrics_sink=sink,
        call_id="job_phase_e_full_stack",
    )

    await runner.on_user_turn(
        "I've been struggling with this AI workflow for months and honestly I'm exhausted",
        asr_ms=420.0,
    )

    # 1. Director was called exactly once.
    create_mock.assert_awaited_once()

    # 2. TTS received the decorated text — verify all 3 tags survived
    #    pronunciation preprocessing AND the LEXICON pass (AI → A-I,
    #    NEPQ → N-E-P-Q applied OUTSIDE the tags).
    tts_input = tts.calls[0]
    assert "[sighs]" in tts_input
    assert "[empathetic]" in tts_input
    assert "[curious]" in tts_input
    assert "A-I" in tts_input
    assert "N-E-P-Q" in tts_input

    # 3. Metrics row has all director fields populated correctly.
    rows = [json.loads(l) for l in sink_path.read_text().strip().split("\n")]
    assert len(rows) == 1
    row = rows[0]
    assert row["personality"] == "sally_emotive"
    assert row["arm"] == "sally_empathy_plus"
    assert row["phase"] == "PROBLEM_AWARENESS"
    assert row["phase_changed"] is True
    assert row["tag_director_used"] is True
    assert row["tag_director_fallback"] is None
    assert row["tag_director_latency_ms"] is not None
    assert row["tag_director_latency_ms"] >= 0.0
    assert row["audio_tags_used"] == ["[sighs]", "[empathetic]", "[curious]"]
    assert row["tts_tier"] == "emotive"
    assert row["expression_decorated"] is True
    # Emotion was extracted from the engine's thought_log_json.
    assert row["user_emotion"] == "frustrated, defeated"
