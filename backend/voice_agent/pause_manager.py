"""Strategic silence manager: per-phase post-response pause settings.

After Sally finishes speaking, the agent waits this long before
considering the user "late" and re-prompting. Voice-specific: the
original plan's table (§7.4) is the starting point; personality
multipliers (personalities.post_response_pause_multiplier) scale them.

Pause values (ms) — these live on `PhaseDefinition.post_response_pause_ms`
(optional field added under Addendum §C1; existing chat semantics
unchanged):

    CONNECTION          800
    SITUATION           1200
    PROBLEM_AWARENESS   2000
    SOLUTION_AWARENESS  1500
    CONSEQUENCE         2500
    OWNERSHIP           3000
    COMMITMENT          2000

End-of-turn silence thresholds also live per-phase (Addendum §C1
`eot_silence_ms`). Swapped for learned TurnDetector on Day 5 (§B5);
silence-VAD remains as fallback.

TODO (Day 2+):
    - def get_post_response_pause_ms(phase, personality) -> int
    - def get_eot_silence_ms(phase, personality) -> int
    - Read values from phase_definitions.PHASE_DEFINITIONS; apply
      personality multiplier.
    - Expose `reset_timer(session_id)` / `user_spoke(session_id)` hooks
      for the agent.py event loop.
"""
