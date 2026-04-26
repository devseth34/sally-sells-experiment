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
from backend.voice_agent.live_reasoning import LiveReasoningPublisher  # noqa: E402
from backend.voice_agent.persistence import SessionRecorder  # noqa: E402
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

    # Parse room metadata set by the frontend token endpoint.
    # Provides forcedPersonality (dev arm picker) and the callId that
    # links this LiveKit job to the voice_sessions DB row.
    import json as _json
    import os as _os

    _forced_from_meta: str | None = None
    _frontend_call_id: str | None = None
    try:
        if ctx.room.metadata:
            _meta = _json.loads(ctx.room.metadata)
            _forced_from_meta = _meta.get("forcedPersonality")
            _frontend_call_id = _meta.get("callId")
    except (ValueError, AttributeError):
        pass

    # SALLY_FORCE_PERSONALITY env var wins over room metadata (local dev).
    _env_forced = _os.environ.get("SALLY_FORCE_PERSONALITY")
    _forced_final = _env_forced or _forced_from_meta

    from backend.voice_agent.personalities import PERSONALITIES as _PERS
    personality = _forced_final if _forced_final in _PERS else assign_personality()

    # Use the frontend's callId so persistence keys match what the browser
    # has in its URL. Fall back to the LiveKit job.id if token was minted
    # outside the voice tab (e.g., direct Playground access).
    _call_id = _frontend_call_id or ctx.job.id

    logger.info(
        "Personality chosen for this call",
        extra={
            "personality": personality,
            "job_id": ctx.job.id,
            "call_id": _call_id,
            "forced": bool(_forced_final),
        },
    )

    stt = make_stt()
    tts = make_tts(personality)  # always the fast (Flash/Sonic) tier
    # Emotive tier (v3) — only built for sally_emotive. For all other
    # arms this is None and the runner stays on the fast path, identical
    # to pre-Phase-F behavior. Exception is swallowed: a broken v3 key
    # or missing aiohttp install must not prevent the other 3 arms from
    # working.
    tts_emotive = None
    try:
        tts_emotive = make_tts(personality, tier="emotive")
    except Exception:
        logger.debug("Emotive TTS not available for %s (non-fatal)", personality)
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
        extra={"path": str(metrics_sink.path), "call_id": _call_id},
    )

    recorder = SessionRecorder(
        call_id=_call_id,
        arm=personality,
        personality=personality,
        forced=bool(_forced_final),
    )

    # Live reasoning publisher (Phase 2). Fire-and-forget broadcast of
    # turn metadata to the participant's browser. Runs in parallel with
    # the recorder; the DB write remains the source of truth.
    publisher = LiveReasoningPublisher(ctx.room)

    runner = SallyVoiceRunner(
        personality=personality,
        tts=tts,
        tts_emotive=tts_emotive,
        audio_source=audio_source,
        on_session_end=_on_session_end,
        metrics_sink=metrics_sink,
        call_id=_call_id,
        recorder=recorder,
        publisher=publisher,
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
            # Per-utterance timing state. Deepgram fires events in this
            # typical order: SpeechStarted -> interim Results -> is_final
            # Results (FINAL_TRANSCRIPT) -> speech_final Results
            # (END_OF_SPEECH). So FINAL usually arrives BEFORE END, not
            # after. The original code assumed the reverse — which is
            # why asr_ms values were huge and uncorrelated with
            # utterance length. See
            # venv/.../livekit/plugins/deepgram/stt.py:660-717 for the
            # plugin's actual event mapping.
            #
            # Correct measurement of user-perceived ASR latency:
            #   asr_tail_ms = max(0, final_t - speech_end_t)
            # i.e. how long the user waited after stopping for the
            # transcript to be ready. If FINAL arrived first, tail is 0.
            # If END arrived first (rare), tail is positive.
            speech_start_t: float | None = None
            speech_end_t: float | None = None
            last_final_t: float | None = None

            async for speech_ev in stt_stream:
                if speech_ev.type == SpeechEventType.START_OF_SPEECH:
                    speech_start_t = time.monotonic()
                    speech_end_t = None  # new utterance, clear prior end
                    last_final_t = None
                    logger.info("STT: SPEECH_STARTED")
                elif speech_ev.type == SpeechEventType.END_OF_SPEECH:
                    speech_end_t = time.monotonic()
                    utt_dur_ms: float | None = None
                    if speech_start_t is not None:
                        utt_dur_ms = (speech_end_t - speech_start_t) * 1000
                    logger.info(
                        "STT: END_OF_SPEECH",
                        extra={
                            "utterance_duration_ms": round(utt_dur_ms) if utt_dur_ms is not None else None,
                            "final_already_arrived": last_final_t is not None,
                        },
                    )
                elif speech_ev.type == SpeechEventType.FINAL_TRANSCRIPT:
                    text = (
                        speech_ev.alternatives[0].text
                        if speech_ev.alternatives
                        else ""
                    )
                    if not text.strip():
                        continue
                    final_t = time.monotonic()
                    last_final_t = final_t

                    # asr_tail_ms: time from user-speech-end to transcript-ready.
                    # Only meaningful if END_OF_SPEECH for this utterance has
                    # already fired; otherwise transcript was ready BEFORE VAD
                    # decided speech ended (tail is conceptually 0 — user
                    # wasn't waiting on us at that moment).
                    asr_tail_ms: float | None = None
                    if speech_end_t is not None:
                        asr_tail_ms = max(0.0, (final_t - speech_end_t) * 1000)

                    utt_dur_ms = None
                    if speech_start_t is not None and speech_end_t is not None:
                        utt_dur_ms = (speech_end_t - speech_start_t) * 1000

                    logger.info(
                        "ASR final",
                        extra={
                            "asr_tail_ms": round(asr_tail_ms) if asr_tail_ms is not None else None,
                            "utterance_duration_ms": round(utt_dur_ms) if utt_dur_ms is not None else None,
                            "end_before_final": speech_end_t is not None,
                            "text": text,
                        },
                    )
                    # Kick off turn processing — don't await, so one
                    # long engine turn doesn't block the next ASR read.
                    # The runner's turn_lock drops concurrent finals.
                    # speech_end_t passed as monotonic() timestamp so the
                    # runner can compute user_perceived_latency_ms =
                    # tts_first_frame_t - speech_end_t after the turn.
                    asyncio.create_task(
                        runner.on_user_turn(
                            text,
                            asr_ms=asr_tail_ms,
                            speech_end_t=speech_end_t,
                            utterance_duration_ms=utt_dur_ms,
                        )
                    )

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

    # Phase 2: announce the session to any subscribed browser. The greeting
    # has finished by now, so the data channel is ready and the live panel
    # has a participant to listen on. Best-effort — failures are swallowed.
    try:
        await publisher.publish_session(
            call_id=_call_id,
            arm=personality,
            personality=personality,
            forced=bool(_forced_final),
        )
    except Exception:  # noqa: BLE001
        logger.debug("publish_session failed (non-fatal)", exc_info=True)

    try:
        await shutdown_event.wait()
    finally:
        for task in list(stt_tasks):
            task.cancel()
        await audio_source.aclose()
        # Flush session to DB. session_ended=True when the engine drove the
        # end (ownership/commitment close); False when user disconnected.
        try:
            await recorder.flush(session_ended=runner._adapter.ended)
        except Exception:  # noqa: BLE001
            logger.exception("recorder.flush failed (non-fatal)")


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
