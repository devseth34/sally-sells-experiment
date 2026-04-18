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

# Initial lexicon — confirm each entry with Stan before shipping.
# Shah pronunciation: unresolved — one of /ʃɑː/ (shah), /ʃɔː/ (shaw),
# or /ʃeɪ/ (shay). Ask and lock before Day 2 audition.
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
