"""
Integration tests for hybrid bot arms.
Tests that:
1. All 8 arms can be created and assigned
2. Hybrid arms route through Sally's engine (not control bots)
3. Persona overrides are correctly looked up for each arm+phase combo
4. Persona overrides are None for phases that should use default Sally persona
5. Original Sally/Hank/Ivy arms are completely untouched
6. ThoughtLog includes active_persona field
7. is_sally flag correctly includes hybrid arms
8. generate_response() accepts persona_override parameter
"""

import pytest
import inspect
from app.schemas import BotArm
from app.persona_config import (
    get_persona_for_arm_phase,
    HYBRID_PERSONA_MAP,
    SALLY_ENGINE_ARMS,
)
from app.models import ThoughtLog
from app.layers.response import generate_response


ALL_PHASES = [
    "CONNECTION", "SITUATION", "PROBLEM_AWARENESS",
    "SOLUTION_AWARENESS", "CONSEQUENCE", "OWNERSHIP", "COMMITMENT",
]


# ============================================================
# TEST 1: BotArm enum has all 8 values
# ============================================================

def test_bot_arm_enum_has_all_eight():
    expected = {
        "sally_nepq", "hank_hypes", "ivy_informs",
        "sally_hank_close", "sally_ivy_bridge",
        "sally_empathy_plus", "sally_direct", "hank_structured",
    }
    actual = {arm.value for arm in BotArm}
    assert expected == actual, f"Missing arms: {expected - actual}, Extra arms: {actual - expected}"


# ============================================================
# TEST 2: SALLY_ENGINE_ARMS includes all Sally-engine arms
# ============================================================

def test_sally_engine_arms_set():
    expected_sally_arms = {
        "sally_nepq", "sally_hank_close", "sally_ivy_bridge",
        "sally_empathy_plus", "sally_direct", "hank_structured",
    }
    assert expected_sally_arms == SALLY_ENGINE_ARMS


# ============================================================
# TEST 3: Original arms have NO persona overrides
# ============================================================

def test_original_sally_has_no_overrides():
    """Sally 100% should never have a persona override."""
    for phase in ALL_PHASES:
        override = get_persona_for_arm_phase("sally_nepq", phase)
        assert override is None, f"sally_nepq should have no override for {phase}"


def test_original_hank_not_in_sally_engine():
    """Hank 100% should NOT be in SALLY_ENGINE_ARMS."""
    assert "hank_hypes" not in SALLY_ENGINE_ARMS


def test_original_ivy_not_in_sally_engine():
    """Ivy 100% should NOT be in SALLY_ENGINE_ARMS."""
    assert "ivy_informs" not in SALLY_ENGINE_ARMS


# ============================================================
# TEST 4: Sally > Hank Close overrides only OWNERSHIP + COMMITMENT
# ============================================================

def test_sally_hank_close_overrides():
    assert get_persona_for_arm_phase("sally_hank_close", "OWNERSHIP") is not None
    assert get_persona_for_arm_phase("sally_hank_close", "COMMITMENT") is not None

    for phase in ["CONNECTION", "SITUATION", "PROBLEM_AWARENESS", "SOLUTION_AWARENESS", "CONSEQUENCE"]:
        assert get_persona_for_arm_phase("sally_hank_close", phase) is None, \
            f"sally_hank_close should not override {phase}"


# ============================================================
# TEST 5: Sally > Ivy Bridge overrides only PROBLEM + SOLUTION
# ============================================================

def test_sally_ivy_bridge_overrides():
    assert get_persona_for_arm_phase("sally_ivy_bridge", "PROBLEM_AWARENESS") is not None
    assert get_persona_for_arm_phase("sally_ivy_bridge", "SOLUTION_AWARENESS") is not None

    for phase in ["CONNECTION", "SITUATION", "CONSEQUENCE", "OWNERSHIP", "COMMITMENT"]:
        assert get_persona_for_arm_phase("sally_ivy_bridge", phase) is None, \
            f"sally_ivy_bridge should not override {phase}"


# ============================================================
# TEST 6: Full-override arms have overrides for ALL phases
# ============================================================

def test_empathy_plus_overrides_all_phases():
    for phase in ALL_PHASES:
        assert get_persona_for_arm_phase("sally_empathy_plus", phase) is not None, \
            f"sally_empathy_plus missing override for {phase}"


