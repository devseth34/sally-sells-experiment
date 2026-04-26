"""Unit tests for the expression decoration layer.

The expression layer is a pure function — no network, no model calls,
no async. Tests are seeded for determinism and exercise:
    • tier == "emotive" iff at least one tag was inserted
    • whitelist enforcement (no leakage outside allowed_tags)
    • emotion override beats phase
    • short-text guard
    • tag positioning rules (never adjacent, never at position 0)
    • disfluency density approximation over many runs
"""

from __future__ import annotations

import random
import re

import pytest

from backend.voice_agent.expression import (
    DISFLUENCY_PHRASES,
    EMOTION_TAG_OVERRIDES,
    PHASE_TAG_POOLS,
    decorate,
)


# Common test inputs. Long enough to clear the 30-char minimum and
# multi-sentence so tag insertion + disfluency injection both have
# room to act.
LONG_TEXT = (
    "I hear you on the workflow pain. "
    "That sounds genuinely frustrating to deal with day after day. "
    "Can you walk me through what a typical morning looks like for you?"
)

SHORT_TEXT = "Got it."

ALL_WARM_TAGS = [
    "[chuckles]", "[warm chuckle]", "[gentle laugh]",
    "[curious]", "[hmm]", "[sighs]", "[empathetic]", "[hesitant]",
]


# ── Determinism ───────────────────────────────────────────────────────


def test_decorate_is_deterministic_under_seeded_rng() -> None:
    rng1 = random.Random(42)
    rng2 = random.Random(42)
    out1 = decorate(
        LONG_TEXT,
        phase="PROBLEM_AWARENESS",
        user_emotion="frustrated",
        personality="sally_emotive",
        allowed_tags=ALL_WARM_TAGS,
        disfluency_density=0.45,
        rng=rng1,
    )
    out2 = decorate(
        LONG_TEXT,
        phase="PROBLEM_AWARENESS",
        user_emotion="frustrated",
        personality="sally_emotive",
        allowed_tags=ALL_WARM_TAGS,
        disfluency_density=0.45,
        rng=rng2,
    )
    assert out1 == out2


# ── Whitelist enforcement ─────────────────────────────────────────────


def test_only_whitelisted_tags_appear() -> None:
    allowed = ["[sighs]", "[empathetic]"]
    decorated, tags_used, _ = decorate(
        LONG_TEXT,
        phase="PROBLEM_AWARENESS",
        user_emotion="frustrated",
        personality="sally_emotive",
        allowed_tags=allowed,
        disfluency_density=0.0,  # disable disfluencies to keep test focused
        rng=random.Random(1),
    )
    for tag in tags_used:
        assert tag in allowed, f"unauthorized tag: {tag}"
    # No non-whitelisted tag tokens leaked into the decorated text either.
    found_tags = re.findall(r"\[[^\]]+\]", decorated)
    for tag in found_tags:
        assert tag in allowed, f"unauthorized tag leaked: {tag}"


def test_empty_whitelist_returns_fast_tier_no_tags() -> None:
    decorated, tags_used, tier = decorate(
        LONG_TEXT,
        phase="PROBLEM_AWARENESS",
        user_emotion="frustrated",
        personality="sally_emotive",
        allowed_tags=[],
        disfluency_density=0.0,
        rng=random.Random(1),
    )
    assert tier == "fast"
    assert tags_used == []
    # No tag-bracket tokens in the output.
    assert "[" not in decorated and "]" not in decorated


# ── Emotion override beats phase ──────────────────────────────────────


def test_emotion_override_picks_from_emotion_pool() -> None:
    # CONNECTION phase pool is [chuckles, warm chuckle]. With
    # user_emotion="frustrated", we should pick from the frustrated
    # override pool (sighs/empathetic) instead.
    allowed = ALL_WARM_TAGS
    _, tags_used, tier = decorate(
        LONG_TEXT,
        phase="CONNECTION",
        user_emotion="frustrated",
        personality="sally_emotive",
        allowed_tags=allowed,
        disfluency_density=0.0,
        rng=random.Random(99),
    )
    assert tier == "emotive"
    frustrated_pool = set(EMOTION_TAG_OVERRIDES["frustrat"])
    connection_only = set(PHASE_TAG_POOLS["CONNECTION"]) - frustrated_pool
    for tag in tags_used:
        assert tag not in connection_only, (
            f"connection-only tag {tag} should not appear when user is frustrated"
        )


