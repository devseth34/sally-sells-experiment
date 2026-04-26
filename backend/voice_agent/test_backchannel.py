"""Tests for the backchannel injector.

Covers:
    - pick_backchannel: round-robin avoids last 2, falls back gracefully
      when pool is exhausted.
    - should_fire_mid_engine: phase gate, interval gate, density roll.
    - Runner integration: fast engine cancels backchannel, slow engine
      lets it fire, audio_lock serializes backchannel vs Sally's TTS.

Run: source venv/bin/activate && python -m pytest backend/voice_agent/test_backchannel.py -v
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, AsyncIterator
from unittest.mock import MagicMock

import pytest

from backend.voice_agent.backchannel import (
    BACKCHANNELS,
    MIN_INTERVAL_SEC,
    PROBABILISTIC_MULTIPLIER,
    pick_backchannel,
    short_key,
    should_fire_mid_engine,
)


# ---------- pick_backchannel ----------

def test_pick_returns_phrase_from_personality_pool() -> None:
    for personality_suffix, pool in BACKCHANNELS.items():
        phrase = pick_backchannel(f"sally_{personality_suffix}", [])
        assert phrase in pool


def test_pick_avoids_last_two_recent() -> None:
    """Warm has 7 candidates; blocking the last 2 must leave 5 choices."""
    rng = random.Random(0)
    recent = ["mhm", "yeah"]
    for _ in range(50):
        phrase = pick_backchannel("sally_warm", recent, rng=rng)
        assert phrase not in {"mhm", "yeah"}


def test_pick_falls_back_when_pool_exhausted() -> None:
    """Direct has only 3 phrases. If the last 2 used include 2 of them,
    we should still return one of the 3 — specifically NOT the most
    recent one, to avoid stuttering."""
    pool = BACKCHANNELS["direct"]  # ["mhm", "okay", "right"]
    recent = ["mhm", "okay"]
    phrase = pick_backchannel("sally_direct", recent)
    # All three are in the pool, but "okay" is most recent — must not repeat.
    assert phrase in pool
    assert phrase != "okay"


def test_pick_unknown_personality_raises() -> None:
    with pytest.raises(ValueError):
        pick_backchannel("sally_nonexistent", [])


def test_short_key_maps_correctly() -> None:
    assert short_key("sally_warm") == "warm"
    assert short_key("sally_confident") == "confident"
    assert short_key("sally_direct") == "direct"


# ---------- should_fire_mid_engine ----------

def test_connection_phase_never_fires() -> None:
    """Opener phase is deliberately silent — filler would feel
    performative before any rapport is built."""
    assert not should_fire_mid_engine(
        personality="sally_warm",
        phase="CONNECTION",
        seconds_since_last=1000.0,
    )


def test_below_min_interval_never_fires() -> None:
    """Guards against mm-hmm every single turn."""
    assert not should_fire_mid_engine(
        personality="sally_warm",
        phase="PROBLEM_AWARENESS",
        seconds_since_last=MIN_INTERVAL_SEC - 0.01,
    )


def test_direct_personality_never_fires() -> None:
    """Direct density = 0 — tight, no filler, even past the interval."""
    for _ in range(20):
        assert not should_fire_mid_engine(
            personality="sally_direct",
            phase="PROBLEM_AWARENESS",
            seconds_since_last=1000.0,
        )


def test_warm_personality_always_fires_when_gated_in() -> None:
    """Warm density = 1.0. Past interval, past CONNECTION, it must fire."""
    for _ in range(20):
        assert should_fire_mid_engine(
            personality="sally_warm",
            phase="SITUATION",
            seconds_since_last=1000.0,
        )


def test_confident_probabilistic_fires_at_roughly_density() -> None:
    """Confident density = 0.30. Over 1000 seeded rolls, fire-rate
    should land inside ±5% of 30%."""
    rng = random.Random(42)
    fires = sum(
        1
        for _ in range(1000)
        if should_fire_mid_engine(
            personality="sally_confident",
            phase="SITUATION",
            seconds_since_last=1000.0,
            rng=rng,
        )
    )
    expected = int(1000 * PROBABILISTIC_MULTIPLIER["confident"])
    assert abs(fires - expected) < 50, f"fires={fires}, expected ~{expected}"


def test_first_turn_infinite_interval_fires_warm() -> None:
    """A brand-new call has last_fired_at=0 → seconds_since_last=inf.
    Must not trip the interval gate."""
    assert should_fire_mid_engine(
        personality="sally_warm",
        phase="SITUATION",
        seconds_since_last=float("inf"),
    )


# ---------- Runner integration ----------
#
# Mocks the TTS + AudioSource so tests don't touch any network / LK SDK.
# Uses controllable adapter.turn() duration to exercise fast-path cancel
# vs slow-path fire.

class _FakeTTSChunk:
    def __init__(self) -> None:
        self.frame = MagicMock()


class _FakeTTS:
    """Fake TTS that yields N chunks each after an optional delay.

    Tracks every synthesize() call so tests can inspect what was spoken.
    """

    def __init__(self, chunks: int = 2, chunk_delay_s: float = 0.05) -> None:
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
    """Records every captured frame so tests can assert ordering.

    Keeping the frames list append-only also lets us assert how many
    _speak calls (counted as bursts of frames) ran, though the TTS
    call-log is the cleaner check.
    """

    def __init__(self) -> None:
        self.frames: list[Any] = []

    async def capture_frame(self, frame: Any) -> None:
        self.frames.append(frame)


class _FakeAdapter:
    """Simulates SallyEngineAdapter: configurable turn delay and phase."""

    def __init__(self, *, turn_delay_s: float, phase: str = "SITUATION", response: str = "reply") -> None:
        self._delay = turn_delay_s
        self._phase = phase
        self._response = response
        self.turn_calls: list[str] = []
        self.last_turn_stats: dict = {}
        self.arm_key = "sally_empathy_plus"
        self.ended = False
        self.last_user_emotion = None  # Phase E field — always None in backchannel tests

    @property
    def current_phase(self) -> str:
        return self._phase

    async def turn(self, transcript: str) -> tuple[str, bool]:
        self.turn_calls.append(transcript)
        await asyncio.sleep(self._delay)
        self.last_turn_stats = {
            "phase": self._phase,
            "phase_changed": False,
            "engine_ms": self._delay * 1000,
            "ended": False,
        }
        return self._response, False


def _make_runner(
    *,
    personality: str = "sally_warm",
    adapter: _FakeAdapter,
    tts: _FakeTTS,
) -> Any:
    """Build a SallyVoiceRunner but swap in the fake adapter via the
    attribute the real __init__ sets. Avoids having to inject through
    the constructor surface (which would add test-only plumbing)."""
    from backend.voice_agent.sally_voice_runner import SallyVoiceRunner

    audio = _FakeAudioSource()
    runner = SallyVoiceRunner(
        personality=personality,
        tts=tts,  # type: ignore[arg-type]
        audio_source=audio,  # type: ignore[arg-type]
    )
    runner._adapter = adapter  # type: ignore[attr-defined]
    return runner, audio


@pytest.mark.asyncio
async def test_fast_engine_cancels_backchannel() -> None:
    """Engine returns before _BACKCHANNEL_DELAY_S → filler never plays.
    Only Sally's real response shows up in the TTS call log."""
    from backend.voice_agent.sally_voice_runner import _BACKCHANNEL_DELAY_S

    tts = _FakeTTS()
    adapter = _FakeAdapter(turn_delay_s=_BACKCHANNEL_DELAY_S / 4, response="real-response")
    runner, _audio = _make_runner(adapter=adapter, tts=tts)

    await runner.on_user_turn("hello")
    await asyncio.sleep(0.05)  # allow any lingering task to settle

    assert tts.calls == ["real-response"], f"expected only real response, got {tts.calls}"


