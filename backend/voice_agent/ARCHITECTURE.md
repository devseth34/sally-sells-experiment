# Voice Agent Architecture

> **Last updated:** 2026-04-25  
> **Branch:** `phase-2-voice`  
> **Status:** Day 4 complete — full NEPQ engine wired, metrics running

---

## Table of Contents

1. [Overview](#1-overview)
2. [Repository Layout](#2-repository-layout)
3. [Entry Points](#3-entry-points)
4. [End-to-End Data Flow](#4-end-to-end-data-flow)
5. [Module Reference](#5-module-reference)
   - [agent.py](#agentpy--day-2a-hello-world)
   - [parrot.py](#parrotpy--day-3-asr-tts-round-trip)
   - [sally.py](#sallypy--day-4-orchestrator)
   - [sally_voice_runner.py](#sally_voice_runnerpy--turn-loop)
   - [engine_adapter.py](#engine_adapterpy--async-engine-bridge)
   - [personalities.py](#personalitiespy--voice-lock-table)
   - [assignment.py](#assignmentpy--personality-picker)
   - [pronunciation.py](#pronunciationpy--lexicon-preprocessor)
   - [stt.py](#sttpy--deepgram-factory)
   - [tts.py](#ttspy--tts-factory)
   - [backchannel.py](#backchannelpy--filler-injector)
   - [voice_fast_path.py](#voice_fast_pathpy--trivial-utterance-shortcut)
   - [metrics.py](#metricspy--per-turn-observability)
   - [cds_rollup.py](#cds_rolluppy--analysis-cli)
   - [simulate_asr_metrics.py](#simulate_asr_metricspy--asr-metric-validator)
   - [Stubs (Day 5+)](#stubs-day-5)
6. [Personality System](#6-personality-system)
7. [Timing & Latency Budget](#7-timing--latency-budget)
8. [Critical Design Decisions](#8-critical-design-decisions)
9. [Pronunciation Landmines](#9-pronunciation-landmines)
10. [Metrics & CDS](#10-metrics--cds)
11. [Testing](#11-testing)
12. [Deployment](#12-deployment)
13. [Known Issues & Blockers](#13-known-issues--blockers)
14. [Frozen Files Policy](#14-frozen-files-policy)

---

## 1. Overview

The voice agent wraps the **frozen Phase 1 NEPQ sales engine** (`backend/app/agent.py`) with a real-time voice pipeline: LiveKit WebRTC in/out, Deepgram Nova-3 ASR, and Cartesia/ElevenLabs TTS. Three voice personalities (Warm / Confident / Direct) each map to an existing engine arm.

**Kill date:** 2026-05-09  
**Success gate:** CDS ≥ +0.35 across ≥40 valid voice sessions vs. chat baseline

The Phase 1 chat product (`backend/app/`) is **frozen** — no modifications, not even whitespace. All voice-specific code lives in `backend/voice_agent/`.

---

## 2. Repository Layout

```
backend/voice_agent/
│
│  ─── Entry Points ──────────────────────────────────────────
│  agent.py              Day 2A: hello-world LiveKit worker (events only)
│  parrot.py             Day 3: Deepgram→preprocess→Cartesia echo loop
│  sally.py              Day 4: full orchestrator (production entry point)
│
│  ─── Core Runtime ──────────────────────────────────────────
│  sally_voice_runner.py Turn serialization, TTS pacing, backchannel scheduling
│  engine_adapter.py     Async wrapper around frozen SallyEngine
│
│  ─── Configuration ─────────────────────────────────────────
│  personalities.py      Locked voice table (Jessica / Alice / Thandi)
│  assignment.py         Uniform-random personality pick per call
│  pronunciation.py      LEXICON: written→spoken substitutions pre-TTS
│
│  ─── Pipeline Modules ──────────────────────────────────────
│  stt.py                Deepgram Nova-3 factory
│  tts.py                Cartesia / ElevenLabs factory (personality dispatch)
│  backchannel.py        Mid-engine filler injection ("mhm", "yeah")
│  voice_fast_path.py    Pattern-match shortcut for single-word turns
│
│  ─── Observability ─────────────────────────────────────────
│  metrics.py            TurnMetrics dataclass + JSONL sink
│  cds_rollup.py         JSONL → latency/phase/arm analysis CLI
│  simulate_asr_metrics.py  Validates 2026-04-24 asr_ms metric fix
│
│  ─── Stubs (Day 5+) ────────────────────────────────────────
│  pause_manager.py      Per-phase post-response silence (not wired)
│  streaming_validator.py Sentence-boundary TTS validator (not wired)
│  cost_guard.py         Cost caps + concurrency guardrails (not wired)
│  voice_legitimacy.py   Voice-specific legitimacy scoring (not wired)
│
│  ─── Deployment ────────────────────────────────────────────
│  Dockerfile            python:3.11-slim image
│  fly.toml              Fly.io config (shared-cpu-1x, region iad)
│  requirements.txt      All deps (voice + Phase 1 bridge)
│
│  ─── Tests ─────────────────────────────────────────────────
│  test_assignment.py
│  test_backchannel.py
│  test_engine_adapter.py
│  test_integration.py
│  test_metrics.py
│  test_pronunciation.py
```

---

## 3. Entry Points

Three runnable modules, each a strict superset of the previous:

| Module | Day | Purpose | Status |
|--------|-----|---------|--------|
| `agent.py` | 2A | Join LiveKit room, log events, do nothing | ✅ done |
| `parrot.py` | 3 | Deepgram → preprocess → Cartesia echo | ✅ done |
| `sally.py` | 4 | Full NEPQ engine + personalities + backchannels + metrics | ✅ done |

**Run any entry point:**
```bash
source venv/bin/activate
python -m backend.voice_agent.sally dev      # production
python -m backend.voice_agent.parrot dev     # pipeline smoke-test
python -m backend.voice_agent.agent dev      # hello-world
```

**Test client:** [https://agents-playground.livekit.io/](https://agents-playground.livekit.io/) — enter `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` from `.env`.

---

## 4. End-to-End Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│  LiveKit Room (WebRTC)                                          │
│  User speaks → remote audio track → AudioStream                │
└───────────────────────────┬─────────────────────────────────────┘
                            │ 16 kHz mono PCM
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  stt.py  —  Deepgram Nova-3                                     │
│  • endpointing_ms=300 (conversational VAD)                      │
│  • interim_results=True (for future backchannel triggers)       │
│  • keyterms from pronunciation.LEXICON (ASR bias)               │
│  • smart_format=False, punctuate=True, filler_words=True        │
└───────────────────────────┬─────────────────────────────────────┘
                            │ SpeechEvents stream
                            │   START_OF_SPEECH   → record speech_start_t
                            │   interim Results   → (future: EOT backchannel)
                            │   FINAL_TRANSCRIPT  → record final_t, call engine
                            │   END_OF_SPEECH     → record speech_end_t
                            │
                            │  ⚠ FINAL fires BEFORE END in Deepgram's ordering.
                            │    asr_ms = max(0, final_t - speech_end_t)
                            │    (often ≈ 0ms; negative means instant)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  voice_fast_path.py  —  Pattern Match                           │
│  • Regex whole-string match on FINAL_TRANSCRIPT text            │
│  • Hit: synthesize stub ComprehensionOutput, skip Layer 1       │
│    Saves 700–1000ms for ~30% of turns (greetings, yes/no, bye)  │
│  • Miss: fall through to engine                                 │
└──────────┬────────────────────────────────────────────────────┬─┘
           │ transcript text                                    │ fast-path stub
           ▼                                                    │
┌──────────────────────────────────────────┐                   │
│  engine_adapter.py  —  SallyEngineAdapter│                   │
│  • asyncio.to_thread(SallyEngine.process_turn, ...)          │
│  • SallyEngine layers (all in frozen app/):                  │
│      Layer 1: Gemini Flash comprehension  (~1200ms)          │
│      Layer 2: decision.py (pure logic)    (<10ms)            │
│      Layer 3: Claude Sonnet response      (~1300ms)          │
│  • Total engine: ~1500–2500ms                                │
│  • Threads state back: phase, profile_json, 8 counters       │
└────────────────┬─────────────────────────┘                   │
                 │ response_text, ended                        │
                 │                                             │
                 │  ┌───────────────────────────────────────┐  │
                 │  │ backchannel.py  (parallel task)       │  │
                 │  │ • Scheduled at START of on_user_turn  │  │
                 │  │ • Sleeps _BACKCHANNEL_DELAY_S (500ms) │  │
                 │  │ • If engine still running at 500ms:   │  │
                 │  │     pick phrase, acquire audio_lock,  │  │
                 │  │     speak filler via TTS              │  │
                 │  │ • Cancelled if engine returns first   │  │
                 │  └───────────────────────────────────────┘  │
                 │                                             │
                 ▼                                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  pronunciation.py  —  preprocess(text, tts_provider)            │
│  • Whole-word LEXICON substitutions (longest-key-first order)   │
│  • "Nik Shah"→"Nick Shah", "NEPQ"→"N-E-P-Q", "CDS"→"C-D-S"    │
│  • "P&L"→"P and L", "$10,000"→"ten thousand dollars", etc.     │
└───────────────────────────┬─────────────────────────────────────┘
                            │ preprocessed text
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  tts.py  —  Provider Dispatch                                   │
│  • Cartesia sonic-2-2025-03-07  (Thandi / sally_direct)        │
│      24 kHz mono PCM, ~90ms first-frame                        │
│  • ElevenLabs eleven_flash_v2_5  (Jessica or Alice)            │
│      pcm_24000, speaking_rate via voice_settings, ~75ms        │
│  • audio_lock serializes filler vs. real response              │
└───────────────────────────┬─────────────────────────────────────┘
                            │ audio chunks (24 kHz)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│  AudioSource.capture_frame()  →  LiveKit RTC  →  User hears    │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼ pause_s sleep (personality-scaled)
┌─────────────────────────────────────────────────────────────────┐
│  metrics.py  —  TurnMetrics emit                                │
│  /tmp/sally_turns.jsonl  (one JSONL row per turn)               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. Module Reference

### `agent.py` — Day 2A Hello-World

**Purpose:** Minimal LiveKit worker that joins rooms and logs events. No ASR/TTS. Useful for verifying LiveKit connectivity and room dispatch in isolation.

**Entry point:**
```python
cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
```

**`entrypoint(ctx: JobContext) -> None`**  
Registers four event handlers (participant_connected, participant_disconnected, track_subscribed, track_unsubscribed), then calls `ctx.connect()`. Stays alive until the framework tears it down.

**Key behavior:** Handlers are registered BEFORE `ctx.connect()` to avoid a race where a participant connects during setup.

---

### `parrot.py` — Day 3 ASR→TTS Round-Trip

**Purpose:** Proves the audio pipeline works end-to-end before wiring the real engine. User speaks → Deepgram Nova-3 transcribes → `pronunciation.preprocess()` → Cartesia Thandi echoes back. No Sally brain.

**Constants:**
```python
_PERSONALITY    = "sally_direct"          # tightest pacing for latency stress-test
_TTS_PROVIDER   = "cartesia"
_TTS_SAMPLE_RATE = 24000
_TTS_CHANNELS   = 1
_STT_SAMPLE_RATE = 16000
_STT_CHANNELS   = 1
```

**Key functions (defined inside `entrypoint`):**

`_speak(text)` — preprocesses text, measures TTS first-frame latency, streams chunks to `audio_source`.

`_drive_stt_from_track(track, participant)` — creates `AudioStream.from_track()`, runs two concurrent coroutines: `_pump_audio()` feeds frames to STT; `_read_transcripts()` awaits FINAL_TRANSCRIPT events and calls `_speak()`. Logs ASR tail latency on each FINAL.

`_attach_if_audio(track, publication, participant)` — deduplication guard: checks `publication.sid` against `attached_track_sids` set before spawning an STT task (prevents double-attachment from event + post-connect enumeration both firing for the same track).

**LiveKit gotcha handled:** After `ctx.connect()`, enumerates `ctx.room.remote_participants` explicitly, because `participant_connected` only fires for participants who join AFTER the agent.

**Success criteria:** Speak "Tell Nik Shah about the NEPQ arm and the CDS score" → hear "Tell Nick Shah about the N-E-P-Q arm and the C-D-S score" within ~2s.

---

### `sally.py` — Day 4 Orchestrator

**Purpose:** Full production entry point. Assigns a personality, builds the STT/TTS stack and `SallyVoiceRunner`, handles the LiveKit event loop, and fires `runner.open()` to speak Sally's greeting.

**Startup sequence:**
1. `load_dotenv()` from repo root (loads all API keys)
2. `install_comprehension_capture()` — attaches L1 model log tap (idempotent)
3. `assign_personality()` — one draw per call
4. `make_stt()`, `make_tts(personality)` — build pipeline
5. Create `AudioSource(24000, 1)` + `LocalAudioTrack`
6. Create `SallyVoiceRunner(personality, tts, audio_source, ...)`
7. Register event handlers; `ctx.connect()`
8. Publish agent track
9. Enumerate pre-existing participants (LiveKit gotcha)
10. `await runner.open()` — speaks greeting, acquires turn_lock so early ASR finals are dropped until greeting finishes
11. Wait for `shutdown_event`

**STT event timing (critical detail):**
```python
# Event order: START_OF_SPEECH → interim → FINAL_TRANSCRIPT → END_OF_SPEECH
# FINAL usually fires BEFORE END — so asr_ms = max(0, final_t - speech_end_t)
# speech_end_t reset to None on START so stale values never leak across turns
```

On FINAL_TRANSCRIPT: `asyncio.create_task(runner.on_user_turn(text, asr_ms=..., speech_end_t=..., utterance_duration_ms=...))` — does NOT await (allows next ASR read to proceed while engine call is in flight).

**Shutdown:** fires when `participant_disconnected` leaves the last remote participant, or when `runner._on_session_end` is called. Cancels STT tasks, closes audio_source.

---

### `sally_voice_runner.py` — Turn Loop

**Purpose:** Serializes turn processing, manages TTS pacing, schedules backchannels, emits per-turn metrics. The central orchestrator between ASR events and engine + TTS output.

**Constants:**
```python
_BACKCHANNEL_DELAY_S    = 0.5    # fire filler if engine takes longer than this
_BASE_POST_RESPONSE_PAUSE_S = 0.3
_ENGINE_FALLBACK        = "Sorry, one moment."
```

**Per-call state:**
```
_personality            str     — e.g., "sally_warm"
_tts_provider           str     — from PERSONALITIES table
_pause_s                float   — _BASE_POST_RESPONSE_PAUSE_S × pause_multiplier
_tts                    TTS     — from make_tts()
_audio_source           AudioSource
_adapter                SallyEngineAdapter
_turn_lock              asyncio.Lock   — serializes on_user_turn calls
_audio_lock             asyncio.Lock   — serializes backchannel vs. real TTS
_on_session_end         callback
_metrics_sink           MetricsSink | None
_call_id                str     — LiveKit job.id
_turn_index             int
_recently_used_backchannels  list[str]  — last 2 phrases for dedup
_last_backchannel_at    float   — monotonic() of last fired backchannel
```

**`open() -> None`** (async)  
Called once after room connect + track publish. Acquires `_turn_lock` exclusively, gets greeting via `adapter.opener()`, speaks it. Any ASR finals that arrive while `_turn_lock` is held are dropped (guard in `on_user_turn`).

**`on_user_turn(transcript, *, asr_ms, speech_end_t, utterance_duration_ms) -> None`** (async)  
The hot path. Guards: empty transcript → return; session ended → return; turn_lock held → log and return (drops concurrent ASR finals during engine call).

Inside the lock:
1. Schedule `_fire_backchannel_during_engine()` task
2. Record `engine_start_t`
3. `await adapter.turn(transcript)` → `(response_text, ended)`
4. Compute `engine_ms`
5. On exception: cancel backchannel, speak fallback, emit metrics, return
6. Cancel backchannel task
7. `await _speak(response_text)` → `(first_frame_ms, first_frame_t)`
8. Sleep `_pause_s`
9. Compute `user_latency_ms = first_frame_t - speech_end_t`
10. Emit metrics
11. If `ended`: call `_on_session_end()`

**`_speak(text) -> tuple[first_frame_ms, first_frame_t]`** (async)  
Preprocesses via `pronunciation.preprocess()`, acquires `_audio_lock`, iterates TTS chunks into `audio_source`. Records first-frame timing. Returns `(None, None)` on TTS failure (non-fatal).

**`_fire_backchannel_during_engine()` task** (async)  
Sleeps `_BACKCHANNEL_DELAY_S`. On wake: checks `should_fire_mid_engine(personality, phase, seconds_since_last)`. If true: `pick_backchannel(personality, recently_used)` → `_speak(phrase)`. Updates `_last_backchannel_at`. Swallows synthesis exceptions. Re-raises `CancelledError` so the task enters cancelled state cleanly.

**Turn lock rationale:** Drops concurrent ASR finals while an engine call is in flight. Crude but safe for Day 4; barge-in / interruption handling is Day 5+ scope.

**Audio lock rationale:** Prevents audible overlap when engine returns while a filler is still playing. Backchannel acquires `_audio_lock` first; real response waits for it to release.

**Latency formula:**
```
user_latency_ms = engine_dispatch_ms + engine_ms + tts_first_frame_ms
```

---

### `engine_adapter.py` — Async Engine Bridge

**Purpose:** The only code that touches `backend/app/agent.py`. Makes the synchronous `SallyEngine.process_turn()` (~1.5–2.5s) safe for asyncio via `asyncio.to_thread()`, and maintains per-call state across turns (the engine itself is stateless).

**Import bridge (critical):**
```python
sys.path.insert(0, str(_BACKEND_DIR))  # so "from app.agent import SallyEngine" resolves
load_dotenv(_REPO_ROOT / ".env", override=True)  # override=True: subprocess children
                                                  # inherit empty env vars from parent
from app.agent import SallyEngine
from app.schemas import NepqPhase
```

**Per-call state initialized in `__init__`:**
```
_personality            str
_arm_key                str     — from PERSONALITIES[personality]["engine_arm"]
_history                list[dict]  — alternating user/assistant dicts
_phase                  NepqPhase   — starts CONNECTION
_profile_json           str     — prospect profile JSON, starts "{}"
_turn_number            int     — starts 0
_retry_count            int
_consecutive_no_new_info int
_turns_in_current_phase int
_deepest_emotional_depth str    — starts "surface"
_objection_diffusion_step int
_ownership_substep      int
_start_time             float   — frozen at construction (for pacing heuristics)
_memory_context         str     — cross-session memory (empty Day 4; DB-backed Day 5+)
_ended                  bool
_last_turn_stats        dict
```

**Properties:** `personality`, `arm_key`, `ended`, `current_phase` (returns `_phase.value`), `last_turn_stats`.

**`opener() -> str`**  
`SallyEngine.get_greeting()` — static call, no turn counter increment.

**`async turn(user_message: str) -> tuple[str, bool]`**  
1. Guard: if `_ended`, return `("", True)`
2. Increment `_turn_number`, append user message to history
3. `engine_result = await asyncio.to_thread(SallyEngine.process_turn, ...)`  
   Passes all per-call state fields as kwargs
4. Threads state back from result: `_phase`, `_profile_json`, all 6 counters, `_ended`
5. Appends assistant response to history
6. Populates `_last_turn_stats` and logs
7. Returns `(response_text, ended)`

**`snapshot_state() -> dict`**  
Debug dump: `{turn, phase, history_len, ended, profile}`. Not for persistence.

---

### `personalities.py` — Voice Lock Table

**Purpose:** Single source of truth for the three locked voices and their pacing parameters. Do NOT change voice IDs mid-experiment.

```python
PERSONALITIES: dict[str, dict] = {
    "sally_warm": {
        "engine_arm":                    "sally_empathy_plus",
        "tts_provider":                  "elevenlabs",
        "tts_voice_id":                  "cgSgspJ2msm6clMCkdW9",  # Jessica
        "speaking_rate":                 0.90,
        "backchannel_density":           "high",
        "post_response_pause_multiplier": 1.2,
    },
    "sally_confident": {
        "engine_arm":                    "sally_nepq",
        "tts_provider":                  "elevenlabs",
        "tts_voice_id":                  "Xb7hH8MSUJpSbSDYk0k2",  # Alice
        "speaking_rate":                 0.92,
        "backchannel_density":           "medium",
        "post_response_pause_multiplier": 1.0,
    },
    "sally_direct": {
        "engine_arm":                    "sally_direct",
        "tts_provider":                  "cartesia",
        "tts_voice_id":                  "692846ad-1a6b-49b8-bfc5-86421fd41a19",  # Thandi
        "speaking_rate":                 1.1,
        "backchannel_density":           "low",
        "post_response_pause_multiplier": 0.85,
    },
}
```

**Audition scoring rubric (locked 2026-04-19):**  
`score = warmth × 1.0 + clarity × 1.2 + trust × 1.3 + naturalness × 1.5` (max 25.0)

Why trust + naturalness weighted highest: hardest dims to fake in a sales context; low scores on either make prospects uncomfortable regardless of other strengths.

**Why Alice (ElevenLabs) for sally_confident instead of Cartesia:** Cartesia's confident voice field was thin — 7/10 Cartesia voices scored 1/1/1/1. Linda (best Cartesia confident) scored 12.20. Alice scored 18.50 with Flash v2.5 latency (~75ms) actually faster than Sonic-2 (~90ms). Provider diversity preserved via Thandi on Cartesia for Direct.

---

### `assignment.py` — Personality Picker

**Purpose:** Returns one personality per voice call via uniform random.

```python
_ARMS: Final[tuple] = ("sally_warm", "sally_confident", "sally_direct")
_DEFAULT_RNG = random.SystemRandom()  # reads os.urandom; safe across forked subprocesses

def assign_personality(stratum: str | None = None, *, rng: random.Random | None = None) -> str
```

`stratum` accepted but ignored — reserved for Day 5 stratified random (§B11). `rng` injectable for deterministic tests. Logs `assignment_method: "uniform_random_day4"` so Day 5 can filter Day 4 draws from CDS math if needed.

**Why not the chat product's balanced allocation:** Chat counts sessions per arm via DB query (main.py:660–687). Voice calls don't persist to DB yet (Day 5). Uniform random over ≥40 sessions is close enough for CDS calibration.

---

### `pronunciation.py` — Lexicon Preprocessor

**Purpose:** Applies written→spoken substitutions between engine output and the TTS call. Without this, Cartesia/ElevenLabs mispronounce brand/jargon terms on the first encounter.

```python
LEXICON: dict[str, str] = {
    "Nik Shah":  "Nick Shah",       # "Nik" → "Nick" prevents "Nike"
    "NEPQ":      "N-E-P-Q",
    "CDS":       "C-D-S",
    "100x":      "one hundred X",
    "AI":        "A-I",
    "$10,000":   "ten thousand dollars",
    "$5M":       "five million dollars",
    "TidyCal":   "tidy cal",
    "Sally":     "Sally",
    "Layer 1":   "layer one",
    "Layer 2":   "layer two",
    "Layer 3":   "layer three",
    "ASR":       "A-S-R",
    "TTS":       "T-T-S",
    "SMS":       "S-M-S",
    "P&L":       "P and L",        # "pandle"/"panel" on Flash v2.5 without this
    "P and L":   "P and L",        # identity keeps already-correct form stable
}
```

**Pattern compilation:**
```python
_ORDERED_KEYS = sorted(LEXICON.keys(), key=len, reverse=True)  # longest-first → no substring collision
_PATTERNS = [
    (re.compile(r"(?<!\w)" + re.escape(k) + r"(?!\w)", re.IGNORECASE), LEXICON[k])
    for k in _ORDERED_KEYS
]
```

`(?<!\w)/(?!\w)` instead of `\b`: `\b` is undefined around non-word chars like `$` and `&`. The lookaround pair correctly anchors `$10,000`, `P&L`, and `100x` (no match inside `1100x`).

**`preprocess(text: str, tts_provider: str) -> str`**  
`tts_provider` accepted but unused (advisory for future per-provider phoneme tags). Applies all patterns in longest-first order. Safe for concurrent calls.

**Provider-specific phoneme fallback** (if lexicon substitution drifts in a future model refresh):
```
Cartesia:    <phoneme alphabet="ipa" ph="ʃɑː">Shah</phoneme>
ElevenLabs:  <phoneme alphabet="ipa" ph="ʃɑː">Shah</phoneme>  (SSML)
```

---

### `stt.py` — Deepgram Factory

**Purpose:** Single place to configure Deepgram Nova-3 for sales-call context. Both `parrot.py` and `sally.py` call `make_stt()`.

**`make_stt() -> deepgram.STT`**
```python
deepgram.STT(
    model="nova-3",
    language="en-US",
    interim_results=True,   # fast feedback; needed for Day 6 EOT backchannel triggers
    smart_format=False,     # we run our own pronunciation pass; smart_format would
                            # pre-convert "$10,000" before the lexicon sees it
    punctuate=True,
    filler_words=True,      # "um"/"uh" kept for Layer 2 disfluency detection
    endpointing_ms=300,     # 25ms (prior value) fired premature EOS on every micro-gap,
                            # inflating observed asr_ms to 8-14s during Day 6 feel-check
    keyterm=_KEYTERMS,      # canonical written forms from LEXICON.keys()
)
```

`_KEYTERMS = list(LEXICON.keys())` — single source of truth with `pronunciation.py`. Deepgram prefers canonical written form (not phonetic hint) for keyterms.

---

### `tts.py` — TTS Factory

**Purpose:** Resolve personality key → configured TTS provider instance. All provider dispatch, model pinning, and encoding config lives here.

**`make_tts(personality_key: str) -> lk_tts.TTS`**

**Cartesia path (sally_direct / Thandi):**
```python
cartesia.TTS(
    model="sonic-2-2025-03-07",  # DATED SNAPSHOT — not alias "sonic-2"
                                  # pins behavior to what Nik signed off on 2026-04-19
    voice=voice_id,
    sample_rate=24000,
    # speed: INTENTIONALLY DROPPED
    # livekit-plugins-cartesia 1.5.4 hardcodes `Cartesia-Version: 2025-04-16`
    # regardless of api_version kwarg. On that API version, sonic-2 rejects
    # `speed` with HTTP 400. Confirmed by smoke-test 2026-04-19.
    # Unblocked by: (a) vendor plugin + swap header, (b) upgrade to sonic-3
    # (requires re-auditioning + Nik approval), or (c) wait for plugin 1.6+
)
```

**ElevenLabs path (sally_warm / jessica, sally_confident / alice):**
```python
elevenlabs.TTS(
    model="eleven_flash_v2_5",
    voice_id=voice_id,
    api_key=os.environ.get("ELEVENLABS_API_KEY") or os.environ.get("ELEVEN_API_KEY"),
    encoding="pcm_24000",       # REQUIRED: default mp3_22050_32 causes sample-rate
                                 # mismatch with 24kHz AudioSource → RtcError on publish
                                 # AND wastes CPU decoding mp3 in realtime pipeline
    voice_settings=elevenlabs.VoiceSettings(
        speed=speed,            # honors speaking_rate from PERSONALITIES table
        stability=0.5,
        similarity_boost=0.75,
    ),
)
```

ElevenLabs import is **lazy** (inside the `if provider == "elevenlabs":` block) to keep parrot.py cold-start fast and isolate ElevenLabs install issues from Day 3 dev runs.

---

### `backchannel.py` — Filler Injector

**Purpose:** Fires "mhm/yeah/got it" while the engine is processing to mask ~1.5–2.5s latency. Makes the conversation feel engaged rather than dead.

**Phrase pools:**
```python
BACKCHANNELS = {
    "warm":      ["mhm", "yeah", "uh-huh", "okay", "got it", "right", "I hear you"],
    "confident": ["mhm", "got it", "okay", "right"],
    "direct":    ["mhm", "okay", "right"],
}
```

**Density multipliers:**
```python
PROBABILISTIC_MULTIPLIER = {
    "warm":      1.00,   # fire every eligible turn
    "confident": 0.30,   # ~30% probabilistic
    "direct":    0.00,   # never
}
MIN_INTERVAL_SEC = 8.0   # throttle repeated fillers
```

**`pick_backchannel(personality, recently_used, *, rng) -> str`**  
Avoids last 2 used phrases. Falls back to "any except most recent" if pool exhausted by recency guard.

**`should_fire_mid_engine(*, personality, phase, seconds_since_last, rng) -> bool`**  
Gating order (first False wins):
1. `phase == "CONNECTION"` → False
2. `seconds_since_last < MIN_INTERVAL_SEC` → False
3. `mult <= 0.0` → False
4. `mult >= 1.0` → True
5. `random() < mult` → probabilistic

**`should_fire_backchannel(...)` (Day 6+ EOT-semantic scaffold)**  
Not wired into runner today. Additional gates: fast-path match → False; utterance < 1.0s → False. Fire on ALWAYS_PHASES + utterance ≥ 6s; emotion markers in interim transcript; probabilistic if 3–6s utterance.

`ALWAYS_PHASES = {"PROBLEM_AWARENESS", "CONSEQUENCE", "OWNERSHIP"}`

`EMOTION_MARKER_RE = re.compile(r"(frustrat|stuck|tired|overwhelm|worr|stress|anxio)", re.IGNORECASE)`

---

### `voice_fast_path.py` — Trivial Utterance Shortcut

**Purpose:** ~30% of voice turns in early NEPQ phases are single-word (greeting, yes, no, bye). Running full Gemini Flash comprehension on "yeah" costs 700–1000ms for zero semantic gain. This module pattern-matches those turns and synthesizes a stub `ComprehensionOutput` directly, skipping Layer 1.

```python
FAST_PATH_PATTERNS = {
    "greeting":     regex=r"^(hi|hey|hello)[\s!.]*$",           action="STAY"
    "confirmation": regex=r"^(yes|yeah|yep|sure|ok|okay|...)$", action="STAY",  profile_delta={"agreement": True}
    "negation":     regex=r"^(no|nope|nah)[\s!.]*$",            action="STAY",  profile_delta={"disagreement": True}
    "session_end":  regex=r"^(bye|goodbye|gotta go|...)$",       action="END"
    "filler":       regex=r"^(uh|um|hmm|mhm|uh-huh|let me think)[\s!.]*$",
                    action="STAY", notes="user still holding turn; no response"
}
```

**`match(transcript: str) -> tuple[str, dict] | None`**  
Returns `(intent, pattern_info)` on first regex match, `None` if no match. All patterns are whole-string, case-insensitive.

**Filler special case:** "uh"/"um"/"hmm" → user still holding the turn. Do NOT respond; reset EOT timer and wait for more.

---

### `metrics.py` — Per-Turn Observability

**Purpose:** Emit one JSONL row per completed user turn. All CDS-grade measurements live here.

**L1 model capture (key design):**  
`SallyEngine.process_turn()` runs via `asyncio.to_thread()`. The frozen comprehension layer logs "Layer 1 completed with model: X" but doesn't return the model name. A `logging.Filter` on `"sally.comprehension"` taps that log and stashes the model name in a module-level global.

Why NOT a ContextVar: `asyncio.to_thread()` copies the context into the worker thread and discards the copy on return — mutations inside the thread never reach the main asyncio thread. The module global survives because both threads share module state. GIL-safe because `turn_lock` ensures at most one in-flight engine call per runner subprocess.

```python
_last_l1_model: Optional[str] = None
_L1_MODEL_RE = re.compile(r"Layer 1 completed with model:\s*(\S+)")

class _ComprehensionLogFilter(logging.Filter):
    def filter(self, record) -> bool:
        global _last_l1_model
        m = _L1_MODEL_RE.search(record.getMessage())
        if m:
            _last_l1_model = m.group(1)
        return True  # tap, not suppressor

def install_comprehension_capture() -> None: ...  # idempotent, call at process start
def consume_turn_l1_model() -> Optional[str]: ...  # read-and-clear after adapter.turn()
```

**`TurnMetrics` dataclass:**
```python
call_id: str                         # LiveKit job.id — stable for entire call
turn_index: int                      # 0-based counter per call
personality: str                     # "sally_warm" / "sally_confident" / "sally_direct"
arm: str                             # "sally_empathy_plus" / "sally_nepq" / "sally_direct"
phase: str                           # NEPQ phase name at turn end
phase_changed: bool                  # True if phase advanced this turn
user_text: str                       # ASR FINAL_TRANSCRIPT text
sally_text: str                      # engine response (or fallback phrase)
asr_ms: Optional[float]             # post-speech ASR tail: max(0, final_t - speech_end_t)
engine_ms: Optional[float]          # SallyEngine.process_turn() duration
l1_model: Optional[str]             # "gemini-2.5-flash-lite" or fallback model name
tts_first_frame_ms: Optional[float] # time from synthesize() call to first audio chunk
ended: bool                          # session_ended flag from engine
utterance_duration_ms: Optional[float] = None   # speech_end_t - speech_start_t
engine_dispatch_ms: Optional[float] = None      # FINAL_TRANSCRIPT → engine starts
user_latency_ms: Optional[float] = None         # speech_end_t → tts_first_frame_t
timestamp: float = field(default_factory=time.time)
```

**Latency decomposition (fixed 2026-04-24):**
```
user_latency_ms = engine_dispatch_ms + engine_ms + tts_first_frame_ms
```
`engine_dispatch_ms ≈ asr_ms` (differ by a few ms of coroutine scheduling overhead). `user_latency_ms` is the canonical user-perceived headline metric.

**`asr_ms` history:** Before 2026-04-24, code measured inter-utterance gap instead of post-speech tail. The bug: `utterance_end_t` was set on END_OF_SPEECH and never reset at the next START_OF_SPEECH, so turn 2's `asr_ms` measured the gap between turn 1's END and turn 2's FINAL (8+ seconds in a normal conversation). Fixed by resetting `speech_end_t = None` on START_OF_SPEECH.

**`MetricsSink`:**
```python
class MetricsSink:
    def __init__(self, path: Path) -> None    # creates parent dirs
    def emit(self, metrics: TurnMetrics) -> None  # appends one JSON line
```
Opens and closes the file per `emit()` (no persistent handle). Multiple subprocesses write to the same file; rows interleaved but self-describing via `call_id`.

`DEFAULT_SINK_PATH = Path("/tmp/sally_turns.jsonl")`

---

### `cds_rollup.py` — Analysis CLI

**Purpose:** Consume the per-turn JSONL and produce session-level + arm-level summaries for CDS computation. Human table or JSON output.

**CLI:**
```bash
python -m backend.voice_agent.cds_rollup                          # all sessions, human table
python -m backend.voice_agent.cds_rollup --arm sally_nepq         # filter to one arm
python -m backend.voice_agent.cds_rollup --call <job_id>          # single call
python -m backend.voice_agent.cds_rollup --since 2026-04-21       # date filter
python -m backend.voice_agent.cds_rollup --since 2026-04-21T12:00 --until 2026-04-21T18:00 --json
```

**`compute_summary(rows) -> dict`** — top-level:
```
{
  total_turns, total_sessions,
  overall: { latency_stats, phase_changes, phases_distribution, l1_model_distribution, l1_primary_rate, l1_fallback_rate },
  arms: { "sally_warm": {...}, "sally_confident": {...}, "sally_direct": {...} },
  sessions: { <call_id>: { turns, arm, personality, deepest_phase, ended_at_phase, session_ended, start_ts, end_ts, duration_s } }
}
```

**Latency stats per block:** `{n, p50, p95, mean}` for each of: `user_latency_ms`, `engine_dispatch_ms`, `engine_ms`, `tts_first_frame_ms`, `asr_ms`, `utterance_duration_ms`.

**`PRIMARY_L1_MODEL = "gemini-2.5-flash-lite"`** — used to compute primary vs. fallback rate.

**`PHASE_ORDER`** (for deepest-phase ranking):
```python
["CONNECTION", "SITUATION", "PROBLEM_AWARENESS", "SOLUTION_AWARENESS",
 "CONSEQUENCE", "OWNERSHIP", "COMMITMENT", "TERMINATED"]
```

---

### `simulate_asr_metrics.py` — ASR Metric Validator

**Purpose:** Validates the 2026-04-24 `asr_ms` fix by running mock Deepgram event sequences through both the old (broken) and new (fixed) `_read_transcripts` logic, comparing outputs without touching real APIs.

**Mock event types:**
```python
class EvType(Enum): START, FINAL, END

@dataclass class Ev:
    type: EvType
    t: float      # monotonic seconds
    text: str | None
```

**Four test scenarios:**
1. **typical_deepgram:** FINAL fires 50ms before END (normal Deepgram ordering). OLD: garbage. NEW: ~0ms (transcript ready before speech end).
2. **end_before_final:** END at 22.0s, FINAL at 22.20s. Both OLD and NEW: ~200ms (happens to match).
3. **two_turns_clean:** Two turns 8s apart. OLD: ~8100ms for turn 2 (inter-utterance gap). NEW: ~100ms (correct per-utterance tail).
4. **missing_end_then_next_final:** The exact bug pattern — stale `utterance_end_t` from turn 1 leaks into turn 2. OLD: massive inflation. NEW: correct isolation.

Run: `python -m backend.voice_agent.simulate_asr_metrics`

**Mocked constants from actual `/tmp/sally_turns.jsonl` p50s (16 turns as of 2026-04-24):**
```python
ENGINE_MS = 5175
TTS_MS    = 504
```

---

### Stubs (Day 5+)

These modules contain design docstrings and TODO scaffolds but no implementation.

**`pause_manager.py`** — Per-phase post-response silence values (800ms–3000ms) scaled by personality multiplier. Will replace the current flat `_pause_s` in `sally_voice_runner.py`.

**`streaming_validator.py`** — Sentence-by-sentence validator for Layer 3 streaming output. Enables TTS start before full response is ready (<1.5s). Rollback path on validation failure.

**`cost_guard.py`** — Concurrency cap (`MAX_CONCURRENT_CALLS=3`), daily spend cap (`DAILY_SPEND_CAP_USD=25`), hourly cap (`HOURLY_CALL_CAP=15`), nightly cost report to Dev.

**`voice_legitimacy.py`** — Extends Phase 1B legitimacy scorer with voice signals: call duration (0–20 pts), speech/silence ratio (0–15 pts), ASR confidence (0–10 pts), barge-in count (0–10 pts), post-survey (0–10 pts). Consent is a hard gate: missing UI or verbal consent → -100 (auto-disqualify).

---

## 6. Personality System

| Personality | Voice | Provider | voice_id | speaking_rate | backchannel | pause_mult | pause |
|-------------|-------|----------|----------|---------------|-------------|------------|-------|
| `sally_warm` | Jessica | ElevenLabs | `cgSgspJ2msm6clMCkdW9` | 0.90 | high (1.0) | 1.2× | ~360ms |
| `sally_confident` | Alice | ElevenLabs | `Xb7hH8MSUJpSbSDYk0k2` | 0.92 | medium (0.3) | 1.0× | ~300ms |
| `sally_direct` | Thandi | Cartesia | `692846ad-1a6b-49b8-bfc5-86421fd41a19` | 1.10 | low (0.0) | 0.85× | ~255ms |

**Personality → engine arm:**
```
sally_warm       → sally_empathy_plus
sally_confident  → sally_nepq
sally_direct     → sally_direct
```

**Rate changes 2026-04-25:** Jessica 0.95→0.90 (smoke test: "some speak too fast"). Alice 1.0→0.92 (educator prosody + NEPQ asks felt rushed at 1.0).

**Voice lock policy:** DO NOT swap voices mid-experiment. Swapping invalidates CDS calibration across the ≥40-session sample (Addendum §B11). If a voice becomes unavailable, escalate to Nik before re-picking.

---

## 7. Timing & Latency Budget

| Stage | Typical | Metric field | Notes |
|-------|---------|-------------|-------|
| VAD endpointing | 300ms | — | Deepgram `endpointing_ms` |
| ASR tail | 0–300ms | `asr_ms` | `max(0, final_t - speech_end_t)`; often 0 (FINAL arrives before END) |
| Engine dispatch | ~5ms | `engine_dispatch_ms` | Scheduling overhead after FINAL_TRANSCRIPT |
| Layer 1 (Gemini Flash) | ~1200ms | part of `engine_ms` | |
| Layer 2 (decision.py) | <10ms | part of `engine_ms` | |
| Layer 3 (Claude Sonnet) | ~1300ms | part of `engine_ms` | |
| Engine total | 1500–2500ms | `engine_ms` | |
| TTS first-frame (Cartesia) | ~90ms | `tts_first_frame_ms` | |
| TTS first-frame (ElevenLabs) | ~75ms | `tts_first_frame_ms` | |
| Post-response pause | 255–360ms | — | `_pause_s = _BASE × personality_multiplier` |
| **User-perceived** | **~1.5–2.5s** | **`user_latency_ms`** | `engine_dispatch_ms + engine_ms + tts_first_frame_ms` |

**Backchannel masking:** If engine > 500ms, filler fires at 500ms. User-perceived gap feels like ~500ms, not 1.5–2.5s.

**Fast-path savings:** ~700–1000ms saved per matched single-word turn (skips Layer 1 Gemini call entirely).

---

## 8. Critical Design Decisions

### 1. Turn-Lock Serialization
`asyncio.Lock` in `SallyVoiceRunner` drops concurrent ASR finals while an engine call is in flight. If the user keeps talking mid-response, those transcripts are silently discarded. Crude but safe for Day 4 — barge-in / interruption handling is Day 5+ scope.

### 2. Audio Lock for Backchannel
A separate `_audio_lock` serializes backchannel TTS vs. real response TTS on the shared `AudioSource`. Without it, if the engine returns while a filler is playing, both would attempt to capture frames simultaneously, causing garbled output.

### 3. Track-Attach Deduplication
`attached_track_sids: set[str]` in `sally.py` and `parrot.py` prevents double-attachment. LiveKit fires `track_subscribed` for new tracks AND the post-connect `remote_participants` enumeration can return the same pre-existing track. Without the dedupe set, two concurrent `_drive_stt_from_track()` coroutines race on the same `AudioSource`.

### 4. `asyncio.to_thread` for Engine
`SallyEngine.process_turn()` is synchronous and takes ~2s. If called directly in the asyncio event loop, it blocks ALL other coroutines (ASR reads, backchannel timers, room event handling) for the entire duration. `asyncio.to_thread()` runs it in the default executor thread pool.

### 5. Module-Global for L1 Model Capture
ContextVar was the natural choice but wrong: `asyncio.to_thread()` COPIES the current context into the executor thread and discards the copy on return. Any `ContextVar.set()` inside the thread is invisible to the main thread. The module global `_last_l1_model` survives because both threads share module state. GIL-safety: `turn_lock` ensures at most one in-flight engine call per runner subprocess at a time.

### 6. `load_dotenv(override=True)` in engine_adapter
LiveKit-agents spawns prewarm subprocesses. These children inherit the parent process's environment after `load_dotenv()` has already run — but since the parent modified its own env vars (not the child's), the child may see empty values. `override=True` forces the child to re-read `.env` from disk regardless of inherited state.

### 7. Cartesia Speed Parameter Dropped
`livekit-plugins-cartesia` 1.5.4 hardcodes `Cartesia-Version: 2025-04-16` in its HTTP headers (ignores any `api_version` kwarg). On that API version, Sonic-2 rejects the `speed` parameter with HTTP 400. The `speaking_rate` field in `PERSONALITIES["sally_direct"]` exists but is unused for Thandi until this is unblocked. Fix options: vendor the plugin and swap the header; upgrade to Sonic-3 (requires re-audition + Nik approval); or wait for plugin 1.6+.

### 8. ElevenLabs PCM Encoding
The ElevenLabs plugin's default encoding is `mp3_22050_32`. This causes two problems: (a) LiveKit's `AudioSource` is configured at 24 kHz; frame sample rates don't match → `RtcError: "sample_rate and num_channels don't match"` on publish; (b) decoding MP3 in a realtime audio pipeline wastes CPU. `encoding="pcm_24000"` fixes both.

### 9. Deepgram Event Ordering
Deepgram Nova-3 fires: `START_OF_SPEECH → interim Results → FINAL_TRANSCRIPT → END_OF_SPEECH`. FINAL typically arrives **before** END (the model finalizes the transcript while VAD is still confirming silence). Correct `asr_ms` calculation: `max(0, final_t - speech_end_t)` — often 0 or slightly negative (transcript was instant, no tail).

---

## 9. Pronunciation Landmines

Applied by `pronunciation.preprocess()` before every TTS call.

| Written form | Spoken form | Reason |
|-------------|------------|--------|
| `Nik Shah` | `Nick Shah` | "Nik" → "Nick" prevents "Nike"; Shah renders /ʃɑː/ correctly as written |
| `NEPQ` | `N-E-P-Q` | Prevents "nepkew"/"nep-cue" |
| `CDS` | `C-D-S` | Prevents "cuds"/"codds" |
| `100x` | `one hundred X` | Prevents "one hundredex" |
| `AI` | `A-I` | Prevents "eye" (word-boundary guard: "paid"/"said" unaffected) |
| `$10,000` | `ten thousand dollars` | Numeric expansion |
| `$5M` | `five million dollars` | Numeric expansion |
| `TidyCal` | `tidy cal` | Prevents "tiddy-cal"/"tidy-cal" |
| `Sally` | `Sally` | Identity — keeps the name stable if model stylizes it |
| `Layer 1` | `layer one` | Prevents "layer one" vs "layer first" ambiguity |
| `Layer 2` | `layer two` | |
| `Layer 3` | `layer three` | |
| `ASR` | `A-S-R` | Prevents "asr" as a word |
| `TTS` | `T-T-S` | |
| `SMS` | `S-M-S` | |
| `P&L` | `P and L` | "pandle"/"panel" on Flash v2.5 without this; plain spaces not hyphens |
| `P and L` | `P and L` | Identity keeps already-correct form stable |

**Word-boundary guard:** Regex uses `(?<!\w)/(?!\w)` (not `\b`, which is undefined around `$` and `&`). Prevents substituting "AI" inside "paid" or "100x" inside "1100x".

**Escalation path if drift reappears after a provider model refresh:**
```
Cartesia:    <phoneme alphabet="ipa" ph="ʃɑː">Shah</phoneme>
ElevenLabs:  <phoneme alphabet="ipa" ph="ʃɑː">Shah</phoneme>  (SSML)
```

---

## 10. Metrics & CDS

### What CDS Measures
Conversion Deflection Score — the voice agent's conversion rate vs. the frozen chat baseline. ≥ +0.35 across ≥40 valid sessions is the ship gate.

### JSONL Schema
Every row: `call_id, turn_index, personality, arm, phase, phase_changed, user_text, sally_text, asr_ms, engine_ms, l1_model, tts_first_frame_ms, ended, utterance_duration_ms, engine_dispatch_ms, user_latency_ms, timestamp`

### Key Rollup Outputs
- **Per-arm latency percentiles** (p50/p95/mean for each stage) → identify arm-specific bottlenecks
- **Phase distribution** (% of sessions reaching CONSEQUENCE / OWNERSHIP / COMMITMENT) → engagement depth
- **L1 primary rate** (% of turns using `gemini-2.5-flash-lite` vs. fallback) → model stability signal
- **Per-session summary** (call_id, arm, turns, deepest_phase, duration, ended) → individual session quality

### Rollup Commands
```bash
python -m backend.voice_agent.cds_rollup                                    # full human table
python -m backend.voice_agent.cds_rollup --arm sally_nepq                   # single arm
python -m backend.voice_agent.cds_rollup --since 2026-04-21T12:00 --json    # JSON for programmatic use
```

---

## 11. Testing

Run the full suite:
```bash
source venv/bin/activate
pytest backend/voice_agent/ -v
```

| Test file | What it verifies |
|-----------|-----------------|
| `test_assignment.py` | Uniform distribution over 3000 draws; seeded RNG determinism; stratum hook forward-compat |
| `test_backchannel.py` | Phrase pool selection; dedup of last-2 recent phrases; all gating rules (CONNECTION, interval, density); async runner integration (fast engine cancels task; slow engine fires filler then real response; direct personality never fires) |
| `test_engine_adapter.py` | Personality→arm mapping; state threading across turns; history ordering; session_ended blocks further turns; arm_key passed to engine |
| `test_integration.py` | Full pipeline (transcript→engine→TTS→JSONL) with mocked engine + fake TTS; fallback phrase on engine exception; slow-engine backchannel fires and is logged separately from turn metrics |
| `test_metrics.py` | L1 log capture via logging filter; capture survives `asyncio.to_thread()`; consume-and-clear semantics; JSONL serialization of None fields as null |
| `test_pronunciation.py` | All 17 LEXICON substitutions; word-boundary guard (no match inside "paid"); case-insensitive; longest-key-first ordering; idempotency; provider arg accepted |

---

## 12. Deployment

### Container
`Dockerfile` — `python:3.11-slim`, no EXPOSE (agent is outbound WebSocket, not HTTP server), CMD: `python -m voice_agent.agent`.

### Fly.io
```toml
app = "sally-voice-agent"
primary_region = "iad"     # US-East, colocates with LiveKit Cloud India South
[[vm]]
  size = "shared-cpu-1x"
  memory = "512mb"
min_machines_running = 1   # keep one warm instance to avoid cold-start on first call
auto_start_machines = true
auto_stop_machines = false
```

Secrets: `fly secrets set LIVEKIT_URL=wss://... LIVEKIT_API_KEY=... LIVEKIT_API_SECRET=... DEEPGRAM_API_KEY=... CARTESIA_API_KEY=... ELEVENLABS_API_KEY=...`

### LiveKit Dispatch
`agent_name=""` in `WorkerOptions` → automatic dispatch to any Agents Playground room without an assigned agent. Good for Day 2–4; revisit for Day 5+ multi-tenant routing.

---

## 13. Known Issues & Blockers

| Issue | Severity | Blocked by | Fix path |
|-------|---------|-----------|---------|
| Cartesia `speaking_rate` not applied to Thandi | Medium — personality pacing for `sally_direct` broken | livekit-plugins-cartesia 1.5.4 sends wrong API version header | (a) vendor plugin + swap header, (b) upgrade to Sonic-3 + re-audition + Nik approval, (c) wait for plugin 1.6+ |
| `pause_manager.py` stub | Low | Day 5 scope | Implement per-phase pause values from `phase_definitions.PHASE_DEFINITIONS`, personality multiplier |
| `streaming_validator.py` stub | Low | Day 5 scope | Sentence-boundary validation; enables TTS start <1.5s |
| `cost_guard.py` stub | Low | Day 5 scope | `MAX_CONCURRENT_CALLS=3`, `DAILY_SPEND_CAP_USD=25`, `HOURLY_CALL_CAP=15` |
| `voice_legitimacy.py` stub | Low | Day 5 scope | 5 voice signals + consent hard gate |
| Day 5 uniform→balanced assignment | Low | Needs DB persistence | Replace `assign_personality` with balanced allocation once voice sessions persist to DB |
| Memory-personalized greeting | Low | Needs DB visitor layer (Day 5+) | `adapter.opener()` currently calls static `SallyEngine.get_greeting()`; personalization requires cross-session memory from DB |
| `voice_fast_path.match()` returns `pattern_info` dict, not `ComprehensionOutput` | Low | Import boundary | Return full ComprehensionOutput stub once the import is clean |

---

## 14. Frozen Files Policy

The following files ship the **live Phase 1 chat product**. Modifying them invalidates the experiment and violates the kill agreement with Nik.

```
backend/app/*               entire directory
backend/app/persona_config.py
backend/app/sms.py
backend/app/followup.py
```

Read-only references are fine. Write operations — including whitespace, imports, type hints, or comments — are **not permitted**.

If you believe a frozen file genuinely needs to change: stop and ask Dev. Do not "fix" or "refactor" them.