def test_no_emotion_falls_through_to_phase_pool() -> None:
    allowed = ALL_WARM_TAGS
    _, tags_used, tier = decorate(
        LONG_TEXT,
        phase="CONSEQUENCE",
        user_emotion=None,
        personality="sally_emotive",
        allowed_tags=allowed,
        disfluency_density=0.0,
        rng=random.Random(42),
    )
    assert tier == "emotive"
    consequence_pool = set(PHASE_TAG_POOLS["CONSEQUENCE"])
    for tag in tags_used:
        assert tag in consequence_pool


def test_substring_emotion_match() -> None:
    # L1 sometimes returns multi-word `emotional_tone` like
    # "engaged, frustrated, defensive". Substring match should still
    # pick up "frustrat" and route to that override pool.
    allowed = ALL_WARM_TAGS
    _, tags_used, _ = decorate(
        LONG_TEXT,
        phase="CONNECTION",
        user_emotion="engaged, frustrated, defensive",
        personality="sally_emotive",
        allowed_tags=allowed,
        disfluency_density=0.0,
        rng=random.Random(7),
    )
    # "frustrat" wins over "defensive" because it appears first in
    # EMOTION_TAG_OVERRIDES iteration order. Either pool is acceptable
    # since both override CONNECTION's pool — assert tags came from
    # one of them, not the connection pool.
    valid_tags = (
        set(EMOTION_TAG_OVERRIDES["frustrat"]) | set(EMOTION_TAG_OVERRIDES["defensive"])
    )
    for tag in tags_used:
        assert tag in valid_tags


# ── Short-text guard ──────────────────────────────────────────────────


def test_short_text_returns_unchanged_fast_tier() -> None:
    decorated, tags_used, tier = decorate(
        SHORT_TEXT,
        phase="CONNECTION",
        user_emotion=None,
        personality="sally_emotive",
        allowed_tags=ALL_WARM_TAGS,
        disfluency_density=0.45,
        rng=random.Random(1),
    )
    assert decorated == SHORT_TEXT
    assert tags_used == []
    assert tier == "fast"


# ── Tier semantics ────────────────────────────────────────────────────


def test_tier_emotive_iff_tags_inserted() -> None:
    # Run with a wide allowed_tags + emotion override. Should always
    # land at least one tag → tier=emotive.
    for seed in range(20):
        _, tags_used, tier = decorate(
            LONG_TEXT,
            phase="PROBLEM_AWARENESS",
            user_emotion="frustrated",
            personality="sally_emotive",
            allowed_tags=ALL_WARM_TAGS,
            disfluency_density=0.0,
            rng=random.Random(seed),
        )
        if tags_used:
            assert tier == "emotive"
        else:
            assert tier == "fast"


# ── Tag positioning ───────────────────────────────────────────────────


def test_tag_always_at_position_zero() -> None:
    """Tags now go at the START of the response — the emotion is a
    reaction that precedes speech, which sounds more natural."""
    for seed in range(10):
        decorated, tags, tier = decorate(
            LONG_TEXT,
            phase="PROBLEM_AWARENESS",
            user_emotion="frustrated",
            personality="sally_emotive",
            allowed_tags=ALL_WARM_TAGS,
            disfluency_density=0.0,
            rng=random.Random(seed),
        )
        if tags:  # tag was inserted (context signals matched)
            assert decorated.startswith("["), (
                f"seed {seed}: tag should be at start but got: {decorated[:60]!r}"
            )


def test_tags_never_adjacent() -> None:
    # Adjacency check: regex for "[tag1] [tag2]" patterns. Should never
    # appear regardless of seed.
    pattern = re.compile(r"\[[^\]]+\]\s*\[[^\]]+\]")
    for seed in range(50):
        decorated, _, _ = decorate(
            LONG_TEXT,
            phase="PROBLEM_AWARENESS",
            user_emotion="frustrated",
            personality="sally_emotive",
            allowed_tags=ALL_WARM_TAGS,
            disfluency_density=0.0,
            rng=random.Random(seed),
        )
        assert pattern.search(decorated) is None, (
            f"seed {seed}: adjacent tags in: {decorated!r}"
        )


# ── Disfluency density approximation ──────────────────────────────────


