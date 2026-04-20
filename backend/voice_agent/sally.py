"""Day 4 Sally voice worker: real NEPQ engine through a LiveKit room.

Wiring:
    user mic  -> Deepgram Nova-3 (make_stt)
              -> SallyVoiceRunner.on_user_turn
                   -> SallyEngineAdapter.turn (frozen engine)
                   -> pronunciation.preprocess
                   -> make_tts(assigned_personality)
                   -> rtc.AudioSource -> user speakers

Personality is chosen at dispatch via `assign_personality()` (uniform
random across the three locked arms for Day 4; will become DB-backed
balanced allocation in Day 5).

Structurally the same shape as parrot.py — same env bootstrap, same
track-attach dedupe, same audio I/O layout. The only difference is the
"middle": parrot echoes, sally calls the real engine. This symmetry is
intentional — parrot stays as a narrow smoke-test tool for the STT/TTS
layer alone.

Run locally:
    source venv/bin/activate
    python -m backend.voice_agent.sally start

Then connect via the Agent Console at cloud.livekit.io -> sally-sells
-> Agents -> Launch Console (the standalone Playground at
agents-playground.livekit.io is NOT project-scoped — see memory note).
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from dotenv import load_dotenv

# Load env BEFORE importing livekit or the engine bridge — the SDK
# reads credentials at import time, and app.* needs GOOGLE_API_KEY +
# ANTHROPIC_API_KEY to initialize its module-level clients lazily.
# override=True because livekit-agents prewarmed subprocesses inherit
# os.environ with API-key vars pre-set to empty strings; default
# override=False would leave those empties alone and the ElevenLabs
# plugin (which reads env at make_tts() time) then sends "" as the key
# and 401s. Same reason engine_adapter.py already uses override=True.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_REPO_ROOT / ".env", override=True)

from livekit import rtc  # noqa: E402
from livekit.agents import JobContext, WorkerOptions, cli  # noqa: E402
from livekit.agents.stt import SpeechEventType  # noqa: E402

from backend.voice_agent.assignment import assign_personality  # noqa: E402
from backend.voice_agent.metrics import (  # noqa: E402
    default_sink,
    install_comprehension_capture,
)
from backend.voice_agent.sally_voice_runner import SallyVoiceRunner  # noqa: E402
from backend.voice_agent.stt import make_stt  # noqa: E402
from backend.voice_agent.tts import make_tts  # noqa: E402

# Install the Layer-1-model capture filter once per subprocess. The
# call is idempotent — livekit-agents reuses prewarm processes across
# dispatches, so entrypoint() re-entry is expected; we don't want to
# stack duplicate filters.
install_comprehension_capture()

logger = logging.getLogger("sally-voice")

# Audio input format for Deepgram. Matches make_stt() default (16 kHz
# mono — Nova-3's sweet spot). If this drifts, Deepgram will resample
# internally and we eat an extra few ms of latency.
_STT_SAMPLE_RATE = 16000
_STT_CHANNELS = 1

# Audio output format for the agent's track. 24 kHz mono matches both
# Cartesia sonic-2 and ElevenLabs Flash v2.5 output rates — same
# constants parrot.py settled on during Day 3 smoke.
_TTS_SAMPLE_RATE = 24000
_TTS_CHANNELS = 1


async def entrypoint(ctx: JobContext) -> None:
    """Called by the LiveKit worker per room dispatch.

    Owns: one SallyVoiceRunner (which owns the engine adapter), one
    STT instance shared across all user tracks, one TTS sink + one
    AudioSource for publishing Sally's voice.
    """
    logger.info(
        "Sally dispatched",
        extra={"room": ctx.room.name, "job_id": ctx.job.id},
    )

    # Personality assignment — one draw per dispatch. Log the pick so
    # CDS calibration (Day 5+) can reconstruct the assignment sequence
    # from worker logs if the DB write layer is still WIP.
    personality = assign_personality()
    logger.info(
        "Personality chosen for this call",
        extra={"personality": personality, "job_id": ctx.job.id},
    )

    stt = make_stt()
    tts = make_tts(personality)
    audio_source = rtc.AudioSource(_TTS_SAMPLE_RATE, _TTS_CHANNELS)
    agent_track = rtc.LocalAudioTrack.create_audio_track("sally-voice", audio_source)

    # Track attach dedupe (Day 3 lesson: `track_subscribed` ALSO fires
    # for pre-existing tracks, so combining with post-connect
    # enumeration over remote_participants double-attaches the same
    # track. Memory note: feedback_livekit_track_subscribed_dedupe.md)
    attached_track_sids: set[str] = set()
    stt_tasks: set[asyncio.Task[None]] = set()

    # Signal for orderly shutdown when the engine reports session_ended.
    shutdown_event = asyncio.Event()

    async def _on_session_end() -> None:
        shutdown_event.set()

    metrics_sink = default_sink()
    logger.info(
        "Metrics sink",
        extra={"path": str(metrics_sink.path), "call_id": ctx.job.id},
    )

    runner = SallyVoiceRunner(
        personality=personality,
        tts=tts,
        audio_source=audio_source,
        on_session_end=_on_session_end,
        metrics_sink=metrics_sink,
        call_id=ctx.job.id,
    )

    async def _drive_stt_from_track(
        track: rtc.Track,
        participant: rtc.RemoteParticipant,
    ) -> None:
        logger.info(
            "STT: attaching to track",
            extra={"identity": participant.identity, "track_sid": track.sid},
        )
        audio_stream = rtc.AudioStream.from_track(
            track=track,
            sample_rate=_STT_SAMPLE_RATE,
            num_channels=_STT_CHANNELS,
        )
        stt_stream = stt.stream()

        async def _pump_audio() -> None:
            async for ev in audio_stream:
                stt_stream.push_frame(ev.frame)
            stt_stream.end_input()

        async def _read_transcripts() -> None:
            utterance_end_t: float | None = None
            async for speech_ev in stt_stream:
                if speech_ev.type == SpeechEventType.END_OF_SPEECH:
                    utterance_end_t = time.monotonic()
                elif speech_ev.type == SpeechEventType.FINAL_TRANSCRIPT:
                    text = (
                        speech_ev.alternatives[0].text
                        if speech_ev.alternatives
                        else ""
                    )
                    if not text.strip():
                        continue
                    asr_ms: float | None = None
                    if utterance_end_t is not None:
                        asr_ms = (time.monotonic() - utterance_end_t) * 1000
                        logger.info(
                            "ASR final",
                            extra={"asr_ms_since_eos": round(asr_ms), "text": text},
                        )
                        utterance_end_t = None
                    else:
                        logger.info("ASR final (no EOS anchor)", extra={"text": text})
                    # Kick off turn processing — don't await, so one
                    # long engine turn doesn't block the next ASR read.
                    # The runner's turn_lock drops concurrent finals.
                    asyncio.create_task(runner.on_user_turn(text, asr_ms=asr_ms))

        await asyncio.gather(_pump_audio(), _read_transcripts())

    def _attach_if_audio(
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ) -> None:
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        if publication.sid in attached_track_sids:
            return
        attached_track_sids.add(publication.sid)
        task = asyncio.create_task(
            _drive_stt_from_track(track, participant),
            name=f"stt-{participant.identity}-{publication.sid}",
        )
        stt_tasks.add(task)
        task.add_done_callback(stt_tasks.discard)

    @ctx.room.on("track_subscribed")
    def _on_track_subscribed(
        track: rtc.Track,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ) -> None:
        _attach_if_audio(track, publication, participant)

    @ctx.room.on("participant_disconnected")
    def _on_participant_disconnected(participant: rtc.RemoteParticipant) -> None:
        logger.info("Participant left", extra={"identity": participant.identity})
        # If the only remote participant leaves, the user hung up —
        # signal shutdown so we don't keep a zombie agent in the room.
        if not any(
            p for p in ctx.room.remote_participants.values() if p is not participant
        ):
            shutdown_event.set()

    await ctx.connect()
    logger.info(
        "Sally connected",
        extra={
            "room": ctx.room.name,
            "local_identity": ctx.room.local_participant.identity,
        },
    )

    publish_opts = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    await ctx.room.local_participant.publish_track(agent_track, publish_opts)

    # Enumerate pre-existing participants' audio tracks (gotcha #1 from
    # CLAUDE.md). The dedupe set above makes this idempotent against
    # track_subscribed events that also fire.
    for participant in ctx.room.remote_participants.values():
        for publication in participant.track_publications.values():
            if publication.track is not None:
                _attach_if_audio(publication.track, publication, participant)

    # Sally opens before the user speaks. This is the whole reason we
    # publish the agent track before reading STT — the opener needs an
    # audio sink ready. runner.open() acquires the turn lock internally
    # so any early ASR final is dropped until the greeting finishes.
    await runner.open()

    try:
        await shutdown_event.wait()
    finally:
        for task in list(stt_tasks):
            task.cancel()
        await audio_source.aclose()


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
