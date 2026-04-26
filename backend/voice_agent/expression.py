"""Expression layer: decorate engine response with audio tags + disfluencies.

Pure-function module. Runs only for `sally_emotive` (the runner skips
the call entirely for the other 3 arms). Output is a tuple of:
    (decorated_text, tags_used, recommended_tier)

The recommended tier drives the runner's TTS routing: "emotive" iff at
least one tag was inserted; "fast" otherwise. Routing decoration through
v3 only when v3 has something to render keeps the latency cost bounded
to genuinely emotive turns.

Why pure / no LLM:
    Tags follow a phase + emotion lookup table. Disfluencies are inserted
    by per-sentence probability. Both are deterministic given a seeded
    `rng`, so tests can pin behavior. No network, no model calls — runs
    in microseconds, can be inlined into the runner's hot path without
    blocking `_speak()`.

Insertion rules (spec §6):
    Tags:
      • Never at position 0 (sounds theatrical).
      • Never adjacent (no `[chuckles] [hmm]`).
      • Skip entirely if response < 30 chars.
      • First tag: after the first sentence boundary.
      • Second tag (30% probability): before the LAST sentence.
    Disfluencies:
      • Per-sentence prefix at `disfluency_density` probability.
      • Skip the first sentence (sets the response's tone cleanly).
      • Skip sentences shorter than 5 words.
      • Never two in a row.
      • 60% starter ("yeah, "), 20% thinker ("um, "), 20%
        acknowledger ("right, ").
"""

from __future__ import annotations

import random
import re
from typing import Literal, Optional, Sequence

# Tag pools by NEPQ phase. Curated for sally_warm/empathy_plus voice
# character (Jessica). Other personalities would need their own pools
# from their own auditions; today only sally_emotive uses this module.
PHASE_TAG_POOLS: dict[str, list[str]] = {
    # Valid eleven_v3 audio tags per ElevenLabs docs. [chuckles] and
    # [hmm] are NOT valid — model reads them literally. Use [laughs],
    # [sighs], [exhales] which v3 renders as actual sounds.
    "CONNECTION":         ["[laughs]", "[exhales]"],
    "SITUATION":          ["[exhales]", "[sighs]"],
    "PROBLEM_AWARENESS":  ["[sighs]", "[exhales]"],
    "SOLUTION_AWARENESS": ["[exhales]"],
    "CONSEQUENCE":        ["[sighs]", "[exhales]"],
    "OWNERSHIP":          ["[sighs]"],
    "COMMITMENT":         ["[laughs]"],
    "TERMINATED":         [],
}

# Emotion overrides using only valid eleven_v3 tags.
EMOTION_TAG_OVERRIDES: dict[str, list[str]] = {
    "frustrat":  ["[sighs]", "[exhales]"],
    "joking":    ["[laughs]"],
    "playful":   ["[laughs]"],
    "sad":       ["[sighs]", "[exhales]"],
    "excited":   ["[laughs]"],
    "confused":  ["[exhales]"],
    "skeptical": ["[sighs]"],
    "defensive": ["[sighs]", "[exhales]"],
}

# Disfluency prefixes. Categories tagged so density routing can pick
# proportionally — starters dominate (sound most natural at sentence
# heads), thinkers and acknowledgers add variety.
DISFLUENCY_PHRASES: dict[str, list[str]] = {
    "warm_starter":      ["yeah, ", "so, ", "I mean, ", "you know, "],
    "warm_thinker":      ["um, ", "uh, ", "hmm, "],
    "warm_acknowledger": ["right, ", "okay, ", "got it, "],
}

# Probability split inside DISFLUENCY_PHRASES (must sum to 1.0).
_DISFLUENCY_CATEGORY_WEIGHTS: dict[str, float] = {
    "warm_starter":      0.60,
    "warm_thinker":      0.20,
    "warm_acknowledger": 0.20,
}

# Minimum response length below which we skip ALL decoration.
_MIN_RESPONSE_CHARS = 30

