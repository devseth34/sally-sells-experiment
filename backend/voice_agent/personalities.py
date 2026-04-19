"""Three voice personality configs: Warm / Confident / Direct.

Each maps to an existing engine persona arm from `app/persona_config.py`
(no change to persona_config.py itself — that file is frozen). Only the
voice surface and pacing differ between personalities.

Voice picks LOCKED 2026-04-19 after the Day 2B audition block. See
`backend/voice_agent/audition.py` for the rendering/scoring harness;
rendered MP3s sit under `backend/voice_agent/auditions/` (gitignored,
regenerable via `python -m backend.voice_agent.audition render`).

Scoring rubric: warmth × 1.0 + clarity × 1.2 + trust × 1.3 +
naturalness × 1.5. Max = 25.0. Trust + naturalness weighted highest
because those are the hardest dimensions to fake — a voice that scores
low on either will feel wrong in a sales context even if the other
dims are strong.

Final picks:

    sally_warm       Jessica  (ElevenLabs)  20.00   4/4/4/4
    sally_confident  Alice    (ElevenLabs)  18.50   4/4/4/3   [*]
    sally_direct     Thandi   (Cartesia)    16.00   4/3/3/3

    [*] sally_confident was originally planned as a Cartesia voice
        (see original docstring in git history). Cartesia's confident
        field turned out thin — 7 of 10 Cartesia voices were rejected
        1/1/1/1 in scoring, and Linda (the only Cartesia voice with
        "confident" in the descriptor) scored 12.20 with weak trust
        and naturalness, the two heaviest-weighted dims. Alice at
        18.50 (British "Clear, Engaging Educator" profile) dominates
        the confident field. Flash v2.5 latency (~75ms) is also
        faster than Sonic-2 (~90ms), so the Cartesia-for-confident
        assumption was an unforced constraint, not a latency hedge.
        We keep provider diversity via Thandi on Cartesia for direct.

DO NOT swap voices mid-experiment — invalidates CDS calibration across
the ≥40-session sample (Addendum §B11). If a voice becomes unavailable
on a provider, escalate to Nik before re-picking.

TODO (Day 3+):
    - Wire `backchannel_density` to backchannel.py trigger multipliers
      (see Addendum §B6 table).
    - Smoke-test each locked voice inside the live Deepgram→Layer→TTS
      pipeline (not just the static audition render) to catch prosody
      issues that isolated renders can't surface.

Personality assignment: stratified random within pre_conviction_enum
stratum (Addendum §B11). See /api/voice/token endpoint for the
`assign_personality()` implementation.
"""

PERSONALITIES: dict[str, dict] = {
    "sally_warm": {
        "engine_arm": "sally_empathy_plus",
        "tts_provider": "elevenlabs",
        # Jessica — "Playful, Bright, Warm", young american female.
        # Top scorer overall (20.00, perfect 4/4/4/4). Warmth and
        # naturalness are the two heaviest-weighted dims — Jessica
        # hits both. Profile aligns exactly with sally_empathy_plus:
        # warm opener, curious mirror, softness on pain reveal.
        "tts_voice_id": "cgSgspJ2msm6clMCkdW9",
        "speaking_rate": 0.95,
        "backchannel_density": "high",
        "post_response_pause_multiplier": 1.2,
    },
    "sally_confident": {
        "engine_arm": "sally_nepq",
        # Provider: ElevenLabs (plan-break — see module docstring).
        "tts_provider": "elevenlabs",
        # Alice — "Clear, Engaging Educator", middle-aged british
        # female, professional. Scored 18.50 (4/4/4/3). British
        # accent conveys authority without arrogance; "educator"
        # framing fits the NEPQ pivot where Sally must confidently
        # restate the prospect's pain and frame the 100x guarantee.
        # Second-highest score in the field; top non-warm-coded.
        "tts_voice_id": "Xb7hH8MSUJpSbSDYk0k2",
        "speaking_rate": 1.0,
        "backchannel_density": "medium",
        "post_response_pause_multiplier": 1.0,
    },
    "sally_direct": {
        "engine_arm": "sally_direct",
        "tts_provider": "cartesia",
        # Thandi — "Direct Dispatcher", South African female,
        # professional. Scored 16.00 (4/3/3/3). "Direct Dispatcher"
        # is on-the-nose for the sally_direct arm; warmth = 4 keeps
        # her from sounding cold while still delivering crisp one-
        # beat asks. Top Cartesia voice with a direct profile.
        "tts_voice_id": "692846ad-1a6b-49b8-bfc5-86421fd41a19",
        "speaking_rate": 1.1,
        "backchannel_density": "low",
        "post_response_pause_multiplier": 0.85,
    },
}
