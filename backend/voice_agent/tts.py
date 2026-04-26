"""TTS factory: personality key -> configured TTS plugin instance.

Exists so parrot.py (Day 3) and sally_voice_runner.py (Day 4) share
one code path for resolving the provider + voice_id + speaking_rate
from the locked PERSONALITIES table. Centralizing this also means a
voice-lock audit only needs to compare personalities.py against this
file, not every caller.

Provider dispatch:
    - elevenlabs: Flash v2.5 model (tier="fast") OR Eleven v3 model
      (tier="emotive", sally_emotive only). voice_id from PERSONALITIES.
    - cartesia:   Sonic-2 model (matches the Day 2B audition renders,
      so voice qualities are what Nik signed off on), voice_id from
      PERSONALITIES, speed as float. Tier is ignored; Cartesia uses
      one model only.

Tier dispatch (added 2026-04-26 for sally_emotive):
    - tier="fast": always available, returns the Flash/Sonic instance.
    - tier="emotive": only valid for personalities with an "emotive"
      entry in their `tts_models` map. Defensive fallback: if a caller
      requests "emotive" for an arm that doesn't have one, return the
      fast tier instead — that way the runner can blindly pass tier
      based on the expression layer's recommendation without per-arm
      branching.

speaking_rate convention across the codebase is a float multiplier
(1.0 = normal, 1.1 = slightly faster). Cartesia sonic-2 and ElevenLabs
Flash v2.5 accept float speeds directly in this range. Eleven v3
ignores speed entirely (spec §16).
"""

from __future__ import annotations

import os
from typing import Literal

from livekit.agents import tts as lk_tts
from livekit.plugins import cartesia

from backend.voice_agent.elevenlabs_v3_tts import (
    ElevenLabsV3TTS,
    V3AuthError,
    VoiceSettings as V3VoiceSettings,
)
from backend.voice_agent.personalities import PERSONALITIES


def make_tts(
    personality_key: str,
    *,
    tier: Literal["fast", "emotive"] = "fast",
) -> lk_tts.TTS:
    """Build a TTS instance for the given personality + tier.

    Raises KeyError if personality_key is not in PERSONALITIES.
    Raises ValueError if the personality's tts_provider is unknown.

    Tier defaults to "fast" so all existing callers (parrot.py,
    sally_voice_runner.py pre-Phase-F) keep working without changes.
    """
    cfg = PERSONALITIES[personality_key]
    provider = cfg["tts_provider"]
    voice_id = cfg["tts_voice_id"]
    speed = cfg["speaking_rate"]

    # Emotive tier dispatch — only for personalities that opted in via
    # tts_models["emotive"]. Defensive fallback for arms that didn't:
    # return their fast tier so the runner doesn't need to branch.
    if tier == "emotive":
        models = cfg.get("tts_models", {})
        if "emotive" in models and provider == "elevenlabs":
            return _make_eleven_v3(personality_key)
        # Fall through to fast-tier construction below.

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

        # The plugin reads env var `ELEVEN_API_KEY` by default, but our
        # .env uses `ELEVENLABS_API_KEY` (the name ElevenLabs' own SDK
        # uses). Pass through explicitly so callers don't need to
        # duplicate the key under two names.
        api_key = os.environ.get("ELEVENLABS_API_KEY") or os.environ.get("ELEVEN_API_KEY")
        return elevenlabs.TTS(
            model="eleven_flash_v2_5",
            voice_id=voice_id,
            api_key=api_key,
            # pcm_24000 matches our AudioSource's 24 kHz mono config in
            # sally.py. Default encoding is mp3_22050_32 which (a) makes
            # frames that don't match our 24 kHz source (RtcError
            # "sample_rate and num_channels don't match" on publish), and
            # (b) wastes CPU decoding mp3 for a realtime pipeline. PCM
            # straight through is cheaper and pitch-correct.
            encoding="pcm_24000",
            # Flash v2.5 accepts speed via voice_settings — plugin exposes
            # it as a top-level kwarg, forwarding to the API.
            voice_settings=elevenlabs.VoiceSettings(
                speed=speed,
                stability=0.5,
                similarity_boost=0.75,
            ),
        )

    raise ValueError(f"Unknown tts_provider {provider!r} for personality {personality_key!r}")


def _make_eleven_v3(personality_key: str) -> ElevenLabsV3TTS:
    """Build an ElevenLabs v3 TTS for the emotive tier.

    Called from `make_tts(key, tier="emotive")` for personalities that
    have an `"emotive"` entry in their `tts_models` map (today: only
    sally_emotive). Returns an `ElevenLabsV3TTS` adapter — see
    elevenlabs_v3_tts.py for why we bypass the livekit plugin.
    """
    cfg = PERSONALITIES[personality_key]
    if cfg["tts_provider"] != "elevenlabs":
        raise ValueError(
            f"v3 only available for elevenlabs-backed personalities; "
            f"{personality_key!r} uses {cfg['tts_provider']!r}"
        )
    api_key = os.environ.get("ELEVENLABS_API_KEY") or os.environ.get("ELEVEN_API_KEY")
    if not api_key:
        raise V3AuthError(
            "ELEVENLABS_API_KEY (or ELEVEN_API_KEY) must be set for v3 TTS"
        )
    return ElevenLabsV3TTS(
        voice_id=cfg["tts_voice_id"],
        api_key=api_key,
        # speed ignored by v3; stability/similarity match Flash defaults
        # so audio character stays consistent across tiers.
        voice_settings=V3VoiceSettings(stability=0.5, similarity_boost=0.75),
        sample_rate=24000,
    )