# Keywords in the RESPONSE TEXT that signal a tag fits contextually.
# If none of these appear, we skip the tag even if emotion warrants it —
# prevents a laugh appearing on "What's your role there?" just because
# the user sounded playful.
_TAG_CONTEXT_SIGNALS: dict[str, list[str]] = {
    "[laughs]":  ["haha", "funny", "laugh", "yeah right", "fair", "ironic",
                  "actually", "wild", "crazy", "interesting", "good point",
                  "that's", "wow", "honestly", "kind of", "sort of"],
    "[sighs]":   ["tough", "hard", "frustrat", "stuck", "understand", "hear you",
                  "that's a lot", "weight", "struggle", "difficult", "rough",
                  "real", "honest", "that makes sense", "wow", "yeah"],
    "[exhales]": ["let me", "alright so", "okay so", "right so",
                  "let me think", "let me understand", "makes sense",
                  "that's a lot", "process that"],
}

# Minimum sentence word count for disfluency prefix. Short sentences
# ("Got it.", "Sure.") sound performative with a "yeah, " prepended.
_MIN_SENTENCE_WORDS = 5

# Sentence boundary detector. Matches ., ?, ! followed by whitespace +
# (typically) a capital letter or end-of-string. Conservative — rather
# preserve too few boundaries than split mid-sentence.
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")


def decorate(
    text: str,
    *,
    phase: str,
    user_emotion: Optional[str],
    personality: str,
    allowed_tags: Sequence[str],
    disfluency_density: float,
    rng: Optional[random.Random] = None,
) -> tuple[str, list[str], Literal["fast", "emotive"]]:
    """Decorate `text` with audio tags + disfluencies.

    Returns:
        (decorated_text, tags_used, recommended_tier)

    `tier == "emotive"` iff at least one tag was inserted. Otherwise
    "fast" — disfluencies alone don't justify v3's first-frame cost
    (Flash speaks them just as well, faster).

    `personality` is accepted for forward-compat (e.g., per-personality
    disfluency phrasing) but currently unused — the warm_* phrase
    families work for the only emotive personality (sally_emotive).
    Kept in the signature so adding sally_emotive_v2 doesn't break
    callers.
    """
    del personality  # advisory only, see docstring

    picker = rng if rng is not None else random
    tags_used: list[str] = []

    # Skip ALL decoration on very short responses.
    if len(text or "") < _MIN_RESPONSE_CHARS:
        return text, tags_used, "fast"

    # Step 1: pick the candidate tag pool (emotion override > phase).
    pool = _select_pool(phase, user_emotion)

    # Step 2: intersect with personality's audition-vetted whitelist.
    candidates = [t for t in pool if t in allowed_tags]
    if not candidates:
        decorated = _apply_disfluencies(
            text, disfluency_density=disfluency_density, picker=picker
        )
        return decorated, tags_used, "fast"

    # Step 3: filter candidates by whether the response text signals the
    # tag fits contextually. A laugh on "What's your role there?" is
    # wrong even if the user sounded playful.
    contextual = [t for t in candidates if _tag_fits_response(t, text)]
    if not contextual:
        decorated = _apply_disfluencies(
            text, disfluency_density=disfluency_density, picker=picker
        )
        return decorated, tags_used, "fast"

    # Step 4: pick one tag. One is enough — stacking two tags sounds forced.
    first_tag = picker.choice(contextual)
    tags_used.append(first_tag)

    # Step 5: insert at the START of the response — the emotion is a
    # reaction that precedes speech ("*sighs* Yeah, that's tough..." is
    # more natural than "Yeah, that's tough. *sighs* Walk me through it.").
    decorated_text = f"{first_tag} {text}"

    # Step 6: apply disfluencies. Skip the first sentence since it now
    # starts with a tag — the injector already guards this.
    decorated_text = _apply_disfluencies(
        decorated_text, disfluency_density=disfluency_density, picker=picker
    )

    return decorated_text, tags_used, "emotive"


# ── Internals ─────────────────────────────────────────────────────────


