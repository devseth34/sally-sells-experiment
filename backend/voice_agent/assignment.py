"""Personality assignment for voice calls.

Picks one of the three locked personalities (`sally_warm`, `sally_confident`,
`sally_direct`) at the start of each voice call. The picked personality
drives both the TTS voice (via personalities.PERSONALITIES) and the NEPQ
engine arm (via personalities.PERSONALITIES[key]["engine_arm"]).

Day 4 status — uniform random:
    The frozen chat product assigns arms via balanced-random over the last
    7 days of session records (main.py:660-687), using a DB query to count
    sessions per arm and picking the least-used. That logic can't be
    reused from here without (a) pulling in the chat DB session (coupling)
    or (b) duplicating the query code against the frozen models. Both are
    premature before voice calls actually persist to the DB — and DB
    persistence is Day 5 scope, not Day 4.

    So Day 4 uses uniform random across the three arms. Over enough calls
    the distribution evens out; the CDS calibration sample (≥40 sessions,
    Addendum §B11) is large enough that a small imbalance won't bias the
    result. When Day 5 adds session persistence, swap this for balanced
    allocation against the voice-specific session count.

Stratification hook:
    `stratum` is accepted but unused today. The eventual design (§B11) is
    stratified random within pre_conviction_enum, but pre_conviction isn't
    known at voice-call dispatch time unless the caller embeds it in the
    LiveKit room metadata. Keeping the parameter in the signature so the
    Day 5 swap doesn't touch callers.

Seeded RNG:
    `rng` defaults to the module-level Random() so production picks are
    non-deterministic. Tests pass a seeded Random() for reproducibility.
"""

from __future__ import annotations

import logging
import random
from typing import Final

from backend.voice_agent.personalities import PERSONALITIES

logger = logging.getLogger("sally-voice-assignment")

_ARMS: Final[tuple[str, ...]] = tuple(PERSONALITIES.keys())
_DEFAULT_RNG = random.Random()


def assign_personality(
    stratum: str | None = None,
    *,
    rng: random.Random | None = None,
) -> str:
    """Return one of `sally_warm` / `sally_confident` / `sally_direct`.

    `stratum` is accepted for forward-compatibility with §B11 stratified
    random (pre_conviction_enum) but ignored today — see module docstring.
    `rng` is injectable for deterministic tests; defaults to a module-
    level Random() initialized at import with the OS entropy source.
    """
    picker = rng if rng is not None else _DEFAULT_RNG
    choice = picker.choice(_ARMS)
    logger.info(
        "Personality assigned",
        extra={
            "personality": choice,
            "engine_arm": PERSONALITIES[choice]["engine_arm"],
            "stratum": stratum,
            # Mark Day 4 draws so Day 5 can filter them out of CDS math
            # if the uniform-vs-balanced distinction turns out to matter.
            "assignment_method": "uniform_random_day4",
        },
    )
    return choice
