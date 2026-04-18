"""LiveKit Agents entry point for Sally voice.

Boots a long-running worker that accepts LiveKit room invitations, wires
Deepgram (ASR) + Cartesia/ElevenLabs (TTS) around the frozen SallyEngine,
and manages the per-call conversation loop.

Referenced by Dockerfile CMD: `python -m voice_agent.agent`.

Current scope (Day 2A — hello-world plumbing check):
    - Registers as a LiveKit worker using credentials from .env.
    - On room dispatch: joins the room, logs participant + track events.
    - No ASR, no TTS, no Sally brain yet — those land Day 3 / Day 4.

TODO (Day 3+):
    - Wire Deepgram streaming STT -> runner.on_user_transcript().
    - Wire runner.on_sally_sentence() -> Cartesia/ElevenLabs TTS stream.
    - Spin up a `SallyVoiceRunner` (sally_voice_runner.py) per job,
      using personality assignment from job metadata.
    - Register VAD / TurnDetector callbacks for EOT + barge-in (see B5).
    - Fire backchannels per backchannel.py trigger rules (B6).
    - Honor cost_guard.can_accept_call() before accepting new jobs (B13).
    - Emit call lifecycle webhooks to FastAPI: /api/voice/token (already
      issued before join), /api/voice/end on disconnect.
    - Enable Krisp noise suppression on the room config (B9).
    - Graceful shutdown on SIGTERM (flush transcripts, close TTS streams).

Run locally:
    source venv/bin/activate
    python -m backend.voice_agent.agent dev

    The `dev` subcommand (from livekit.agents.cli) registers this
    process as a worker with your LiveKit Cloud project using the
    credentials in .env. Any browser that connects to your project
    URL will trigger a dispatch to this running worker.

Test in browser:
    1. Start the worker (command above). Wait for the "registered
       worker" log line.
    2. Open https://agents-playground.livekit.io/ in a browser.
    3. Enter your LIVEKIT_URL, create a participant token (the
       playground has a helper), and connect to a room.
    4. The worker log should show "PARTICIPANT CONNECTED: <identity>"
       when you join, and "TRACK SUBSCRIBED" when your mic track
       publishes.
"""

from __future__ import annotations

import logging
from pathlib import Path

from dotenv import load_dotenv

# Load env from repo root BEFORE importing livekit — the SDK reads
# LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET at import time.
# repo-root = this file's parent.parent.parent (backend/voice_agent/agent.py -> repo/.env).
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_REPO_ROOT / ".env")

from livekit import rtc  # noqa: E402  -- must import after load_dotenv
from livekit.agents import JobContext, WorkerOptions, cli  # noqa: E402

logger = logging.getLogger("sally-voice-agent")


async def entrypoint(ctx: JobContext) -> None:
    """Called by the LiveKit worker when a room is dispatched to us.

    Day 2A scope: join the room, log events, stay alive. Day 3 will
    layer ASR/TTS on top of this same entry point.
    """
    logger.info("Agent dispatched: room=%s job_id=%s", ctx.room.name, ctx.job.id)

    # Register room event handlers BEFORE ctx.connect() so we don't
    # miss the first participant joining (rare race, but real).
    @ctx.room.on("participant_connected")
    def _on_participant_connected(participant: rtc.RemoteParticipant) -> None:
        logger.info("PARTICIPANT CONNECTED: identity=%s sid=%s", participant.identity, participant.sid)

    @ctx.room.on("participant_disconnected")
    def _on_participant_disconnected(participant: rtc.RemoteParticipant) -> None:
        logger.info("PARTICIPANT DISCONNECTED: identity=%s sid=%s", participant.identity, participant.sid)

    @ctx.room.on("track_subscribed")
    def _on_track_subscribed(
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ) -> None:
        logger.info(
            "TRACK SUBSCRIBED: kind=%s from=%s sid=%s",
            track.kind,
            participant.identity,
            publication.sid,
        )

    @ctx.room.on("track_unsubscribed")
    def _on_track_unsubscribed(
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ) -> None:
        logger.info(
            "TRACK UNSUBSCRIBED: kind=%s from=%s sid=%s",
            track.kind,
            participant.identity,
            publication.sid,
        )

    # Join the room as the agent participant.
    await ctx.connect()
    logger.info(
        "Agent connected: room=%s local_identity=%s",
        ctx.room.name,
        ctx.room.local_participant.identity,
    )

    # Stay alive until the room disconnects. ctx.wait_for_participant()
    # is Agents-SDK idiomatic but for Day 2A we don't need to block on
    # anything specific — the framework will dispose of us when the
    # room ends.


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