def _select_pool(phase: str, user_emotion: Optional[str]) -> list[str]:
    """Emotion override beats phase. Substring match on emotional_tone
    so multi-word L1 outputs like 'engaged, frustrated' still hit the
    frustrated bucket."""
    if user_emotion:
        normalized = user_emotion.lower()
        for key, override_pool in EMOTION_TAG_OVERRIDES.items():
            if key in normalized:
                return list(override_pool)
    return list(PHASE_TAG_POOLS.get(phase, []))


def _split_sentences(text: str) -> list[str]:
    """Split on sentence boundaries while preserving terminal punctuation.
    Returns a list of sentence strings; empty input yields []."""
    text = (text or "").strip()
    if not text:
        return []
    parts = _SENTENCE_BOUNDARY_RE.split(text)
    return [p for p in parts if p]


def _tag_fits_response(tag: str, response_text: str) -> bool:
    """Return True if the response text contains signals that this tag
    is contextually appropriate. Prevents mechanical insertion on turns
    where the emotion makes no narrative sense (e.g. a laugh on a bare
    question, or a sigh on an upbeat closing line).

    Falls back to True for tags not in the signal table — better to allow
    than to always block unknown tags.
    """
    signals = _TAG_CONTEXT_SIGNALS.get(tag)
    if signals is None:
        return True  # unknown tag: allow
    text_lower = response_text.lower()
    return any(s in text_lower for s in signals)


def _apply_disfluencies(
    text: str,
    *,
    disfluency_density: float,
    picker: random.Random,
) -> str:
    """Per-sentence disfluency prefix injection. Skips first sentence,
    short sentences, and sentences that already start with an audio tag.
    Never two in a row."""
    if disfluency_density <= 0.0:
        return text
    sentences = _split_sentences(text)
    if len(sentences) < 2:
        return text

    out: list[str] = [sentences[0]]
    last_was_disfluent = False

    for sentence in sentences[1:]:
        if last_was_disfluent:
            out.append(sentence)
            last_was_disfluent = False
            continue
        # Skip if too short (word count, not char count — "Got it." is 2 words).
        if len(sentence.split()) < _MIN_SENTENCE_WORDS:
            out.append(sentence)
            last_was_disfluent = False
            continue
        # Skip if sentence starts with an audio tag — we don't want
        # `[chuckles] yeah, ...`, that's clumsy.
        if sentence.lstrip().startswith("["):
            out.append(sentence)
            last_was_disfluent = False
            continue
        if picker.random() >= disfluency_density:
            out.append(sentence)
            last_was_disfluent = False
            continue
        # Pick category by weighted roll.
        category = _pick_category(picker)
        prefix = picker.choice(DISFLUENCY_PHRASES[category])
        # Lowercase first letter of the original sentence so the
        # prefix flows: "yeah, that's tough" not "yeah, That's tough".
        sentence_modified = _lowercase_first_letter(sentence)
        out.append(f"{prefix}{sentence_modified}")
        last_was_disfluent = True

    return " ".join(out)


def _pick_category(picker: random.Random) -> str:
    """Sample a disfluency category by weight. Returns one of the keys
    in _DISFLUENCY_CATEGORY_WEIGHTS."""
    roll = picker.random()
    cumulative = 0.0
    for category, weight in _DISFLUENCY_CATEGORY_WEIGHTS.items():
        cumulative += weight
        if roll < cumulative:
            return category
    # Fallback (covers floating-point edge case at exactly 1.0).
    return "warm_starter"


def _lowercase_first_letter(sentence: str) -> str:
    """Lowercase only the first letter; preserve everything else.
    Skips proper nouns and quoted starts (anything not [a-z]/[A-Z] at
    position 0 stays as-is)."""
    if not sentence:
        return sentence
    first = sentence[0]
    if not first.isalpha():
        return sentence
    # Heuristic: don't lowercase "I" (single uppercase I followed by
    # space) — it's a pronoun, not sentence-initial capitalization.
    if sentence.startswith("I ") or sentence == "I":
        return sentence
    return first.lower() + sentence[1:]