def test_sally_direct_overrides_all_phases():
    for phase in ALL_PHASES:
        assert get_persona_for_arm_phase("sally_direct", phase) is not None, \
            f"sally_direct missing override for {phase}"


def test_hank_structured_overrides_all_phases():
    for phase in ALL_PHASES:
        assert get_persona_for_arm_phase("hank_structured", phase) is not None, \
            f"hank_structured missing override for {phase}"


# ============================================================
# TEST 7: Persona override strings are non-empty and substantial
# ============================================================

def test_persona_overrides_are_substantial():
    """Each persona override should be a real prompt, not empty or trivially short."""
    for (arm, phase), persona in HYBRID_PERSONA_MAP.items():
        assert isinstance(persona, str), f"({arm}, {phase}) persona is not a string"
        assert len(persona) > 100, f"({arm}, {phase}) persona is too short ({len(persona)} chars)"


# ============================================================
# TEST 8: get_persona_for_arm_phase returns None for unknown arms
# ============================================================

def test_unknown_arm_returns_none():
    assert get_persona_for_arm_phase("nonexistent_arm", "CONNECTION") is None


def test_unknown_phase_returns_none():
    assert get_persona_for_arm_phase("sally_hank_close", "NONEXISTENT_PHASE") is None


# ============================================================
# TEST 9: Random assignment includes all 8 arms
# ============================================================

def test_random_assignment_pool():
    """Verify all 8 arms are in the random assignment pool by checking BotArm enum size."""
    assert len(BotArm) == 8, f"Expected 8 BotArm values, got {len(BotArm)}"


# ============================================================
# TEST 10: is_sally logic covers hybrid arms
# ============================================================

def test_is_sally_includes_hybrids():
    """All hybrid arms should be treated as 'is_sally' for state tracking purposes."""
    for arm_value in ["sally_nepq", "sally_hank_close", "sally_ivy_bridge",
                      "sally_empathy_plus", "sally_direct", "hank_structured"]:
        assert arm_value in SALLY_ENGINE_ARMS, f"{arm_value} should be in SALLY_ENGINE_ARMS"

    assert "hank_hypes" not in SALLY_ENGINE_ARMS
    assert "ivy_informs" not in SALLY_ENGINE_ARMS


# ============================================================
# TEST 11: Partial-override arms don't leak across phases
# ============================================================

def test_no_cross_contamination():
    """Verify that arm A's overrides don't appear when querying arm B."""
    shc_ownership = get_persona_for_arm_phase("sally_hank_close", "OWNERSHIP")
    sib_ownership = get_persona_for_arm_phase("sally_ivy_bridge", "OWNERSHIP")
    assert sib_ownership is None, "sally_ivy_bridge should not have OWNERSHIP override"
    assert shc_ownership is not None


# ============================================================
# TEST 12: ThoughtLog model has active_persona field
# ============================================================

def test_thought_log_has_active_persona_field():
    """ThoughtLog Pydantic model should have active_persona with a default value."""
    fields = ThoughtLog.model_fields
    assert "active_persona" in fields, "ThoughtLog missing active_persona field"
    assert fields["active_persona"].default == "sally_default"


# ============================================================
# TEST 13: generate_response() accepts persona_override parameter
# ============================================================

def test_generate_response_accepts_persona_override():
    """generate_response() should accept persona_override as a keyword argument."""
    sig = inspect.signature(generate_response)
    assert "persona_override" in sig.parameters, \
        "generate_response() missing persona_override parameter"
    param = sig.parameters["persona_override"]
    assert param.default is None, "persona_override should default to None"


# ============================================================
# TEST 14: BOT_DISPLAY_NAMES has all 8 arms
# ============================================================

def test_bot_display_names_complete():
    from app.bot_router import BOT_DISPLAY_NAMES
    for arm in BotArm:
        assert arm in BOT_DISPLAY_NAMES, f"{arm.value} missing from BOT_DISPLAY_NAMES"


# ============================================================
# TEST 15: SALLY_ENGINE_ARMS is a frozenset (immutable)
# ============================================================

def test_sally_engine_arms_immutable():
    assert isinstance(SALLY_ENGINE_ARMS, frozenset), "SALLY_ENGINE_ARMS should be a frozenset"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
