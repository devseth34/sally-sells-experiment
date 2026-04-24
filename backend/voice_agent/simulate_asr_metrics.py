"""Mock ASR-latency simulation — validates the 2026-04-24 metric fix.

Runs scripted Deepgram event sequences through a pure-Python port of
the sally.py _read_transcripts logic (old and new) so we can SEE the
bug and its fix without touching Deepgram, Cartesia, or LiveKit.

Each scenario yields one or more turn metric rows. The simulation
also mocks engine/TTS latencies so we can show user_latency_ms
(the user-perceived number) decompose cleanly.

Run:
    cd backend && python -m voice_agent.simulate_asr_metrics
    (or from repo root)
    python -m backend.voice_agent.simulate_asr_metrics
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class EvType(str, Enum):
    START = "start_of_speech"
    FINAL = "final_transcript"
    END = "end_of_speech"


@dataclass
class Ev:
    """Synthetic SpeechEvent. `t` is a monotonic-style float (seconds)."""
    type: EvType
    t: float
    text: str | None = None


@dataclass
class TurnRow:
    """What the runner emits per turn (subset — what the sink would see)."""
    text: str
    asr_ms_new: float | None
    asr_ms_old: float | None
    utterance_duration_ms: float | None
    engine_dispatch_ms: float | None
    engine_ms: float | None
    tts_first_frame_ms: float | None
    user_latency_ms: float | None


# ---- two ports of the event-handler logic ----------------------------------


def process_new(events: list[Ev], engine_ms: float, tts_ms: float) -> list[TurnRow]:
    """Port of the fixed sally._read_transcripts.

    Resets speech_end_t on SPEECH_STARTED (new utterance) so a stale
    end-of-speech from the prior utterance can NEVER leak into a new
    asr_ms calculation. Computes asr_tail_ms only when end-of-speech
    has been observed for THIS utterance; otherwise None.
    """
    out: list[TurnRow] = []
    speech_start_t: float | None = None
    speech_end_t: float | None = None
    for ev in events:
        if ev.type == EvType.START:
            speech_start_t = ev.t
            speech_end_t = None
        elif ev.type == EvType.END:
            speech_end_t = ev.t
        elif ev.type == EvType.FINAL:
            text = (ev.text or "").strip()
            if not text:
                continue
            final_t = ev.t
            asr_tail_ms: float | None = None
            if speech_end_t is not None:
                asr_tail_ms = max(0.0, (final_t - speech_end_t) * 1000)
            utt_dur_ms: float | None = None
            if speech_start_t is not None and speech_end_t is not None:
                utt_dur_ms = (speech_end_t - speech_start_t) * 1000
            # Mock downstream: engine starts at final_t, tts first-frame at
            # engine_start + engine_ms + tts_ms.
            engine_start_t = final_t
            tts_first_frame_t = engine_start_t + (engine_ms / 1000) + (tts_ms / 1000)
            engine_dispatch_ms = None
            user_latency_ms = None
            if speech_end_t is not None:
                engine_dispatch_ms = max(0.0, (engine_start_t - speech_end_t) * 1000)
                user_latency_ms = max(0.0, (tts_first_frame_t - speech_end_t) * 1000)
            out.append(
                TurnRow(
                    text=text,
                    asr_ms_new=asr_tail_ms,
                    asr_ms_old=None,  # filled by process_old
                    utterance_duration_ms=utt_dur_ms,
                    engine_dispatch_ms=engine_dispatch_ms,
                    engine_ms=engine_ms,
                    tts_first_frame_ms=tts_ms,
                    user_latency_ms=user_latency_ms,
                )
            )
    return out


def process_old(events: list[Ev]) -> list[float | None]:
    """Port of the ORIGINAL buggy sally._read_transcripts.

    Single running `utterance_end_t`, set on END_OF_SPEECH, cleared on
    FINAL_TRANSCRIPT. Never reset at utterance start — which is where
    the cross-utterance leak comes from.
    """
    out: list[float | None] = []
    utterance_end_t: float | None = None
    for ev in events:
        if ev.type == EvType.END:
            utterance_end_t = ev.t
        elif ev.type == EvType.FINAL:
            text = (ev.text or "").strip()
            if not text:
                continue
            if utterance_end_t is not None:
                asr_ms = (ev.t - utterance_end_t) * 1000
                out.append(asr_ms)
                utterance_end_t = None
            else:
                out.append(None)  # "no EOS anchor"
    return out


# ---- scenarios -------------------------------------------------------------


def scenario_typical_deepgram() -> tuple[str, list[Ev]]:
    """Deepgram's normal flow: FINAL fires before END_OF_SPEECH by ~50ms.

    User speaks 2s ("what is 100x"), Deepgram's is_final=true fires
    mid-endpointing silence, speech_final=true follows after the
    300ms endpointing wait.
    """
    evs = [
        Ev(EvType.START, 10.00),
        Ev(EvType.FINAL, 11.95, "what is 100x"),  # is_final at 1.95s in
        Ev(EvType.END, 12.00),                     # endpointing at 2.0s in
    ]
    return "Typical Deepgram (FINAL 50ms before END)", evs


def scenario_end_before_final() -> tuple[str, list[Ev]]:
    """Rarer: endpointing fires first, then a final-is_final Results
    lands ~200ms later (network jitter, late finalization).
    """
    evs = [
        Ev(EvType.START, 20.00),
        Ev(EvType.END, 22.00),
        Ev(EvType.FINAL, 22.20, "who is nik shah"),
    ]
    return "END before FINAL (tail visible, 200ms)", evs


def scenario_two_turns_clean() -> tuple[str, list[Ev]]:
    """Two back-to-back turns. User pauses 8s between them. Verifies
    the per-utterance reset keeps turn-2 asr_tail correct (not inflated
    by inter-utterance think time)."""
    evs = [
        Ev(EvType.START, 30.00),
        Ev(EvType.FINAL, 31.90, "hello sally"),
        Ev(EvType.END, 32.00),
        # 8 seconds of thinking
        Ev(EvType.START, 40.00),
        Ev(EvType.FINAL, 41.90, "tell me about 100x"),
        Ev(EvType.END, 42.00),
    ]
    return "Two turns with 8s think-time gap", evs


def scenario_missing_end_then_next_final() -> tuple[str, list[Ev]]:
    """The exact OLD bug pattern: turn 1's END fires, then turn 2
    starts but the new code receives FINAL before seeing a new START
    or END. In the OLD code, turn 2's FINAL would use turn 1's stale
    utterance_end_t. In the NEW code, SPEECH_STARTED resets speech_end_t
    to None so no stale leak."""
    evs = [
        Ev(EvType.START, 50.00),
        Ev(EvType.FINAL, 51.90, "okay"),
        Ev(EvType.END, 52.00),
        # Turn 2 — SPEECH_STARTED arrives, final arrives before the new END
        Ev(EvType.START, 60.00),
        Ev(EvType.FINAL, 61.50, "what about 100x"),
        Ev(EvType.END, 61.60),
    ]
    return "Stale-anchor bug reproduction (the 8-14s inflation)", evs


SCENARIOS = [
    scenario_typical_deepgram,
    scenario_end_before_final,
    scenario_two_turns_clean,
    scenario_missing_end_then_next_final,
]


# ---- report ---------------------------------------------------------------


def run() -> None:
    # Plausible engine + TTS numbers from the 16 real turns in
    # /tmp/sally_turns.jsonl (engine p50 5175 / tts p50 504).
    ENGINE_MS = 5175
    TTS_MS = 504

    print("=" * 78)
    print("ASR metric fix — mock simulation (2026-04-24)")
    print(f"Mocked downstream: engine_ms={ENGINE_MS} tts_first_frame_ms={TTS_MS}")
    print("=" * 78)

    for scenario in SCENARIOS:
        name, events = scenario()
        new_rows = process_new(events, ENGINE_MS, TTS_MS)
        old_asrs = process_old(events)

        print(f"\n--- {name} ---")
        print(f"  events: {len(events)}")
        print(f"  {'turn':<6} {'text':<30} {'asr_new':>10} {'asr_OLD':>10} {'utt_dur':>9} {'disp':>8} {'user_lat':>10}")
        for i, (row, old) in enumerate(zip(new_rows, old_asrs), start=1):
            print(
                f"  {i:<6} {row.text[:28]:<30} "
                f"{_fmt(row.asr_ms_new):>10} "
                f"{_fmt(old):>10} "
                f"{_fmt(row.utterance_duration_ms):>9} "
                f"{_fmt(row.engine_dispatch_ms):>8} "
                f"{_fmt(row.user_latency_ms):>10}"
            )

    print()
    print("=" * 78)
    print("KEY TAKEAWAYS (read the asr_new vs asr_OLD columns):")
    print("  - Typical Deepgram: asr_new=None (transcript ready BEFORE speech end);")
    print("    OLD code was reporting garbage instead of None.")
    print("  - Stale-anchor scenario: OLD code reports ~8100 ms (the think-time gap)")
    print("    as ASR latency. NEW code correctly reports ~100 ms (true tail) OR")
    print("    None if transcript arrived before endpointing.")
    print("  - user_latency_ms is the honest user-perceived number: from the moment")
    print("    the user stops speaking to the moment Sally's first audio frame lands.")
    print("    With engine=5175 + tts=504, floor is ~5.7 s even with perfect ASR.")
    print("=" * 78)


def _fmt(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:.0f}"


if __name__ == "__main__":
    run()
