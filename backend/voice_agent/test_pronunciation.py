"""Pronunciation preprocessor tests.

Run with: source venv/bin/activate && python -m pytest backend/voice_agent/test_pronunciation.py -v

These are unit tests, not TTS render tests — they verify the text
substitution layer only. Listening-verification of actual TTS output
lives in audition.py (Day 2B).
"""

from __future__ import annotations

import pytest

from backend.voice_agent.pronunciation import LEXICON, preprocess


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Landmine case that triggered the whole module.
        ("Talk to Nik Shah", "Talk to Nick Shah"),
        # Acronyms spelled letter-by-letter.
        ("The NEPQ arm", "The N-E-P-Q arm"),
        ("CDS goes up", "C-D-S goes up"),
        ("asked about AI", "asked about A-I"),
        # Brand + number forms.
        ("100x guarantee", "one hundred X guarantee"),
        # Dollar figure with punctuation-adjacent.
        ("pays $10,000 back", "pays ten thousand dollars back"),
        # Ampersand hyphen landmine ("pandle" on Flash v2.5 with hyphens).
        ("P&L line", "P and L line"),
        # TidyCal scheduler reference.
        ("book on TidyCal", "book on tidy cal"),
        # Layer references.
        ("Layer 2 handles that", "layer two handles that"),
    ],
)
def test_lexicon_substitutions(raw: str, expected: str) -> None:
    assert preprocess(raw, "cartesia") == expected


def test_idempotent_when_already_substituted() -> None:
    """Running preprocess twice should be a no-op on already-substituted text.

    Guards against regressions where "P and L" → "P and L" identity
    entry gets accidentally removed, which would let "P&L" → "P and L"
    → further-mangled on a second pass.
    """
    once = preprocess("We checked the P&L on 100x", "cartesia")
    twice = preprocess(once, "cartesia")
    assert once == twice


def test_longest_key_wins_over_substring() -> None:
    """"Nik Shah" must match before any future single-word "Nik" entry.

    Also verifies the longest-first ordering isn't broken by the next
    person who adds a LEXICON key.
    """
    result = preprocess("Call Nik Shah tomorrow", "cartesia")
    assert result == "Call Nick Shah tomorrow"
    # Ensure "Shah" alone (not in LEXICON) was NOT re-processed into
    # something unexpected — it should pass through untouched.
    assert preprocess("Mr. Shah is ready", "cartesia") == "Mr. Shah is ready"


def test_no_match_inside_other_words() -> None:
    """Word-boundary guard prevents matches inside longer tokens.

    "AI" inside "paid" / "said" must NOT be replaced.
    """
    assert preprocess("he paid the bill", "cartesia") == "he paid the bill"
    assert preprocess("she said so", "cartesia") == "she said so"


def test_case_insensitive_match() -> None:
    """Deepgram transcript casing varies by accent and context."""
    assert "N-E-P-Q" in preprocess("talk about nepq arms", "cartesia")
    assert "Nick Shah" in preprocess("nik shah is the founder", "cartesia")


def test_provider_arg_accepted_but_currently_advisory() -> None:
    """tts_provider is declared but shouldn't change output today."""
    sample = "Nik Shah built 100x"
    assert preprocess(sample, "cartesia") == preprocess(sample, "elevenlabs")


def test_every_lexicon_key_produces_its_mapped_value() -> None:
    """Sanity check: each LEXICON entry is reachable via preprocess()."""
    for key, expected in LEXICON.items():
        out = preprocess(key, "cartesia")
        # Identity entries (P and L -> P and L) are trivially satisfied.
        assert out == expected, f"LEXICON[{key!r}] -> {out!r}, expected {expected!r}"
