"""LiveKit Agents entry point for Sally voice.

Boots a long-running worker that accepts LiveKit room invitations, wires
Deepgram (ASR) + Cartesia/ElevenLabs (TTS) around the frozen SallyEngine,
and manages the per-call conversation loop.

Referenced by Dockerfile CMD: `python -m voice_agent.agent`.

TODO (Day 2+):
    - Instantiate a `livekit.agents.Worker` with a JobRequest handler.
    - On room join: fetch personality assignment from /api/voice/token
      metadata, spin up a `SallyVoiceRunner` (sally_voice_runner.py).
    - Wire Deepgram streaming STT -> runner.on_user_transcript().
    - Wire runner.on_sally_sentence() -> Cartesia/ElevenLabs TTS stream.
    - Register VAD / TurnDetector callbacks for EOT + barge-in (see B5).
    - Fire backchannels per backchannel.py trigger rules (B6).
    - Honor cost_guard.can_accept_call() before accepting new jobs (B13).
    - Emit call lifecycle webhooks to FastAPI: /api/voice/token (already
      issued before join), /api/voice/end on disconnect.
    - Enable Krisp noise suppression on the room config (B9).
    - Graceful shutdown on SIGTERM (flush transcripts, close TTS streams).
"""


def main() -> None:
    """TODO: wire up LiveKit Agents Worker. Placeholder for Day 2."""
    raise NotImplementedError("Voice agent entry point not yet implemented.")


if __name__ == "__main__":
    main()
