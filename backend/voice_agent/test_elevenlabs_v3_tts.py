"""STALE — superseded by the AsyncElevenLabs SDK rewrite of elevenlabs_v3_tts.py.

This file was originally written against the raw-aiohttp + SSE-parsing
version of `ElevenLabsV3TTS`. That version was scrapped after the user's
audition revealed the SDK's `text_to_speech.stream()` is the only path
that renders v3 audio tags as real sounds (raw HTTP read them literally).
The rewrite removed `_get_session`, the SSE parser, `MAX_CHARS_V3`, and
the retry/exception classes this file imports.

The current SDK-based adapter is exercised through:
  - test_integration.py (uses _FakeTTS at the runner boundary; covers
    the same call path the v3 adapter sits in)
  - manual smoke testing via the LiveKit Agents Playground

A focused unit test of the SDK adapter (mocking AsyncElevenLabs.text_to_speech
.stream) would be valuable but is out of scope for the current phase.
Re-enable by deleting this file and writing fresh tests against the
SDK-based class in elevenlabs_v3_tts.py.

Run: skipped via collect_ignore_glob in pyproject (or just by this empty file).
"""

import pytest

# Empty test module — pytest will collect zero tests from this file.
# Keeping the file (vs deleting) preserves the rationale for anyone who
# pulls the repo and wonders why it's empty.
pytest.skip(
    "test_elevenlabs_v3_tts.py is stale — see file docstring for context",
    allow_module_level=True,
)
