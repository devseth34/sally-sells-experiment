"""TTS pronunciation lexicon + preprocessor.

Runs between Layer 3 sentence output and the TTS request. Without this,
Cartesia/ElevenLabs mispronounce brand/jargon terms on the first call —
painful and irreversible (Addendum §B1).

Each TTS provider has its own phoneme flavor:
    - Cartesia:   inline <phoneme alphabet="ipa" ph="..."> tags
    - ElevenLabs: SSML <phoneme> tags; also supports a voice-level
                  pronunciation dictionary via API

Day 3 status: lexicon substitution only. Day 2B smoke confirmed that
"Shah" and every other LEXICON key render cleanly on both providers
without phoneme tags, so the tts_provider arg is currently advisory.
Kept in the signature so we can escalate to provider-specific phoneme
wrapping per-entry without a caller API change if drift reappears on a
provider refresh.

Number / date / percentage expansion is NOT implemented here yet —
parrot-back (Day 3) only surfaces what the user says, and the frozen
SallyEngine outputs already read dollar figures as words (verified in
app/persona_config.py). Revisit if Day 4+ engine output surfaces raw
"$10,000" / "12%" / "2026-04-19" forms into TTS.
"""

from __future__ import annotations

import re

# Initial lexicon — confirm each entry with Nik before shipping.
# Shah pronunciation: LOCKED as /ʃɑː/ ("shah", rhymes with "spa"),
# per Nik 2026-04-19. "Shah" as written should hit /ʃɑː/ cleanly on
# both Cartesia Sonic 2 and ElevenLabs Flash v2.5 (common English
# loanword); if Day 2B audition reveals /ʃɔː/ (shaw) or /ʃeɪ/ (shay)
# drift, escalate to provider phoneme tags:
#     cartesia:   <phoneme alphabet="ipa" ph="ʃɑː">Shah</phoneme>
#     elevenlabs: <phoneme alphabet="ipa" ph="ʃɑː">Shah</phoneme>
# "Nik" -> "Nick" is a separate fix (prevents "Nike").
LEXICON: dict[str, str] = {
    "Nik Shah":     "Nick Shah",
    "NEPQ":         "N-E-P-Q",
    "CDS":          "C-D-S",
    "100x":         "one hundred X",
    "AI":           "A-I",
    "$10,000":      "ten thousand dollars",
    "$5M":          "five million dollars",
    "TidyCal":      "tidy cal",
    "Sally":        "Sally",
    "Layer 1":      "layer one",
    "Layer 2":      "layer two",
    "Layer 3":      "layer three",
    "ASR":          "A-S-R",
    "TTS":          "T-T-S",
    "SMS":          "S-M-S",
    # P&L is read as "pandle" / "panel" on Flash v2.5 in hyphenated form.
    # Plain-space "P and L" hits letter names cleanly on both providers
    # (confirmed Day 2B smoke, Dev, 2026-04-19). If drift reappears in a
    # provider refresh, escalate to explicit phonetic: "pee and ell".
    "P&L":          "P and L",
    "P and L":      "P and L",  # identity keeps already-correct form stable
}


# Longest-first ordering avoids substring collisions: "Nik Shah" must
# match before "Shah" alone, and "P and L" before "P" would if we ever
# added single-letter keys. Built once at import time.
_ORDERED_KEYS: list[str] = sorted(LEXICON.keys(), key=len, reverse=True)

# Word-boundary substitution. We use (?<!\w)/(?!\w) rather than \b
# because \b is undefined around non-word chars like `$` and `&` —
# "$10,000" and "P&L" need the non-word-char prefix/suffix guard. This
# correctly anchors "100x" (no match inside "1100x") and "AI" (no match
# inside "paid"). IGNORECASE because Deepgram transcript casing is not
# reliable across accents and disfluencies.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?<!\w)" + re.escape(k) + r"(?!\w)", re.IGNORECASE), LEXICON[k])
    for k in _ORDERED_KEYS
]


def preprocess(text: str, tts_provider: str) -> str:
    """Return `text` with pronunciation substitutions applied.

    `tts_provider` is accepted for forward-compatibility with per-
    provider phoneme tag wrapping (see module docstring); today it is
    unused because Day 2B smoke confirmed lexicon substitution alone is
    sufficient on both sonic-2 and Flash v2.5.
    """
    del tts_provider  # advisory only — see module docstring
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text
