"""Deepgram Nova-3 STT factory.

Exists so parrot.py (Day 3) and sally_voice_runner.py (Day 4) don't
duplicate the STT construction. Nova-3 settings are tuned for a sales
call context: interim results on (we need fast feedback for backchannel
triggers in Day 5), smart_format off (we run our own pronunciation
pass post-ASR, and smart_format would pre-convert "$10,000" into words
before our lexicon sees it). Sample rate 16 kHz matches the LiveKit
audio input default.

Pronunciation landmine terms are passed as Deepgram `keyterms`, which
bias Nova-3 toward recognizing them correctly in the first place (so
"Nik Shah" comes out of ASR as "Nik Shah", not "Nick Sha" or "nickshaw").
Keyterms are ASR-side hints; the downstream pronunciation.LEXICON still
handles TTS-side corrections.

Reference: https://developers.deepgram.com/docs/keyterm
"""

from __future__ import annotations

from livekit.plugins import deepgram

from backend.voice_agent.pronunciation import LEXICON

# Landmine terms biased into Nova-3 recognition. Pulled from the same
# LEXICON that the TTS preprocessor uses — single source of truth.
# Deepgram prefers the canonical written form here, not the phonetic
# hint, so we use the LEXICON keys (not values).
_KEYTERMS: list[str] = list(LEXICON.keys())


def make_stt() -> deepgram.STT:
    """Build a Nova-3 streaming STT instance configured for Sally calls."""
    return deepgram.STT(
        model="nova-3",
        language="en-US",
        interim_results=True,
        # smart_format converts "$10,000" -> "$10,000" (display form) which
        # we don't need; our pronunciation.preprocess() handles TTS-side.
        smart_format=False,
        punctuate=True,
        # Filler words ("um", "uh") kept — Layer 2 disfluency rules in
        # persona_config may use them to detect hesitation.
        filler_words=True,
        # 25 ms VAD endpointing matches Deepgram's recommended default
        # for low-latency conversational agents. Higher values add lag
        # to end-of-utterance detection (see latency budget in CLAUDE.md).
        endpointing_ms=25,
        # Plugin renamed `keyterms` -> `keyterm` to match Deepgram API
        # naming; the old kwarg still works but emits a deprecation
        # warning. Using the new name here.
        keyterm=_KEYTERMS,
    )
