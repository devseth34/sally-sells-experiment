"""Per-call wrapper around the frozen SallyEngine.

Translates the streaming voice loop (ASR transcript in, TTS audio out)
into the same turn-based interface SallyEngine expects for chat. Does
NOT modify `app/agent.py`, `app/layers/*.py`, `app/persona_config.py`,
or the semantics of `app/phase_definitions.py` (brain is frozen as of
Phase 1B sign-off).

Handles:
    - Streaming Layer 3 output into sentence-boundary chunks for TTS
      (see streaming_validator.py) per Addendum §A2.
    - Populating `ComprehensionOutput.interruption_context` when the
      prior Sally utterance was barge-in'd (Addendum §B3).
    - Passing `is_voice_channel=True` so Layer 3 tunes sentence length
      for spoken delivery (Addendum §C1).
    - Tracking `last_utterance_completed_text` and
      `last_utterance_truncated_text` for barge-in recovery.
    - Emitting per-stage latency dicts for DBMessage.latency_ms
      (vad / l1 / l3_ttft / tts_ttfb / backchannel_fired).

TODO (Day 2+):
    - class SallyVoiceRunner: wraps one DBSession for the call.
        - __init__(session_id, personality_config, engine)
        - async on_user_transcript(text, asr_confidence) -> AsyncIterator[Sentence]
        - async on_barge_in(timestamp) -> None
        - async finalize() -> None  # writes DBMessage rows, closes session
    - Integrate voice_fast_path.match() before invoking Layer 1.
    - Integrate pronunciation.preprocess() between Layer 3 sentences
      and TTS.
    - Integrate pause_manager.get_pause(phase) after each Sally turn.
    - Emit transcript rows in the format from plan §7.12.
"""
