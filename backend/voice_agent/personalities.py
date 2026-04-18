"""Three voice personality configs: Warm / Confident / Direct.

Each maps to an existing engine persona arm from `app/persona_config.py`
(no change to persona_config.py itself — that file is frozen). Only the
voice surface and pacing differ between personalities.

Voice IDs are filled in after the Apr 19 audition block (Addendum §B7):
render a ~150-word audition script in 20 candidate voices (10 ElevenLabs
warm, 10 Cartesia professional), score warmth/clarity/trust/naturalness
1-5, pick top 3 non-overlapping + blind-check with 2 outsiders. Do not
swap voices after Day 2 — invalidates calibration.

TODO (Day 2, post-audition):
    - Fill in tts_voice_id for each personality.
    - Add a rationale comment per pick (why this voice for this arm).
    - Wire `backchannel_density` to backchannel.py trigger multipliers
      (see B6 table).

PERSONALITIES = {
    "sally_warm": {
        "engine_arm": "sally_empathy_plus",
        "tts_provider": "elevenlabs",
        "tts_voice_id": "<TBD post-audition>",
        "speaking_rate": 0.95,
        "backchannel_density": "high",
        "post_response_pause_multiplier": 1.2,
    },
    "sally_confident": {
        "engine_arm": "sally_nepq",
        "tts_provider": "cartesia",
        "tts_voice_id": "<TBD post-audition>",
        "speaking_rate": 1.0,
        "backchannel_density": "medium",
        "post_response_pause_multiplier": 1.0,
    },
    "sally_direct": {
        "engine_arm": "sally_direct",
        "tts_provider": "cartesia",
        "tts_voice_id": "<TBD post-audition>",
        "speaking_rate": 1.1,
        "backchannel_density": "low",
        "post_response_pause_multiplier": 0.85,
    },
}

Personality assignment: stratified random within pre_conviction_enum
stratum (Addendum §B11). See /api/voice/token endpoint for the
`assign_personality()` implementation.
"""
