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


# ── Audio-tag protection (Phase D) ────────────────────────────────────


def test_audio_tag_protected_from_substitution() -> None:
    """Tag content must reach TTS verbatim. AI inside `[curious about
    the AI thing]` must NOT become A-I."""
    assert (
        preprocess("[curious about the AI thing]", "elevenlabs")
        == "[curious about the AI thing]"
    )


def test_audio_tag_outside_substitution_still_works() -> None:
    """LEXICON substitution still applies OUTSIDE tags — the protection
    is scoped, not blanket."""
    result = preprocess("Yeah, AI is hard. [chuckles]", "elevenlabs")
    assert "A-I" in result, f"AI outside tag should be substituted: {result!r}"
    assert "[chuckles]" in result, f"tag should survive verbatim: {result!r}"


def test_multiple_tags_protected() -> None:
    text = "[chuckles] AI is great. [sighs] NEPQ helps."
    result = preprocess(text, "elevenlabs")
    assert "[chuckles]" in result
    assert "[sighs]" in result
    assert "A-I" in result
    assert "N-E-P-Q" in result


def test_lexicon_inside_tag_preserved() -> None:
    """Multi-word LEXICON keys (Nik Shah) must not leak into tag content
    even though the tag itself contains the substring."""
    text = "[hesitant about the Nik Shah opportunity]"
    assert preprocess(text, "elevenlabs") == text


def test_tag_with_brackets_only() -> None:
    # Common short tags. No internal LEXICON keys here.
    assert preprocess("[chuckles]", "elevenlabs") == "[chuckles]"
    assert preprocess("[empathetic]", "elevenlabs") == "[empathetic]"
    assert preprocess("[warm chuckle]", "elevenlabs") == "[warm chuckle]"


def test_tag_protection_does_not_leak_sentinel() -> None:
    """The NUL-byte sentinel used internally must never appear in the
    final output. If restoration is broken, the sentinel leaks."""
    out = preprocess("[chuckles] talking about NEPQ", "elevenlabs")
    assert "\x00" not in out, f"sentinel leaked into output: {out!r}"
    assert "TAG" not in out or "[" in out  # only the original tag should contain "TAG"


def test_tag_protection_idempotent() -> None:
    """Decorated text should remain stable across multiple preprocess
    calls — a common scenario if the runner accidentally re-preprocesses
    or a test runs the function twice."""
    once = preprocess("[chuckles] AI is hard", "elevenlabs")
    twice = preprocess(once, "elevenlabs")
    assert once == twice


# ── Phase D: SSML break / ellipsis / em-dash protection ──────────────


def test_ssml_break_half_second_preserved() -> None:
    text = 'Let me ask you something <break time="0.5s"/>'
    out = preprocess(text, "elevenlabs")
    assert '<break time="0.5s"/>' in out


def test_ssml_break_one_second_preserved() -> None:
    text = 'Take a moment <break time="1.0s"/> and consider this.'
    out = preprocess(text, "elevenlabs")
    assert '<break time="1.0s"/>' in out


def test_ellipsis_preserved() -> None:
    text = "I hear you... that sounds tough."
    out = preprocess(text, "elevenlabs")
    assert "..." in out


def test_em_dash_preserved() -> None:
    text = "I hear you — that sounds really tough."
    out = preprocess(text, "elevenlabs")
    assert "—" in out


def test_lexicon_applies_adjacent_to_break() -> None:
    """A <break/> next to a LEXICON key should NOT prevent substitution
    of the key. 'Nik Shah' → 'Nick Shah' must still happen."""
    text = 'Hi Nik Shah <break time="0.5s"/> let me ask about NEPQ.'
    out = preprocess(text, "elevenlabs")
    assert "Nick Shah" in out
    assert "N-E-P-Q" in out
    assert '<break time="0.5s"/>' in out


def test_em_dash_does_not_block_lexicon_on_either_side() -> None:
    """Em-dash adjacency: 'Nik Shah—NEPQ stuff' should still get both
    LEXICON substitutions (em-dash counts as non-word boundary)."""
    text = "Nik Shah—NEPQ is the framework"
    out = preprocess(text, "elevenlabs")
    assert "Nick Shah" in out
    assert "N-E-P-Q" in out
    assert "—" in out


def test_caps_word_passes_through() -> None:
    """CAPS for emphasis is licensed by the director prompt. Lexicon
    substitution is case-insensitive but only on whole-word matches —
    an emphasized 'REALLY' should stay capitalized; AI inside the same
    sentence should still substitute."""
    text = "That's REALLY important AI work"
    out = preprocess(text, "elevenlabs")
    assert "REALLY" in out
    assert "A-I" in out


def test_multiple_decoration_types_preserved_together() -> None:
    """Mix of audio tag + break + ellipsis in one response — all four
    should survive together, with LEXICON applying to non-protected text."""
    text = '[sighs] I hear you... <break time="0.5s"/> NEPQ helps with this — really.'
    out = preprocess(text, "elevenlabs")
    assert "[sighs]" in out
    assert "..." in out
    assert '<break time="0.5s"/>' in out
    assert "—" in out
    assert "N-E-P-Q" in out


def test_protect_re_no_sentinel_leak() -> None:
    """All four decoration types together — sentinel must never leak."""
    text = '[sighs] yes... <break time="1.0s"/> tell me more — please.'
    out = preprocess(text, "elevenlabs")
    assert "\x00" not in out
