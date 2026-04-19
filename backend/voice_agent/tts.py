"""TTS factory: personality key -> configured TTS plugin instance.

Exists so parrot.py (Day 3) and sally_voice_runner.py (Day 4) share
one code path for resolving the provider + voice_id + speaking_rate
from the locked PERSONALITIES table. Centralizing this also means a
voice-lock audit only needs to compare personalities.py against this
file, not every caller.

Provider dispatch:
    - elevenlabs: Flash v2.5 model, voice_id from PERSONALITIES,
      speed from speaking_rate via voice_settings.
    - cartesia:   Sonic-2 model (matches the Day 2B audition renders,
      so voice qualities are what Nik signed off on), voice_id from
      PERSONALITIES, speed as float.

speaking_rate convention across the codebase is a float multiplier
(1.0 = normal, 1.1 = slightly faster). Both Cartesia sonic-2 and
ElevenLabs Flash v2.5 accept float speeds directly in this range.
"""

from __future__ import annotations

from livekit.agents import tts as lk_tts
from livekit.plugins import cartesia

from backend.voice_agent.personalities import PERSONALITIES


def make_tts(personality_key: str) -> lk_tts.TTS:
    """Build a TTS instance for the given personality.

    Raises KeyError if personality_key is not in PERSONALITIES.
    Raises ValueError if the personality's tts_provider is unknown.
    """
    cfg = PERSONALITIES[personality_key]
    provider = cfg["tts_provider"]
    voice_id = cfg["tts_voice_id"]
    speed = cfg["speaking_rate"]

    if provider == "cartesia":
        # Model pinned to the dated snapshot `sonic-2-2025-03-07` (not
        # the `sonic-2` alias) so the voice behavior Nik signed off on
        # 2026-04-19 is frozen, per the Addendum §B11 voice-lock rule.
        #
        # `speed` is DROPPED for Day 3 despite cfg["speaking_rate"]
        # being set in PERSONALITIES. Why: livekit-plugins-cartesia
        # 1.5.4 hardcodes `Cartesia-Version: 2025-04-16` in
        # constants.py and sends that header regardless of the
        # api_version kwarg we pass. On the 2025-04-16 API, sonic-2
        # rejects `speed` with HTTP 400 ("Bad Request") — confirmed by
        # smoke-test on 2026-04-19. Day 3 parrot proves the round-trip
        # works at normal pace; Day 4/5 needs personality pacing and
        # will have to either (a) vendor the plugin and swap the
        # header, (b) upgrade to sonic-3 (requires re-auditioning all
        # three Cartesia voices + Nik approval), or (c) wait for
        # plugin 1.6+ to thread api_version into the header.
        _ = speed  # explicitly unused, see above
        return cartesia.TTS(
            model="sonic-2-2025-03-07",
            voice=voice_id,
            sample_rate=24000,
        )

    if provider == "elevenlabs":
        # Import lazily: the ElevenLabs plugin pulls in a larger
        # dependency tree, and Day 3 parrot only exercises Cartesia.
        # Lazy import keeps parrot's cold-start fast and means any
        # ElevenLabs install hiccup doesn't break Day 3 dev runs.
        from livekit.plugins import elevenlabs  # noqa: PLC0415

        return elevenlabs.TTS(
            model="eleven_flash_v2_5",
            voice_id=voice_id,
            # Flash v2.5 accepts speed via voice_settings — plugin exposes
            # it as a top-level kwarg, forwarding to the API.
            voice_settings=elevenlabs.VoiceSettings(
                speed=speed,
                stability=0.5,
                similarity_boost=0.75,
            ),
        )

    raise ValueError(f"Unknown tts_provider {provider!r} for personality {personality_key!r}")
