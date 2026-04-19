"""TTS pronunciation lexicon + preprocessor.

Runs between Layer 3 sentence output and the TTS request. Without this,
Cartesia/ElevenLabs mispronounce brand/jargon terms on the first call —
painful and irreversible (Addendum §B1).

Each TTS provider has its own phoneme flavor:
    - Cartesia:   inline <phoneme alphabet="ipa" ph="..."> tags
    - ElevenLabs: SSML <phoneme> tags; also supports a voice-level
                  pronunciation dictionary via API

Verify every entry during Day 2 by rendering sample audio per voice
and listening.

Number handling: all dollar figures, percentages, and dates get
expanded to words (e.g. "$10,000" -> "ten thousand dollars") BEFORE
the phoneme substitution pass.
"""

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


def preprocess(text: str, tts_provider: str) -> str:
    """Return `text` with pronunciation substitutions applied.

    TODO (Day 2):
        - Apply LEXICON replacements (whole-word / word-boundary match).
        - Expand number-like tokens ($X, X%, dates) to words before
          lexicon pass.
        - Wrap substitutions in provider-appropriate tags:
            - cartesia:    <phoneme alphabet="ipa" ph="...">
            - elevenlabs:  SSML <phoneme>
        - Add a unit test that renders each LEXICON key and asserts
          the expected output string per provider.
    """
    raise NotImplementedError("Preprocessor not yet implemented.")