@pytest.mark.asyncio
async def test_slow_engine_fires_backchannel_then_speaks() -> None:
    """Engine takes longer than the backchannel delay → filler plays,
    then Sally's response. audio_lock ensures ORDERING (filler first,
    then response) even though both are async."""
    from backend.voice_agent.sally_voice_runner import _BACKCHANNEL_DELAY_S

    tts = _FakeTTS()
    # Warm personality: density 1.0, filler always fires when gated-in.
    adapter = _FakeAdapter(turn_delay_s=_BACKCHANNEL_DELAY_S + 0.4, phase="SITUATION", response="real-response")
    runner, _audio = _make_runner(personality="sally_warm", adapter=adapter, tts=tts)
    # Prime the last-fired clock so seconds_since_last passes the gate.
    runner._last_backchannel_at = 0.0  # first-turn inf path  # type: ignore[attr-defined]

    await runner.on_user_turn("long user turn")

    assert len(tts.calls) == 2, f"expected backchannel + response, got {tts.calls}"
    # Filler first (index 0), then real response (index 1).
    filler, response = tts.calls
    assert filler in BACKCHANNELS["warm"]
    assert response == "real-response"


@pytest.mark.asyncio
async def test_direct_personality_never_fires_mid_engine() -> None:
    """Direct density=0 → even with a slow engine, no filler."""
    from backend.voice_agent.sally_voice_runner import _BACKCHANNEL_DELAY_S

    tts = _FakeTTS()
    adapter = _FakeAdapter(turn_delay_s=_BACKCHANNEL_DELAY_S + 0.4, response="direct-response")
    runner, _audio = _make_runner(personality="sally_direct", adapter=adapter, tts=tts)

    await runner.on_user_turn("anything")

    assert tts.calls == ["direct-response"]


@pytest.mark.asyncio
async def test_backchannel_skipped_in_connection_phase() -> None:
    """CONNECTION phase gates out regardless of density."""
    from backend.voice_agent.sally_voice_runner import _BACKCHANNEL_DELAY_S

    tts = _FakeTTS()
    adapter = _FakeAdapter(
        turn_delay_s=_BACKCHANNEL_DELAY_S + 0.4,
        phase="CONNECTION",
        response="opener-reply",
    )
    runner, _audio = _make_runner(personality="sally_warm", adapter=adapter, tts=tts)

    await runner.on_user_turn("hey")

    assert tts.calls == ["opener-reply"]


@pytest.mark.asyncio
async def test_interval_gate_prevents_second_backchannel_too_soon() -> None:
    """Turn 1 fires backchannel → turn 2 must NOT fire because
    seconds_since_last < MIN_INTERVAL_SEC (unless we sleep 8s, which
    we don't in this test). Verifies state persists across turns."""
    from backend.voice_agent.sally_voice_runner import _BACKCHANNEL_DELAY_S

    tts = _FakeTTS()
    adapter = _FakeAdapter(turn_delay_s=_BACKCHANNEL_DELAY_S + 0.4, phase="SITUATION", response="r")
    runner, _audio = _make_runner(personality="sally_warm", adapter=adapter, tts=tts)

    await runner.on_user_turn("turn 1")
    assert len(tts.calls) == 2  # filler + r

    # Immediately re-fire — interval gate should block the second filler.
    await runner.on_user_turn("turn 2")
    # Second turn only adds the response, no filler.
    assert len(tts.calls) == 3
    assert tts.calls[2] == "r"
