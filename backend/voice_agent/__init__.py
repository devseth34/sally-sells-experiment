"""Sally voice agent package.

Wraps the frozen Phase 1B NEPQ engine (`app.agent.SallyEngine`) with
streaming ASR, TTS, barge-in, backchannels, and per-phase pacing so Sally
can hold real-time voice conversations over WebRTC via LiveKit.

See PHASE_2_VOICE_AGENT_PLAN.md and PHASE_2_PLAN_ADDENDUM.md at the repo
root for the full design.
"""
