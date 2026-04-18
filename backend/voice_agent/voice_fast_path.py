"""Trivial-utterance shortcut: skip Layer 1 for greetings/yes/no/bye.

Voice has many more single-word turns than chat (especially in
CONNECTION and SITUATION phases — ~30% of turns). Running the full
Gemini Flash comprehension pass on "yeah" or "mhm" costs 700-1000ms
for no semantic gain.

On match: skip Layer 1, synthesize a stub `ComprehensionOutput`, pass
directly to Layer 2 with the intent tag. Layer 2 / Layer 3 remain
untouched (brain is frozen).

Filler intent ("uh", "um", "hmm", "let me think") is special: treat
as the user still holding the turn — do not respond at all; reset the
EOT timer and wait for more.

All regexes are whole-string, case-insensitive.
"""

from __future__ import annotations

import re

# Intent -> (compiled regex, Layer 2 action hint).
# Layer 2 action hints are interpretive guidance for the voice runner
# to build the ComprehensionOutput stub; they do not change Layer 2
# semantics.
FAST_PATH_PATTERNS: dict[str, dict] = {
    "greeting": {
        "regex":  re.compile(r"^(hi|hey|hello)[\s!.]*$", re.IGNORECASE),
        "action": "STAY",
        "stub":   {"profile_delta": {}, "notes": "phase-appropriate opener"},
    },
    "confirmation": {
        "regex":  re.compile(
            r"^(yes|yeah|yep|sure|ok|okay|right|correct|exactly|absolutely)[\s!.]*$",
            re.IGNORECASE,
        ),
        "action": "STAY",
        "stub":   {"profile_delta": {"agreement": True}},
    },
    "negation": {
        "regex":  re.compile(r"^(no|nope|nah)[\s!.]*$", re.IGNORECASE),
        "action": "STAY",
        "stub":   {"profile_delta": {"disagreement": True}},
    },
    "session_end": {
        "regex":  re.compile(
            r"^(bye|goodbye|talk (to|with) you (later|soon)|gotta go)[\s!.]*$",
            re.IGNORECASE,
        ),
        "action": "END",
        "stub":   {"profile_delta": {}},
    },
    "filler": {
        "regex":  re.compile(
            r"^(uh|um|hmm|mhm|uh-huh|let me think)[\s!.]*$", re.IGNORECASE
        ),
        "action": "STAY",
        "stub":   {"profile_delta": {}, "notes": "user still holding turn; no response"},
    },
}


def match(transcript: str) -> tuple[str, dict] | None:
    """Return (intent, pattern_info) if `transcript` is a fast-path hit.

    TODO (Day 2):
        - Return the full ComprehensionOutput stub (not just pattern_info)
          once the ComprehensionOutput import boundary is clean.
        - Decide whether to count "filler" matches toward turn counters
          (probably no — they're not really turns).
        - Unit tests covering each regex with boundary-case inputs
          ("Yeah!", "YES.", "hey there" <- should NOT match greeting).
    """
    text = (transcript or "").strip()
    if not text:
        return None
    for intent, info in FAST_PATH_PATTERNS.items():
        if info["regex"].match(text):
            return intent, info
    return None
