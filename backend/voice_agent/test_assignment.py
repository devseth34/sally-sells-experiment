"""Tests for voice-call personality assignment.

Run: source venv/bin/activate && python -m pytest backend/voice_agent/test_assignment.py -v
"""

from __future__ import annotations

import random
from collections import Counter

import pytest

from backend.voice_agent.assignment import assign_personality
from backend.voice_agent.personalities import PERSONALITIES

_ARMS = set(PERSONALITIES.keys())


def test_returns_one_of_the_three_locked_personalities() -> None:
    result = assign_personality()
    assert result in _ARMS


def test_seeded_rng_is_deterministic() -> None:
    """Same seed -> same sequence. Guards the test below and tests in Day 5
    that will replay assignment sequences from production logs."""
    rng_a = random.Random(42)
    rng_b = random.Random(42)
    seq_a = [assign_personality(rng=rng_a) for _ in range(20)]
    seq_b = [assign_personality(rng=rng_b) for _ in range(20)]
    assert seq_a == seq_b


def test_uniform_distribution_over_3000_draws() -> None:
    """All three arms should be reachable and roughly evenly distributed.

    3000 draws / 3 arms = 1000 expected each. A seeded uniform draw sits
    easily within ±5% of that (±50 draws). Tighter bounds would cause
    flakes; looser wouldn't catch a regression that, e.g., dropped one
    arm entirely.
    """
    rng = random.Random(1337)
    counts = Counter(assign_personality(rng=rng) for _ in range(3000))
    assert set(counts.keys()) == _ARMS, "every arm must be reachable"
    for arm, count in counts.items():
        assert 950 <= count <= 1050, f"{arm} drew {count} times, expected 1000 ±50"


@pytest.mark.parametrize("stratum", [None, "cold", "warm", "hot", "unknown_future_value"])
def test_stratum_is_accepted_but_currently_ignored(stratum: str | None) -> None:
    """The stratum hook must not crash on any string or None.

    Day 5 will wire this into real stratified logic. Guarding the
    signature here so callers from Day 4 don't break on the swap.
    """
    result = assign_personality(stratum=stratum)
    assert result in _ARMS


def test_default_rng_picks_randomly_across_calls() -> None:
    """Without a seeded rng, repeated calls should not return the same
    arm every time. Very weak probabilistic assertion (fails with
    probability 1/3**20 ≈ 3e-10 if the default rng is actually uniform)."""
    picks = {assign_personality() for _ in range(20)}
    assert len(picks) >= 2, "default rng appears deterministic — is it seeded?"
