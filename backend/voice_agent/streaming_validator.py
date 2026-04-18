"""Sentence-boundary validator for streaming Layer 3 output.

The chat path validates Layer 3's FULL response before releasing it via
the circuit breaker. Voice can't wait for the full response — audio has
to start playing in under 1.5s. So we validate sentence-by-sentence and
roll back gracefully on mid-stream failures (Addendum §A2).

Flow:
    1. Accumulate Claude streaming tokens.
    2. Flush at sentence boundaries (., ?, ! followed by whitespace).
    3. Run each completed sentence through the validator chain:
        - length check (<= phase max words)
        - forbidden-phrase regex (hype, unreviewed claims)
        - phase-appropriate content check (no pitching pre-CONSEQUENCE,
          no prescriptive advice pre-OWNERSHIP)
    4. On pass -> push to TTS queue.
    5. On fail for the FIRST sentence -> halt, emit
       "let me put that a different way", regenerate with stronger
       guardrails.
    6. On fail LATER (already streaming) -> cut TTS at next natural
       pause; emit a recovery phrase; restart from that point.

Fallback: if mid-stream cuts happen >1x per 20 calls in Stage 1, revert
to full-response validation and eat the latency (backchannel masks most
of it anyway).

TODO (Day 2+):
    - class SentenceStream: token accumulator + boundary detector.
    - class SentenceValidator: length / forbidden / phase checks.
    - Define FORBIDDEN_PHRASE_REGEX.
    - Define per-phase content rules (mirror Phase 1B guardrails).
    - Metrics: count first-sentence fails vs mid-stream fails per call
      for the fallback decision.
"""
