"""Backchannel injector: scripted "mhm/yeah/got it" while Sally thinks.

Purpose:
    1. Mask 500-800ms of perceived latency while Layer 1 runs
       (Addendum §A1 parallelization strategy).
    2. Sound engaged during long user monologues without stepping on
       the speaker.

Firing a backchannel at EVERY end-of-turn is the textbook "obvious AI"
signature — so this module gates them behind trigger rules (§B6).

Rule summary:
    NEVER when:
        - fast-path match (trivial utterance)
        - user utterance duration < 1s
        - last backchannel fired < 8s ago
        - phase is CONNECTION (performative-sounding this early)
    ALWAYS when:
        - user utterance >= 6s AND phase in {PROBLEM_AWARENESS,
          CONSEQUENCE, OWNERSHIP}
        - interim ASR contains emotional markers
    PROBABILISTIC (50%):
        - user utterance 3-6s in any phase past CONNECTION

Per-personality density multipliers (applied to the probabilistic
bucket; the ALWAYS bucket is non-negotiable):
    warm:      100%  (fire every probabilistic opportunity)
    confident:  30%
    direct:     15%  (only the ALWAYS set)

Variety: track last 2 used per session; never repeat consecutively.
"""

from __future__ import annotations

import re

BACKCHANNELS: dict[str, list[str]] = {
    "warm":      ["mhm", "yeah", "uh-huh", "okay", "got it", "right", "I hear you"],
    "confident": ["mhm", "got it", "okay", "right"],
    "direct":    ["mhm", "okay", "right"],
}

# Phases where "ALWAYS" backchannel on long user turns.
ALWAYS_PHASES: set[str] = {"PROBLEM_AWARENESS", "CONSEQUENCE", "OWNERSHIP"}

# Emotional-marker regex — if interim ASR contains any of these
# stems, jump straight to an ALWAYS fire regardless of duration.
EMOTION_MARKER_RE = re.compile(
    r"(frustrat|stuck|tired|overwhelm|worr|stress|anxio)", re.IGNORECASE
)

# Probabilistic multiplier per personality (applied to the 3-6s bucket).
PROBABILISTIC_MULTIPLIER: dict[str, float] = {
    "warm":      1.00,
    "confident": 0.30,
    "direct":    0.00,  # direct skips the probabilistic bucket entirely
}

# Minimum seconds between consecutive backchannel fires per session.
MIN_INTERVAL_SEC = 8.0


def should_fire_backchannel(
    *,
    personality: str,
    phase: str,
    user_utterance_sec: float,
    interim_transcript: str,
    seconds_since_last: float,
    is_fast_path_match: bool,
) -> bool:
    """Return True if a backchannel should fire at the current EOT.

    Caller is responsible for: (1) actually picking the phrase via
    `pick_backchannel()`, (2) resetting the "seconds_since_last" clock,
    (3) scheduling the TTS within ~100ms of EOT.

    TODO (Day 2):
        - Plumb session-level state (last_used list, last_fired_at)
          from sally_voice_runner.py rather than the caller.
        - Wire into streaming_validator.py's sentence-flush loop so a
          backchannel can preempt Sally's first sentence if Layer 3
          is slow.
    """
    if is_fast_path_match:
        return False
    if user_utterance_sec < 1.0:
        return False
    if seconds_since_last < MIN_INTERVAL_SEC:
        return False
    if phase == "CONNECTION":
        return False

    # ALWAYS bucket.
    if phase in ALWAYS_PHASES and user_utterance_sec >= 6.0:
        return True
    if EMOTION_MARKER_RE.search(interim_transcript or ""):
        return True

    # Probabilistic bucket (3-6s).
    if 3.0 <= user_utterance_sec < 6.0:
        import random
        mult = PROBABILISTIC_MULTIPLIER.get(personality, 0.0)
        return random.random() < mult

    return False


def pick_backchannel(personality: str, recently_used: list[str]) -> str:
    """Return a backchannel phrase, avoiding the last 2 used.

    TODO (Day 2):
        - Promote `recently_used` tracking to session state in
          sally_voice_runner.py.
        - If all candidates are in recently_used, fall back to the
          least-recent one (don't lock up).
    """
    raise NotImplementedError("Picker not yet implemented.")