def test_disfluency_density_approximates_target() -> None:
    """Verify per-sentence disfluency rate over many seeds matches
    the theoretical post-gating expectation.

    LONG_TEXT has 3 sentences; first is never decorated. Among the 2
    eligible sentences, the never-two-in-a-row rule means after a
    disfluency lands on sentence 2, sentence 3 is forced to skip:

        E[disfluent on s2] = density
        E[disfluent on s3] = density * P(s2 skipped) = density * (1 - density)
        Effective per-sentence = (density + density*(1-density)) / 2
                               = density * (2 - density) / 2

    With density 0.45 → effective ≈ 0.349. We assert observed is
    within ±0.03 of that theoretical rate.
    """
    target = 0.45
    # Theoretical effective rate given the never-two-in-a-row gating
    # over 2 eligible sentences.
    theoretical_effective = target * (2.0 - target) / 2.0  # ≈ 0.349
    decorated_sentence_count = 0
    eligible_sentence_count = 0
    starter_prefixes = tuple(p.lower() for p in DISFLUENCY_PHRASES["warm_starter"])
    thinker_prefixes = tuple(p.lower() for p in DISFLUENCY_PHRASES["warm_thinker"])
    ack_prefixes = tuple(p.lower() for p in DISFLUENCY_PHRASES["warm_acknowledger"])
    all_prefixes = starter_prefixes + thinker_prefixes + ack_prefixes

    for seed in range(1000):
        decorated, _, _ = decorate(
            LONG_TEXT,
            phase="CONNECTION",
            user_emotion=None,
            personality="sally_emotive",
            allowed_tags=[],  # tags off, isolate disfluency behavior
            disfluency_density=target,
            rng=random.Random(seed),
        )
        # LONG_TEXT has 3 sentences. Skip first → 2 eligible. The third
        # (Q-mark "Can you walk me through what a typical morning looks
        # like for you?") has 14 words so passes the >=5 word filter.
        # The second has 11 words so also eligible.
        eligible_sentence_count += 2

        # Count sentences that start with a disfluency prefix.
        # Sentence boundaries: split on `(?<=[.!?])\s+`.
        sentences = re.split(r"(?<=[.!?])\s+", decorated)
        for sent in sentences[1:]:  # skip first sentence
            if sent.lower().startswith(all_prefixes):
                decorated_sentence_count += 1

    observed_density = decorated_sentence_count / eligible_sentence_count
    assert abs(observed_density - theoretical_effective) < 0.03, (
        f"observed {observed_density:.3f} too far from "
        f"theoretical {theoretical_effective:.3f} (raw density {target})"
    )


# ── Tag pool sanity ───────────────────────────────────────────────────


def test_terminated_phase_has_empty_pool() -> None:
    # TERMINATED is the post-end state; we shouldn't decorate at all.
    _, tags_used, tier = decorate(
        LONG_TEXT,
        phase="TERMINATED",
        user_emotion=None,
        personality="sally_emotive",
        allowed_tags=ALL_WARM_TAGS,
        disfluency_density=0.0,
        rng=random.Random(1),
    )
    assert tags_used == []
    assert tier == "fast"


def test_unknown_phase_falls_back_gracefully() -> None:
    # If a typo or new phase shows up, decorate shouldn't crash.
    decorated, tags_used, tier = decorate(
        LONG_TEXT,
        phase="MYSTERY_PHASE",
        user_emotion=None,
        personality="sally_emotive",
        allowed_tags=ALL_WARM_TAGS,
        disfluency_density=0.0,
        rng=random.Random(1),
    )
    assert tags_used == []
    assert tier == "fast"
    assert decorated == LONG_TEXT  # no decoration applied


# ── Personality arg accepted ──────────────────────────────────────────


def test_personality_arg_accepted_but_advisory() -> None:
    # Two personality strings should produce identical output for now.
    rng1 = random.Random(7)
    rng2 = random.Random(7)
    out1 = decorate(
        LONG_TEXT,
        phase="CONNECTION",
        user_emotion=None,
        personality="sally_emotive",
        allowed_tags=ALL_WARM_TAGS,
        disfluency_density=0.45,
        rng=rng1,
    )
    out2 = decorate(
        LONG_TEXT,
        phase="CONNECTION",
        user_emotion=None,
        personality="sally_emotive_v2",  # hypothetical future variant
        allowed_tags=ALL_WARM_TAGS,
        disfluency_density=0.45,
        rng=rng2,
    )
    assert out1 == out2
