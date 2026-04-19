"""Day 3 parrot-back worker: STT -> preprocess -> TTS round-trip.

Purpose:
    Prove the audio pipeline works end-to-end in a LiveKit room before
    Sally's brain lands in Day 4. User speaks -> Deepgram Nova-3
    transcribes -> pronunciation.preprocess() applies the LEXICON ->
    Cartesia Sonic-2 speaks the same words back in Thandi's voice.

    This is a vertical slice of Day 4's pipeline — the only difference
    is the middle stage. In Day 4, `sally_voice_runner.py` replaces
    `_parrot_text()` below with `SallyEngine.turn(transcript)`. STT
    capture, pronunciation preprocessing, and TTS publishing stay the
    same.

Voice choice:
    sally_direct (Thandi, Cartesia). The sally_direct personality has
    the tightest pacing (speaking_rate 1.1, post_response_pause 0.85),
    which stresses latency the hardest — if we can round-trip cleanly
    on sally_direct, we're fine on the slower-paced personalities too.

Success criteria (verify manually in Agents Playground):
    1. `python -m backend.voice_agent.parrot dev` registers the worker.
    2. Open https://agents-playground.livekit.io/ and connect to a room.
    3. Speak a phrase containing a landmine term: "Tell Nik Shah about
       the NEPQ arm and the CDS score."
    4. Within ~2s of stopping, Thandi echoes back: "Tell Nick Shah
       about the N-E-P-Q arm and the C-D-S score." (pronunciation
       corrected by LEXICON pass).
    5. End-of-speech -> first audio out should be < 700ms typical,
       < 1.5s worst case. Anything above 1.5s feels wrong on voice.

Known gotchas (handled below):
    - participant_connected fires only for post-dispatch joins, so we
      also enumerate ctx.room.remote_participants on connect.
    - Playground sends lk.agent.session byte streams every 5s; these
      are Playground metadata, not audio. We don't log them (unlike
      agent.py's noisy default).
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from dotenv import load_dotenv

# Load .env BEFORE importing livekit — SDK reads credentials at import.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_REPO_ROOT / ".env")

from livekit import rtc  # noqa: E402
from livekit.agents import JobContext, WorkerOptions, cli  # noqa: E402
from livekit.agents.stt import SpeechEventType  # noqa: E402

from backend.voice_agent.pronunciation import preprocess  # noqa: E402
from backend.voice_agent.stt import make_stt  # noqa: E402
from backend.voice_agent.tts import make_tts  # noqa: E402

logger = logging.getLogger("sally-voice-parrot")

# sally_direct drives the parrot — see module docstring.
_PERSONALITY = "sally_direct"
_TTS_PROVIDER = "cartesia"

# Audio output config. 24 kHz matches Cartesia's sonic-2 output sample
# rate; mono is correct for voice. If we ever swap to ElevenLabs here,
# Flash v2.5 output is also 24 kHz so the source config stays valid.
_TTS_SAMPLE_RATE = 24000
_TTS_CHANNELS = 1

# Audio input config for Deepgram. 16 kHz is the make_stt() default and
# is the sweet spot for Nova-3 (higher rates don't improve accuracy and
# waste bandwidth).
_STT_SAMPLE_RATE = 16000
_STT_CHANNELS = 1


async def entrypoint(ctx: JobContext) -> None:
    """Called per room dispatch. Owns one STT stream + one TTS sink."""
    logger.info("Parrot dispatched: room=%s job_id=%s", ctx.room.name, ctx.job.id)

    stt = make_stt()
    tts = make_tts(_PERSONALITY)

    # TTS output sink. Create BEFORE connect() so it's ready when we
    # publish the track right after joining.
    audio_source = rtc.AudioSource(_TTS_SAMPLE_RATE, _TTS_CHANNELS)
    agent_track = rtc.LocalAudioTrack.create_audio_track("sally-parrot", audio_source)

    # Track the handler tasks we spawn for user audio so we can cancel
    # them on disconnect without leaking tasks across dispatches.
    stt_tasks: set[asyncio.Task[None]] = set()

    # Dedupe key set for track attachments. Both the `track_subscribed`
    # event AND our post-connect `remote_participants` enumeration can
    # fire for the same pre-existing track — attaching twice spawns
    # two concurrent _speak coroutines that race on the same
    # audio_source, producing glitchy/choppy playback and eventually
    # RtcError "InvalidState - failed to capture frame". Dedupe by
    # track SID.
    attached_track_sids: set[str] = set()

    async def _speak(text: str) -> None:
        """Synthesize `text` through the personality's TTS and publish.

        Swallows TTS failures after logging them. A single failed
        synthesis must not kill the STT task — the user would disconnect
        and re-dispatch for every bad utterance, which is unusable.
        Cartesia occasionally 400s on short/weird transcripts (e.g. a
        single letter from a partial mic pickup); we log and move on.
        """
        if not text.strip():
            return
        processed = preprocess(text, _TTS_PROVIDER)
        t0 = time.monotonic()
        first_frame = True
        try:
            async for chunk in tts.synthesize(processed):
                if first_frame:
                    dt_ms = (time.monotonic() - t0) * 1000
                    logger.info("TTS first-frame: %.0f ms (text=%r)", dt_ms, processed[:60])
                    first_frame = False
                await audio_source.capture_frame(chunk.frame)
        except Exception as exc:  # noqa: BLE001 — deliberate broad catch
            logger.warning("TTS failed for %r: %s", processed[:60], exc)

    async def _drive_stt_from_track(
        track: rtc.Track,
        participant: rtc.RemoteParticipant,
    ) -> None:
        """Pipe a remote audio track -> Deepgram -> _speak on final transcripts."""
        logger.info(
            "STT: attaching to track from identity=%s sid=%s",
            participant.identity,
            track.sid,
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
                    text = speech_ev.alternatives[0].text if speech_ev.alternatives else ""
                    if not text.strip():
                        continue
                    # Latency marker: end-of-speech -> we receive the
                    # final transcript. First-TTS-frame is logged in
                    # _speak. Sum of the two is the user-perceived
                    # round-trip (target < 700ms per CLAUDE.md).
                    if utterance_end_t is not None:
                        asr_ms = (time.monotonic() - utterance_end_t) * 1000
                        logger.info("ASR final: %.0f ms since EOS | %r", asr_ms, text)
                        utterance_end_t = None
                    else:
                        logger.info("ASR final (no EOS anchor): %r", text)
                    await _speak(text)

        # Run audio pump + transcript reader concurrently. Either
        # raising will cancel the other; gather re-raises.
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
        logger.info("Participant left: %s", participant.identity)

    # NOTE: we intentionally do NOT register a listener for byte_stream
    # / `lk.agent.session` topics. Playground sends those every ~5s as
    # session metadata; agent.py logs them and clutters the console.
    # Parrot stays quiet unless there's real audio activity.

    await ctx.connect()
    logger.info(
        "Parrot connected: room=%s local_identity=%s",
        ctx.room.name,
        ctx.room.local_participant.identity,
    )

    # Publish our TTS track so the Playground client starts receiving
    # audio frames the moment we produce them. Publishing before the
    # first _speak call avoids a cold-start delay.
    publish_opts = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    await ctx.room.local_participant.publish_track(agent_track, publish_opts)

    # Gotcha #1 from CLAUDE.md: participant_connected only fires for
    # joins AFTER the agent. For participants who joined before our
    # dispatch (including the typical Playground flow where the user
    # connects, then the agent gets dispatched), we must enumerate
    # the existing remote_participants dict here and hook their
    # already-subscribed tracks.
    for participant in ctx.room.remote_participants.values():
        for publication in participant.track_publications.values():
            if publication.track is not None:
                _attach_if_audio(publication.track, publication, participant)

    # Stay alive until the room tears us down. The framework cancels
    # our entrypoint task when the room ends; the stt_tasks set will
    # propagate cancellation to the per-track pumps.
    try:
        await asyncio.Event().wait()
    finally:
        for task in list(stt_tasks):
            task.cancel()
        await audio_source.aclose()


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
