"""Voice-specific legitimacy signals, layered onto the existing scorer.

The Phase 1B `app/legitimacy_scorer.py` scores text metrics (word count,
topic relevance) on the ASR transcript. Voice sessions add signals that
only exist in audio: call duration, speech-to-silence ratio, ASR
confidence, barge-in count, etc.

Total voice session legitimacy is capped at 100 across ALL signals
(text-based + voice-additive). Consent-given is a hard gate: if UI or
verbal consent is missing, auto-disqualify the session.

Signal table (Addendum §B12):

    Signal                       | Max pts | Logic
    -----------------------------+---------+----------------------------
    Call duration                |  20     | <60s=0, 60-180s=10, >180s=20
    Speech-to-silence ratio      |  15     | >40%=15, 20-40%=8, <20%=0
    ASR avg confidence           |  10     | >0.85=10, 0.7-0.85=5, <0.7=0
    Barge-in count               |  10     | 1-4=10 (engaged), 0/>8=0
    Completed post-survey        |  10     | Binary
    Consent (UI + verbal)        | -100 if absent -> auto-disqualify

TODO (Day 2+):
    - def score_voice_session(session: DBSession) -> VoiceLegitimacyScore
    - Pull duration from session.end_time - session.start_time.
    - Pull speech-to-silence from per-utterance audio timing in DBMessage
      (requires voice_agent to emit both ASR intervals and silence gaps).
    - Pull ASR confidence average from Deepgram finalized transcripts.
    - Pull barge-in count from DBSession.interruption_count.
    - Fail-closed on missing consent flags.
    - Compose with `app.legitimacy_scorer.score_session(...)` (do not
      modify the existing scorer — additive only).
"""
