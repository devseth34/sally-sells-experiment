"""Backchannel injector: scripted "mhm/yeah/got it" while Sally thinks.

Purpose:
    Mask the ~3-5s engine latency between the user finishing a turn and
    Sally's TTS starting. A short filler ("mhm", "gotcha") played during
    the Layer 1+3 wait makes the conversation feel engaged rather than
    dead. Biggest perceived-UX win on top of the 2.5-flash-lite model
    swap (Day 5 brief).

Day 5 scope — ONE trigger, mid-engine:
    The runner schedules a backchannel task at the start of every
    on_user_turn, which sleeps ~500ms and then — if the engine hasn't
    yet returned — fires a filler through the same TTS + audio source
    as Sally's real response. An asyncio.Lock serializes audio emission
    so the filler never collides with Sally's eventual TTS output. The
    task is cancelled if the engine returns before the sleep elapses,
    so fast turns skip the filler entirely.

    EOT-triggered semantic backchannels (long user utterance → fire
    "I hear you", emotional-marker detection, etc. — Addendum §B6's
    richer ruleset) are Day 6+ scope. The scaffold's
    `should_fire_backchannel` function captures that design for the
    future; today the runner uses a narrower gating set below.

Gating for the mid-engine trigger:
    NEVER fire if:
        - phase is CONNECTION (too performative during the opener)
        - fewer than MIN_INTERVAL_SEC since last backchannel (avoid
          "mm-hmm every turn" robotic pattern)
        - personality density multiplier rolls False
    Then: pick a phrase that wasn't among the last 2 used this call.

Per-personality density multipliers (applied to every eligible turn):
    warm:       1.00   (fire every eligible turn — dense warmth)
    confident:  0.30   (sparse — professional cadence)
    direct:     0.00   (never — direct personality = tight, no filler)

The multipliers track personalities.py's `backchannel_density` field
(high/medium/low), but numerically so the trigger is a clean
`random() < mult` check.
"""

from __future__ import annotations

import random
import re
from typing import Sequence

BACKCHANNELS: dict[str, list[str]] = {
    "warm":      ["mhm", "yeah", "uh-huh", "okay", "got it", "right", "I hear you"],
    "confident": ["mhm", "got it", "okay", "right"],
    "direct":    ["mhm", "okay", "right"],
}

ALWAYS_PHASES: set[str] = {"PROBLEM_AWARENESS", "CONSEQUENCE", "OWNERSHIP"}

EMOTION_MARKER_RE = re.compile(
    r"(frustrat|stuck|tired|overwhelm|worr|stress|anxio)", re.IGNORECASE
)

PROBABILISTIC_MULTIPLIER: dict[str, float] = {
    "warm":      1.00,
    "confident": 0.30,
    "direct":    0.00,
}

MIN_INTERVAL_SEC = 8.0


def short_key(personality: str) -> str:
    """Map `sally_warm` -> `warm` etc. so backchannel tables can stay
    keyed by bare personality descriptors (matches the audition +
    scoring modules, which predate the `sally_*` naming)."""
    return personality.removeprefix("sally_")


def pick_backchannel(
    personality: str,
    recently_used: Sequence[str],
    *,
    rng: random.Random | None = None,
) -> str:
    """Return a backchannel phrase for `personality`, avoiding the last
    2 used this call.

    If every candidate is in `recently_used` (possible for `direct` with
    only 3 phrases), falls back to the first candidate that isn't the
    IMMEDIATELY preceding one — better to repeat an older phrase than
    stutter the exact same filler back to back.

    `rng` is injectable for deterministic tests; defaults to module
    `random` for production (SystemRandom is overkill here — filler
    variety doesn't need cryptographic quality).
    """
    key = short_key(personality)
    pool = list(BACKCHANNELS.get(key, []))
    if not pool:
        raise ValueError(f"No backchannels configured for personality {personality!r}")

    picker = rng if rng is not None else random
    avoid = set(recently_used[-2:]) if recently_used else set()
    candidates = [p for p in pool if p not in avoid]

    if candidates:
        return picker.choice(candidates)

    # Pool exhausted by recency; fall back to any phrase that isn't the
    # single most recent one (so we don't repeat twice in a row).
    most_recent = recently_used[-1] if recently_used else None
    fallback_pool = [p for p in pool if p != most_recent] or pool
    return picker.choice(fallback_pool)


def should_fire_mid_engine(
    *,
    personality: str,
    phase: str,
    seconds_since_last: float,
    rng: random.Random | None = None,
) -> bool:
    """Decide whether to fire a mid-engine backchannel on this turn.

    Narrower than `should_fire_backchannel` below — Day 5 uses this one.
    Gating order mirrors the docstring: phase → interval → density roll.
    """
    if phase == "CONNECTION":
        return False
    if seconds_since_last < MIN_INTERVAL_SEC:
        return False
    key = short_key(personality)
    mult = PROBABILISTIC_MULTIPLIER.get(key, 0.0)
    if mult <= 0.0:
        return False
    if mult >= 1.0:
        return True
    picker = rng if rng is not None else random
    return picker.random() < mult


def should_fire_backchannel(
    *,
    personality: str,
    phase: str,
    user_utterance_sec: float,
    interim_transcript: str,
    seconds_since_last: float,
    is_fast_path_match: bool,
    rng: random.Random | None = None,
) -> bool:
    """Full scaffold-design trigger (EOT-semantic). Day 6+ scope.

    Kept callable and tested so the richer EOT-based trigger can slot in
    without re-deriving the rules. Not wired into the runner today.
    """
    if is_fast_path_match:
        return False
    if user_utterance_sec < 1.0:
        return False
    if seconds_since_last < MIN_INTERVAL_SEC:
        return False
    if phase == "CONNECTION":
        return False

    if phase in ALWAYS_PHASES and user_utterance_sec >= 6.0:
        return True
    if EMOTION_MARKER_RE.search(interim_transcript or ""):
        return True

    if 3.0 <= user_utterance_sec < 6.0:
        key = short_key(personality)
        mult = PROBABILISTIC_MULTIPLIER.get(key, 0.0)
        picker = rng if rng is not None else random
        return picker.random() < mult

    return False
