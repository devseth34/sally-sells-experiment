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
        # Lowered 0.95 -> 0.90 on 2026-04-25 after Dev's smoke test
        # ("some speak too fast"). EL Flash v2.5 honors this directly
        # via voice_settings.speed; tested at 0.90 still well within the
        # natural-prosody range Jessica was auditioned at.
        "speaking_rate": 0.90,
        "backchannel_density": "high",
        "post_response_pause_multiplier": 1.2,
        # Tier-aware fields added 2026-04-26 for sally_emotive parity.
        # Existing 3 arms: only fast tier (Flash); empty tag whitelist;
        # no inline disfluencies — keeps their CDS sample byte-stable.
        "tts_models": {"fast": "eleven_flash_v2_5"},
        "allowed_audio_tags": [],
        "disfluency_density": 0.0,
        # tag_director: when True AND allowed_audio_tags is non-empty, the
        # runner calls Haiku to choose tags + placement instead of the
        # rules-based expression.decorate() path. Existing 3 arms keep
        # this False — they're already gated by empty allowed_audio_tags
        # but the explicit flag makes the schema self-documenting.
        "tag_director": False,
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
        # Lowered 1.0 -> 0.92 on 2026-04-25. Alice is "Clear, Engaging
        # Educator" — at 1.0 the British prosody compounds with
        # NEPQ-style asks to feel rushed. 0.92 keeps her authoritative
        # without the educator-on-deadline feel Dev flagged.
        "speaking_rate": 0.92,
        "backchannel_density": "medium",
        "post_response_pause_multiplier": 1.0,
        "tts_models": {"fast": "eleven_flash_v2_5"},
        "allowed_audio_tags": [],
        "disfluency_density": 0.0,
        "tag_director": False,
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
        # Symbolic — Cartesia path doesn't read tts_models; included
        # for shape uniformity so callers can iterate PERSONALITIES
        # without per-arm branching on "does this key exist".
        "tts_models": {"fast": "cartesia_sonic_2"},
        "allowed_audio_tags": [],
        "disfluency_density": 0.0,
        "tag_director": False,
    },
    # 4th arm added 2026-04-26 (V3_IMPLEMENTATION.md). Held intentionally
    # parallel to sally_warm — same voice (Jessica), same engine arm
    # (sally_empathy_plus), same speaking_rate, same pause multiplier.
    # The ONLY experimental variable is "Flash flat" vs "v3 + expression
    # layer." Any other change here invalidates the A/B comparison.
    #
    # Tier routing (Phase F): the runner picks `fast` for greetings,
    # fast-path matches, undecorated turns, and all backchannels.
    # Picks `emotive` only when the expression layer inserted at least
    # one audio tag — that's the only case where v3's higher latency
    # earns its cost.
    "sally_emotive": {
        "engine_arm": "sally_empathy_plus",
        "tts_provider": "elevenlabs",
        "tts_voice_id": "cgSgspJ2msm6clMCkdW9",  # Jessica — same as warm
        "tts_models": {
            "fast": "eleven_flash_v2_5",
            "emotive": "eleven_v3",
        },
        # speaking_rate honored on Flash tier; v3 ignores it.
        "speaking_rate": 0.90,
        # Backchannels always Flash (Phase F gates this), so density
        # mirrors warm.
        "backchannel_density": "high",
        "post_response_pause_multiplier": 1.2,
        # Expanded 2026-04-26 (V3_TAG_DIRECTOR.md §2). Sales-relevant
        # subset of v3's tag taxonomy. Three categories:
        #
        #   Reactions      — pre-speech physical sounds (precede the clause)
        #   Emotional state — govern delivery of next 4-5 words
        #   Delivery direction — modify HOW words are spoken
        #
        # Audition-confirmed working: [laughs] [sighs] [exhales]. Others
        # remain on this list speculatively — Haiku director will pick
        # them, the user prunes any that read literally during smoke
        # testing. Reduce this list (no code change needed) — the
        # director's whitelist enforcement automatically stops emitting
        # rejected tags.
        "allowed_audio_tags": [
            # Reactions (pre-speech)
            "[laughs]",
            "[laughs harder]",
            "[sighs]",
            "[exhales]",
            "[clears throat]",
            "[breathes in]",
            "[sniff]",
            "[pauses]",
            # Emotional state (govern next 4-5 words)
            "[serious]",
            "[reassuring]",
            "[thoughtful]",
            "[concerned]",
            "[hopeful]",
            "[surprised]",
            "[excited]",
            "[empathetic]",
            "[curious]",
            "[warmly]",
            # Delivery direction (modify HOW)
            "[softly]",
            "[slowly]",
            "[quickly]",
            "[emphasizing]",
            "[deliberately]",
            "[whispers]",
        ],
        # Slightly higher than warm (0.0) to give v3 something to chew
        # on even when no tag landed in a phase pool. Inline "yeah,",
        # "you know," prefixes change Flash audio character too.
        "disfluency_density": 0.45,
        # Use Haiku 4.5 to choose tags + placement contextually instead
        # of the rules-based expression.decorate() path. The rules path
        # remains as the fallback when Haiku times out, errors, or
        # returns invalid output. See tag_director.py.
        "tag_director": True,
    },
}
