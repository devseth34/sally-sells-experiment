"""Tests for SallyEngineAdapter.

These tests patch `SallyEngine.process_turn` so they DON'T hit the real
Gemini + Claude APIs. Goals:
    - state threading: counters and phase advance across turns.
    - arm_key mapping from personality -> engine arm.
    - session_ended flag is honored and subsequent turn() calls no-op.

For an end-to-end smoke with the real engine, see the Agent Console
test in sally.py (that's the Day 4 deliverable, not a unit test).

Run: source venv/bin/activate && python -m pytest backend/voice_agent/test_engine_adapter.py -v
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.voice_agent.engine_adapter import SallyEngineAdapter
from backend.voice_agent.personalities import PERSONALITIES


def _fake_result(text: str, phase: str = "CONNECTION", ended: bool = False, **overrides):
    """Build a fake SallyEngine.process_turn() return dict."""
    base = {
        "response_text": text,
        "new_phase": phase,
        "new_profile_json": "{}",
        "thought_log_json": "{}",
        "phase_changed": False,
        "session_ended": ended,
        "retry_count": 0,
        "consecutive_no_new_info": 0,
        "turns_in_current_phase": 1,
        "deepest_emotional_depth": "surface",
        "objection_diffusion_step": 0,
        "ownership_substep": 0,
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize("personality", list(PERSONALITIES.keys()))
def test_personality_maps_to_engine_arm(personality: str) -> None:
    adapter = SallyEngineAdapter(personality)
    assert adapter.arm_key == PERSONALITIES[personality]["engine_arm"]


def test_rejects_unknown_personality() -> None:
    with pytest.raises(ValueError, match="Unknown personality"):
        SallyEngineAdapter("sally_mystery")


def test_opener_is_static_greeting() -> None:
    adapter = SallyEngineAdapter("sally_direct")
    greeting = adapter.opener()
    # Sanity check — don't pin exact wording (the frozen engine owns it)
    # but make sure it's not empty and mentions "Sally" or "100x".
    assert greeting
    assert "Sally" in greeting or "100x" in greeting


@pytest.mark.asyncio
async def test_turn_threads_state_across_calls() -> None:
    """Phase advance from one turn must feed into the next turn's
    current_phase. Guards against the adapter losing state between
    calls, which would break NEPQ flow invariants."""
    seen_phases: list[str] = []

    def fake_process(**kwargs):
        seen_phases.append(kwargs["current_phase"].value)
        # Advance CONNECTION -> PROBLEM_AWARENESS on turn 2
        if kwargs["turn_number"] == 1:
            return _fake_result("Hi!", phase="CONNECTION")
        return _fake_result("Tell me more.", phase="PROBLEM_AWARENESS", phase_changed=True)

    adapter = SallyEngineAdapter("sally_warm")
    with patch("backend.voice_agent.engine_adapter.SallyEngine.process_turn", side_effect=fake_process):
        r1, ended1 = await adapter.turn("hello")
        r2, ended2 = await adapter.turn("yeah it's been hard")

    assert r1 == "Hi!"
    assert r2 == "Tell me more."
    assert ended1 is False and ended2 is False
    # First call saw the initial CONNECTION; second saw the engine-reported
    # CONNECTION (since we advanced on the return, not the input of turn 2).
    # After turn 2 returns, adapter should hold PROBLEM_AWARENESS.
    assert seen_phases == ["CONNECTION", "CONNECTION"]
    assert adapter.snapshot_state()["phase"] == "PROBLEM_AWARENESS"


@pytest.mark.asyncio
async def test_turn_appends_to_history_in_order() -> None:
    """History must contain user then assistant in strict alternation,
    matching what SallyEngine.process_turn expects on subsequent calls."""
    adapter = SallyEngineAdapter("sally_nepq" if "sally_nepq" in PERSONALITIES else "sally_confident")
    captured_histories: list[list[dict]] = []

    def fake_process(**kwargs):
        captured_histories.append(list(kwargs["conversation_history"]))
        return _fake_result("Got it.")

    with patch("backend.voice_agent.engine_adapter.SallyEngine.process_turn", side_effect=fake_process):
        await adapter.turn("first message")
        await adapter.turn("second message")

    # Turn 1's engine call sees [user:first]
    # Turn 2's engine call sees [user:first, assistant:Got it., user:second]
    assert captured_histories[0] == [{"role": "user", "content": "first message"}]
    assert captured_histories[1] == [
        {"role": "user", "content": "first message"},
        {"role": "assistant", "content": "Got it."},
        {"role": "user", "content": "second message"},
    ]


@pytest.mark.asyncio
async def test_session_ended_flag_propagates_and_blocks_further_turns() -> None:
    """Once the engine reports session_ended=True, the adapter must
    refuse further turns — calling the engine again after TERMINATED
    would be a bug."""
    adapter = SallyEngineAdapter("sally_direct")
    call_count = 0

    def fake_process(**kwargs):
        nonlocal call_count
        call_count += 1
        return _fake_result("Thanks, bye!", ended=True)

    with patch("backend.voice_agent.engine_adapter.SallyEngine.process_turn", side_effect=fake_process):
        r1, ended1 = await adapter.turn("I'm done")
        r2, ended2 = await adapter.turn("wait one more thing")

    assert ended1 is True
    assert ended2 is True
    assert r2 == ""  # adapter refuses to call engine again
    assert call_count == 1  # engine only invoked once
    assert adapter.ended is True


@pytest.mark.asyncio
async def test_arm_key_passed_through_to_engine() -> None:
    """The engine must receive our personality's arm_key, not something
    invented by the adapter. This is the glue between Day 3's voice
    layer (which thinks in personalities) and the frozen engine (which
    thinks in arms)."""
    seen_arm: list[str | None] = []

    def fake_process(**kwargs):
        seen_arm.append(kwargs.get("arm_key"))
        return _fake_result("ok")

    adapter = SallyEngineAdapter("sally_warm")
    with patch("backend.voice_agent.engine_adapter.SallyEngine.process_turn", side_effect=fake_process):
        await adapter.turn("hi")

    assert seen_arm[0] == PERSONALITIES["sally_warm"]["engine_arm"]


# ── Emotion plumbing (Phase E, for sally_emotive expression layer) ────


@pytest.mark.asyncio
async def test_user_emotion_extracted_from_thought_log() -> None:
    """When L1's emotional_tone is present under
    thought_log["comprehension"]["emotional_tone"], the adapter must
    surface it via `last_user_emotion`."""
    import json
    thought_log = json.dumps(
        {"comprehension": {"emotional_tone": "engaged, frustrated, defensive"}}
    )

    def fake_process(**kwargs):
        return _fake_result("Sounds tough.", thought_log_json=thought_log)

    adapter = SallyEngineAdapter("sally_emotive")
    with patch("backend.voice_agent.engine_adapter.SallyEngine.process_turn", side_effect=fake_process):
        await adapter.turn("the workflow is killing me")

    assert adapter.last_user_emotion == "engaged, frustrated, defensive"


@pytest.mark.asyncio
async def test_user_emotion_handles_flat_thought_log() -> None:
    """Some engine paths may serialize emotional_tone at the top level
    of thought_log instead of nested under `comprehension`. Adapter
    should handle both shapes."""
    import json
    thought_log = json.dumps({"emotional_tone": "excited"})

    def fake_process(**kwargs):
        return _fake_result("Great!", thought_log_json=thought_log)

    adapter = SallyEngineAdapter("sally_emotive")
    with patch("backend.voice_agent.engine_adapter.SallyEngine.process_turn", side_effect=fake_process):
        await adapter.turn("yes!")

    assert adapter.last_user_emotion == "excited"


@pytest.mark.asyncio
async def test_user_emotion_none_when_thought_log_missing() -> None:
    """Engine can omit thought_log_json entirely on fast-path or fallback
    runs. Adapter must default to None, never crash."""
    def fake_process(**kwargs):
        # Pop the default thought_log_json to simulate engine not setting it
        result = _fake_result("ok")
        result.pop("thought_log_json", None)
        return result

    adapter = SallyEngineAdapter("sally_emotive")
    with patch("backend.voice_agent.engine_adapter.SallyEngine.process_turn", side_effect=fake_process):
        await adapter.turn("hi")

    assert adapter.last_user_emotion is None


@pytest.mark.asyncio
async def test_user_emotion_none_when_thought_log_malformed() -> None:
    """Garbled JSON must not crash the turn. Defensive parse → None."""
    def fake_process(**kwargs):
        return _fake_result("ok", thought_log_json="not valid json {{{ ")

    adapter = SallyEngineAdapter("sally_emotive")
    with patch("backend.voice_agent.engine_adapter.SallyEngine.process_turn", side_effect=fake_process):
        await adapter.turn("hi")

    assert adapter.last_user_emotion is None


@pytest.mark.asyncio
async def test_user_emotion_none_when_field_absent() -> None:
    """Valid JSON without an emotional_tone field → None (not "")."""
    import json
    thought_log = json.dumps({"comprehension": {"intent": "agreement"}})

    def fake_process(**kwargs):
        return _fake_result("ok", thought_log_json=thought_log)

    adapter = SallyEngineAdapter("sally_emotive")
    with patch("backend.voice_agent.engine_adapter.SallyEngine.process_turn", side_effect=fake_process):
        await adapter.turn("hi")

    assert adapter.last_user_emotion is None


@pytest.mark.asyncio
async def test_user_emotion_resets_between_turns() -> None:
    """A frustrated emotion on turn 1 must NOT bleed into turn 2 if
    turn 2's thought_log lacks the field. No stale emotion leakage."""
    import json
    log_with = json.dumps({"comprehension": {"emotional_tone": "frustrated"}})
    log_without = json.dumps({"comprehension": {}})

    call = {"n": 0}

    def fake_process(**kwargs):
        call["n"] += 1
        if call["n"] == 1:
            return _fake_result("ok 1", thought_log_json=log_with)
        return _fake_result("ok 2", thought_log_json=log_without)

    adapter = SallyEngineAdapter("sally_emotive")
    with patch("backend.voice_agent.engine_adapter.SallyEngine.process_turn", side_effect=fake_process):
        await adapter.turn("hi")
        assert adapter.last_user_emotion == "frustrated"
        await adapter.turn("hi again")
        assert adapter.last_user_emotion is None  # reset, not carried over


@pytest.mark.asyncio
async def test_last_turn_stats_includes_user_emotion() -> None:
    """Phase F's metrics emission reads `last_turn_stats` for
    observability fields. Make sure user_emotion is exposed there too."""
    import json
    thought_log = json.dumps({"comprehension": {"emotional_tone": "excited"}})

    def fake_process(**kwargs):
        return _fake_result("ok", thought_log_json=thought_log)

    adapter = SallyEngineAdapter("sally_emotive")
    with patch("backend.voice_agent.engine_adapter.SallyEngine.process_turn", side_effect=fake_process):
        await adapter.turn("yes!")

    assert adapter.last_turn_stats.get("user_emotion") == "excited"
