# Voice Agent v3 Emotive Arm — Implementation Guide

> **Audience:** Claude Code
> **Companion doc:** `backend/voice_agent/ARCHITECTURE.md`
> **Status:** Spec — not yet implemented
> **Scope:** Add a 4th personality arm (`sally_emotive`) using ElevenLabs Eleven v3 with audio tags + disfluencies. Existing 3 arms remain unchanged.

---

## Table of Contents

1. [Context & Design Decisions](#1-context--design-decisions)
2. [New Arm Specification](#2-new-arm-specification)
3. [File Change Matrix](#3-file-change-matrix)
4. [Phase A — ElevenLabs v3 TTS Adapter](#4-phase-a--elevenlabs-v3-tts-adapter)
5. [Phase B — Personality Config (4th Arm)](#5-phase-b--personality-config-4th-arm)
6. [Phase C — Expression Layer](#6-phase-c--expression-layer)
7. [Phase D — Pronunciation Tag Protection](#7-phase-d--pronunciation-tag-protection)
8. [Phase E — Engine Adapter L1 Emotion Plumbing](#8-phase-e--engine-adapter-l1-emotion-plumbing)
9. [Phase F — Runner Integration](#9-phase-f--runner-integration)
10. [Phase G — Metrics](#10-phase-g--metrics)
11. [Phase H — Assignment (4-Way)](#11-phase-h--assignment-4-way)
12. [Phase I — CDS Rollup](#12-phase-i--cds-rollup)
13. [Phase J — Tests](#13-phase-j--tests)
14. [Validation Checklist](#14-validation-checklist)
15. [Smoke Test Script](#15-smoke-test-script)
16. [Known Issues & Things to Watch](#16-known-issues--things-to-watch)

---

## 1. Context & Design Decisions

### Why a 4th arm instead of upgrading existing arms

The voice-lock policy in `ARCHITECTURE.md` §6 says don't swap voices mid-experiment because it contaminates CDS calibration. Switching `sally_warm` from Flash to v3 changes the acoustic output even with the same `voice_id` — that contaminates the existing sample. A 4th arm running in parallel keeps the existing three arms' CDS sample valid and isolates v3's effect to a clean comparison.

### Why Jessica voice + sally_empathy_plus engine arm

To make `sally_warm` vs `sally_emotive` a clean A/B test where the **only** variable is "Flash flat" vs "v3 + expression layer," both arms must share:

- The same TTS voice (`cgSgspJ2msm6clMCkdW9` = Jessica)
- The same engine arm (`sally_empathy_plus`)
- The same speaking rate (0.90)
- The same post-response pause multiplier (1.2)

If you change any of these between the two arms, you can't attribute CDS deltas to v3 specifically. Hold everything else constant.

### Why two-tier routing inside the emotive arm

Even within `sally_emotive`, not every turn should hit v3:

- **Greetings, fast-path matches, single-word turns:** Route to Flash. v3 first-frame latency (~500ms–1s) is wasted on "okay" or "yeah."
- **Backchannels (mid-engine fillers):** Always Flash. Their entire job is masking latency; using v3 defeats the purpose.
- **Decorated turns (expression layer added a tag):** Route to v3. This is where v3 earns its cost.
- **Undecorated turns (expression layer added no tag):** Route to Flash. No emotional payload, no need for v3.

The expression layer's return value (`recommended_tier`) drives this routing. The TTS factory exposes both Flash and v3 instances per personality; the runner picks based on tier.

### Account constraints (ElevenLabs Creator plan)

- **5 concurrent connections.** Stay under this in `cost_guard.py` (current `MAX_CONCURRENT_CALLS=3` is fine).
- **5,000-char per-request limit on v3.** Add a defensive length check; fall back to Flash if exceeded.
- **2× credit multiplier on v3** vs 1× on Flash. Tier routing keeps cost bounded.
- **63K v3 chars/cycle remaining.** Sufficient for implementation + smoke testing.

---

## 2. New Arm Specification

Add to `personalities.py`:

```python
"sally_emotive": {
    "engine_arm":                    "sally_empathy_plus",   # SAME as sally_warm
    "tts_provider":                  "elevenlabs",
    "tts_voice_id":                  "cgSgspJ2msm6clMCkdW9",  # Jessica — SAME as sally_warm
    "tts_models": {
        "fast":    "eleven_flash_v2_5",   # for greetings, fast-path, backchannels, undecorated turns
        "emotive": "eleven_v3",            # for turns with audio tags
    },
    "speaking_rate":                 0.90,    # honored on Flash; v3 doesn't accept speed param
    "backchannel_density":           "high",  # backchannels always use fast tier
    "post_response_pause_multiplier": 1.2,
    "allowed_audio_tags":            [],      # ← USER FILLS IN POST-AUDITION
    "disfluency_density":            0.45,    # slightly higher than warm baseline
},
```

The `allowed_audio_tags` list MUST be populated by the user from their Jessica audition before the arm is enabled in production. Until populated, the expression layer falls back to no tag insertion (effectively making `sally_emotive` behave as Flash + disfluencies, which is still a meaningful test).

---

## 3. File Change Matrix

| File | Action | Phase |
|------|--------|-------|
| `backend/voice_agent/elevenlabs_v3_tts.py` | NEW | A |
| `backend/voice_agent/expression.py` | NEW | C |
| `backend/voice_agent/personalities.py` | MOD | B |
| `backend/voice_agent/tts.py` | MOD | A, B |
| `backend/voice_agent/pronunciation.py` | MOD | D |
| `backend/voice_agent/engine_adapter.py` | MOD | E |
| `backend/voice_agent/sally_voice_runner.py` | MOD | F |
| `backend/voice_agent/metrics.py` | MOD | G |
| `backend/voice_agent/assignment.py` | MOD | H |
| `backend/voice_agent/cds_rollup.py` | MOD | I |
| `backend/voice_agent/test_*.py` | MOD/NEW | J |

The frozen Phase 1 chat product (`backend/app/`) is **never** touched. Per `ARCHITECTURE.md` §14, this includes whitespace, imports, and comments.

---

## 4. Phase A — ElevenLabs v3 TTS Adapter

### Why a custom adapter is required

The `livekit-plugins-elevenlabs` package (currently 1.5.x) forces all TTS through a multi-stream-input WebSocket endpoint. The `eleven_v3` model **does not support WebSockets** — connection attempts return HTTP 403. Reference: [livekit/agents#3904](https://github.com/livekit/agents/issues/3904), [#4901](https://github.com/livekit/agents/issues/4901). ElevenLabs has confirmed this is intentional architectural divergence, not a bug.

The fix is to bypass the plugin entirely for v3 turns and call ElevenLabs' HTTP streaming endpoint (Server-Sent Events) directly.

### File: `backend/voice_agent/elevenlabs_v3_tts.py`

Implement a class `ElevenLabsV3TTS` that conforms to `livekit.agents.tts.TTS` so it's drop-in compatible with the runner.

**Constructor signature:**

```python
class ElevenLabsV3TTS(tts.TTS):
    def __init__(
        self,
        *,
        voice_id: str,
        api_key: str,
        voice_settings: VoiceSettings | None = None,
        sample_rate: int = 24000,
        timeout_s: float = 30.0,
    ) -> None: ...
```

`VoiceSettings` is a small local dataclass (do not import from the elevenlabs package — keep this adapter dependency-light). Fields: `stability: float = 0.5`, `similarity_boost: float = 0.75`. Note: `speed` is **not** included because v3 ignores it.

**Core method to implement:** `synthesize(text: str) -> ChunkedStream`

This must return an object that `sally_voice_runner._speak()` can iterate via `async for frame in stream` to push frames into `AudioSource`.

**HTTP request specification:**

```
POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream
Headers:
  xi-api-key: {api_key}
  Content-Type: application/json
  Accept: text/event-stream
Query params:
  output_format=pcm_24000
  model_id=eleven_v3
  optimize_streaming_latency=2
Body (JSON):
  {
    "text": "{text}",
    "voice_settings": {
      "stability": 0.5,
      "similarity_boost": 0.75
    }
  }
```

**SSE parsing:**

The response is a stream of `data: <base64-pcm>` lines separated by blank lines, terminated by an SSE close. For each `data:` line:

1. Decode the base64 payload to raw PCM bytes (16-bit signed little-endian, 24kHz mono)
2. Wrap in `livekit.rtc.AudioFrame(data, sample_rate=24000, num_channels=1, samples_per_channel=len(data) // 2)`
3. Yield from the ChunkedStream

**Defensive length check:**

```python
MAX_CHARS_V3 = 4800  # ElevenLabs v3 hard limit is 5000; leave 200 char safety margin

async def synthesize(self, text: str) -> ChunkedStream:
    if len(text) > MAX_CHARS_V3:
        raise V3TextTooLongError(
            f"Text length {len(text)} exceeds v3 limit; runner should fall back to Flash"
        )
    ...
```

The runner catches `V3TextTooLongError` and re-dispatches the turn through Flash.

**Retry policy:**

- One retry on 5xx with 250ms backoff
- No retry on 4xx (these are user errors — 401 = bad API key, 422 = bad text, etc.)
- Surface a clear exception class hierarchy: `V3AuthError`, `V3RateLimitError`, `V3TextTooLongError`, `V3ServerError`

**Latency measurement:**

Capture `first_frame_ms` from request-send to first SSE `data:` line. Expose as the same return shape `_speak()` already expects (`(first_frame_ms, first_frame_t)`).

**HTTP client:**

Use `aiohttp.ClientSession`. Reuse a session across calls (construct in `__init__`, close in `aclose()`). Do NOT create a new session per synthesize call — Creator plan has 5 concurrent connection limit and TLS handshake overhead would dominate first-frame latency.

**Connection lifecycle:**

```python
async def aclose(self) -> None:
    if self._session is not None:
        await self._session.close()
        self._session = None
```

The runner calls `aclose()` on shutdown.

### Update to `tts.py` (Phase A side)

Add a helper to build `ElevenLabsV3TTS`:

```python
def _make_eleven_v3(personality: dict) -> ElevenLabsV3TTS:
    api_key = os.environ.get("ELEVENLABS_API_KEY") or os.environ.get("ELEVEN_API_KEY")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY required for sally_emotive")
    return ElevenLabsV3TTS(
        voice_id=personality["tts_voice_id"],
        api_key=api_key,
        voice_settings=VoiceSettings(stability=0.5, similarity_boost=0.75),
        sample_rate=24000,
    )
```

Don't call this yet — full integration into `make_tts()` happens in Phase B.

### Tests for Phase A

`test_elevenlabs_v3_tts.py` — unit test the SSE parsing and length-check guard with a mocked `aiohttp` session. Do not hit the real API in tests. Cover:

- `synthesize` with a text under 4800 chars yields the expected number of frames
- `synthesize` with a text over 4800 chars raises `V3TextTooLongError`
- 401 raises `V3AuthError` immediately (no retry)
- 503 retries once then raises `V3ServerError`
- `aclose` closes the session

---

## 5. Phase B — Personality Config (4th Arm)

### Modify `personalities.py`

Add the `sally_emotive` entry from §2 above. Also add the new fields `tts_models`, `allowed_audio_tags`, and `disfluency_density` to all four personalities (the existing three get backwards-compatible defaults):

```python
"sally_warm": {
    # ... existing fields unchanged ...
    "tts_models":          {"fast": "eleven_flash_v2_5"},  # only fast tier
    "allowed_audio_tags":  [],                              # no tags on existing arms
    "disfluency_density":  0.0,                             # no inline disfluencies
},
"sally_confident": {
    # ... existing fields unchanged ...
    "tts_models":          {"fast": "eleven_flash_v2_5"},
    "allowed_audio_tags":  [],
    "disfluency_density":  0.0,
},
"sally_direct": {
    # ... existing fields unchanged ...
    "tts_models":          {"fast": "cartesia_sonic_2"},   # symbolic; cartesia path doesn't read this
    "allowed_audio_tags":  [],
    "disfluency_density":  0.0,
},
"sally_emotive": {
    "engine_arm":                    "sally_empathy_plus",
    "tts_provider":                  "elevenlabs",
    "tts_voice_id":                  "cgSgspJ2msm6clMCkdW9",
    "tts_models":                    {"fast": "eleven_flash_v2_5", "emotive": "eleven_v3"},
    "speaking_rate":                 0.90,
    "backchannel_density":           "high",
    "post_response_pause_multiplier": 1.2,
    "allowed_audio_tags":            [],   # TODO: populate from audition
    "disfluency_density":            0.45,
},
```

The default `allowed_audio_tags=[]` for the new arm means the expression layer will run but insert no tags until the user populates the list. This is intentional — it lets implementation proceed without blocking on the audition.

### Modify `tts.py`

Refactor `make_tts(personality_key)` to `make_tts(personality_key, *, tier: Literal["fast", "emotive"] = "fast")`.

```python
def make_tts(personality_key: str, *, tier: Literal["fast", "emotive"] = "fast") -> tts.TTS:
    personality = PERSONALITIES[personality_key]
    
    # Cartesia path (sally_direct) — both tiers identical
    if personality["tts_provider"] == "cartesia":
        return _make_cartesia(personality)
    
    # ElevenLabs paths
    if tier == "emotive":
        if "emotive" not in personality["tts_models"]:
            # Existing arms don't have an emotive tier — defensive fallback
            return _make_eleven_flash(personality)
        return _make_eleven_v3(personality)
    
    return _make_eleven_flash(personality)
```

Existing arms call `make_tts(key)` without `tier` and get Flash as before — zero behavior change for the existing 3 arms.

### Tests for Phase B

Extend `test_assignment.py` (and add `test_personalities.py` if not present) to verify:

- All four personalities load without error
- `make_tts("sally_warm")` returns Flash (unchanged)
- `make_tts("sally_emotive")` returns Flash (default tier)
- `make_tts("sally_emotive", tier="emotive")` returns `ElevenLabsV3TTS`
- `make_tts("sally_direct", tier="emotive")` returns Cartesia (no v3 for Direct)
- `make_tts("sally_warm", tier="emotive")` returns Flash (defensive fallback for arms without emotive tier)

---

## 6. Phase C — Expression Layer

### Purpose

A pure function that decorates Layer 3's response text with audio tags and disfluencies before TTS. It runs only for `sally_emotive`. For the other three arms, the runner skips the call entirely and routes to Flash with raw text.

### File: `backend/voice_agent/expression.py`

```python
def decorate(
    text: str,
    *,
    phase: str,
    user_emotion: str | None,
    personality: str,
    allowed_tags: list[str],
    disfluency_density: float,
    rng: random.Random | None = None,
) -> tuple[str, list[str], Literal["fast", "emotive"]]:
    """
    Decorate engine response with audio tags + disfluencies.
    
    Returns:
        (decorated_text, tags_used, recommended_tier)
        - tier == "emotive" if at least one tag was inserted
        - tier == "fast" if no tags inserted (then v3 latency is wasted)
    """
```

### Tag selection rules

```python
PHASE_TAG_POOLS = {
    "CONNECTION":         ["[chuckles]", "[warm chuckle]"],
    "SITUATION":          ["[curious]", "[hmm]"],
    "PROBLEM_AWARENESS":  ["[sighs]", "[empathetic]", "[hesitant]"],
    "SOLUTION_AWARENESS": ["[curious]", "[hmm]"],
    "CONSEQUENCE":        ["[sighs]", "[empathetic]"],
    "OWNERSHIP":          ["[hesitant]", "[hmm]"],
    "COMMITMENT":         ["[warm chuckle]", "[gentle laugh]"],
    "TERMINATED":         [],
}

EMOTION_TAG_OVERRIDES = {
    # If L1 detected these emotions, prefer these tags regardless of phase
    "frustrated":  ["[sighs]", "[empathetic]"],
    "joking":      ["[chuckles]", "[gentle laugh]"],
    "sad":         ["[sighs]", "[empathetic]"],
    "excited":     ["[chuckles]", "[warm chuckle]"],
    "confused":    ["[hmm]", "[hesitant]"],
}
```

**Selection algorithm:**

1. If `user_emotion` matches a key in `EMOTION_TAG_OVERRIDES`, use that pool. Otherwise use `PHASE_TAG_POOLS[phase]`.
2. Intersect with `allowed_tags` (per-personality whitelist from audition).
3. If the intersection is empty, return `(text, [], "fast")` — no decoration possible.
4. Pick one tag from the intersection (seeded RNG).
5. With probability 0.30, pick a second tag (different from the first).
6. Insert tags at strategic positions:
   - First tag: after the first sentence boundary (`.` or `?` or `!`)
   - Second tag (if any): before the last sentence

**Never:**
- Insert a tag at the very start of the response (sounds theatrical)
- Insert two tags in adjacent positions
- Insert any tag if the response is shorter than 30 characters

### Disfluency injection rules

```python
DISFLUENCY_PHRASES = {
    "warm_starter":     ["yeah, ", "so, ", "I mean, ", "you know, "],
    "warm_thinker":     ["um, ", "uh, ", "hmm, "],
    "warm_acknowledger": ["right, ", "okay, ", "got it, "],
}
```

**Selection algorithm:**

1. Split response into sentences.
2. For each sentence after the first, with probability `disfluency_density`, prefix with one disfluency:
   - 60% chance: `warm_starter`
   - 20% chance: `warm_thinker`
   - 20% chance: `warm_acknowledger`
3. Never prefix two disfluencies in a row.
4. Never modify a sentence shorter than 5 words.

### Function purity

- No LLM calls. Rules-based only.
- No side effects.
- Deterministic given a seeded `rng`.
- Must be safe to call from inside `asyncio.to_thread` (it's pure Python, so yes).

### Tests for Phase C — `test_expression.py`

- Determinism: same input + seed → same output
- Tag selection respects `allowed_tags` whitelist (no leakage)
- Empty whitelist → no tags inserted, tier="fast"
- Emotion override: `user_emotion="frustrated"` always picks from frustrated pool
- Disfluency density approximation: over 1000 runs, ratio is within ±0.05 of target
- Short text (< 30 chars): no tags, no disfluencies
- Tags never inserted at position 0 of response
- Two tags never adjacent
- `tier == "emotive"` iff `len(tags_used) > 0`

---

## 7. Phase D — Pronunciation Tag Protection

### The problem

`pronunciation.preprocess()` runs after the expression layer. The existing LEXICON could match words **inside** an audio tag bracket. Example: response is `[curious about the AI thing]`. The current regex `(?<!\w)AI(?!\w)` matches the "AI" inside the tag and substitutes it to "A-I", producing `[curious about the A-I thing]` — which v3 won't recognize as a valid tag and will speak literally.

### The fix

Stash audio tag spans before substitution, restore after.

```python
_TAG_RE = re.compile(r"\[[^\]]+\]")

def preprocess(text: str, tts_provider: str) -> str:
    # 1. Stash audio tags
    stashed: list[str] = []
    def _stash(m: re.Match) -> str:
        stashed.append(m.group(0))
        return f"\x00TAG{len(stashed) - 1}\x00"
    
    protected_text = _TAG_RE.sub(_stash, text)
    
    # 2. Run existing LEXICON substitutions on protected_text
    for pattern, replacement in _PATTERNS:
        protected_text = pattern.sub(replacement, protected_text)
    
    # 3. Restore tags verbatim
    for i, tag in enumerate(stashed):
        protected_text = protected_text.replace(f"\x00TAG{i}\x00", tag)
    
    return protected_text
```

The sentinel `\x00TAG{i}\x00` uses NUL bytes which can never appear in legitimate text, so there's no collision risk. The existing LEXICON keys never contain `\x00` so no pattern will match the sentinel.

### Tests for Phase D — extend `test_pronunciation.py`

```python
def test_audio_tag_protected_from_substitution():
    # AI inside tag should NOT be substituted
    assert preprocess("[curious about the AI thing]", "elevenlabs") == "[curious about the AI thing]"

def test_audio_tag_outside_substitution_still_works():
    # AI outside tag SHOULD be substituted
    result = preprocess("Yeah, AI is hard. [chuckles]", "elevenlabs")
    assert "A-I" in result
    assert "[chuckles]" in result

def test_multiple_tags_protected():
    text = "[chuckles] AI is great. [sighs] NEPQ helps."
    result = preprocess(text, "elevenlabs")
    assert "[chuckles]" in result
    assert "[sighs]" in result
    assert "A-I" in result
    assert "N-E-P-Q" in result

def test_lexicon_inside_tag_preserved():
    # Make sure even multi-word LEXICON keys don't leak into tags
    text = "[hesitant about the Nik Shah opportunity]"
    assert preprocess(text, "elevenlabs") == text
```

---

## 8. Phase E — Engine Adapter L1 Emotion Plumbing

### What's needed

The expression layer needs `user_emotion` to pick appropriate tags. Layer 1 already extracts emotional cues — they live in `ComprehensionOutput`. The adapter currently discards this; surface it.

### Steps

1. **Read `backend/app/schemas.py`** to find the exact field name on `ComprehensionOutput` that captures user emotion. Likely candidates: `emotional_state`, `emotional_cues`, `user_emotion`, `emotion`. Use whichever exists.

2. **Read `backend/app/agent.py`** (read-only — DO NOT MODIFY) to confirm what `SallyEngine.process_turn()` returns and whether `ComprehensionOutput` is included or just `response_text`. If only `response_text` is returned, check whether the L1 capture mechanism in `metrics.py` (`install_comprehension_capture`) can be extended to also capture the emotion field.

3. **In `engine_adapter.py`:**

```python
# Add to __init__
self._last_user_emotion: str | None = None

# Add property
@property
def last_user_emotion(self) -> str | None:
    return self._last_user_emotion

# In turn() method, after engine_result is received:
# (Option A: if ComprehensionOutput is in the result)
self._last_user_emotion = getattr(
    engine_result.get("comprehension"), 
    "emotional_state",  # or whatever field name exists
    None
)

# (Option B: if not directly available, extend the logging filter
# in metrics.py to capture emotion alongside L1 model)
```

If the emotion field isn't accessible without modifying `app/`, fall back to extending `metrics.py`'s `_ComprehensionLogFilter` to tap a second log line. Add `_last_user_emotion` as a module global with a `consume_turn_user_emotion()` function paralleling `consume_turn_l1_model()`.

### Why this is in a separate phase

If the field isn't readily accessible from outside the frozen `app/` directory, this phase blocks. In that case, the expression layer falls back to phase-only tag selection (no emotion override) until the plumbing is fixed in a later iteration. **Do not** modify `app/` to make this work — surface the blocker and proceed with phase-only selection.

### Tests for Phase E — extend `test_engine_adapter.py`

- After a turn, `adapter.last_user_emotion` returns whatever emotion field was in the engine result
- If engine result has no emotion field, `last_user_emotion` is `None`
- Emotion is reset between turns (no leakage)

---

## 9. Phase F — Runner Integration

### **STOP — ask before starting this phase.**

This is the highest-risk cross-cutting change. Confirm Phases A–E are merged and tested before touching the runner.

### Changes to `sally_voice_runner.py`

**1. Construction — build both TTS instances:**

```python
def __init__(self, personality: str, ...):
    # ... existing fields ...
    self._tts_fast = make_tts(personality, tier="fast")
    self._tts_emotive: tts.TTS | None = None
    if "emotive" in PERSONALITIES[personality]["tts_models"]:
        self._tts_emotive = make_tts(personality, tier="emotive")
    # NOTE: self._tts is removed; replace all references with _tts_fast or tier-aware lookup
```

**2. `on_user_turn` — call expression layer for emotive arm:**

After `adapter.turn()` returns and before `_speak()`:

```python
if self._personality == "sally_emotive":
    decorated_text, tags_used, tier = expression.decorate(
        response_text,
        phase=self._adapter.current_phase,
        user_emotion=self._adapter.last_user_emotion,
        personality=self._personality,
        allowed_tags=PERSONALITIES[self._personality]["allowed_audio_tags"],
        disfluency_density=PERSONALITIES[self._personality]["disfluency_density"],
    )
else:
    decorated_text = response_text
    tags_used = []
    tier = "fast"
```

**3. `_speak` — accept tier and pick TTS:**

```python
async def _speak(
    self, 
    text: str, 
    *, 
    tier: Literal["fast", "emotive"] = "fast"
) -> tuple[float | None, float | None]:
    tts_instance = self._tts_emotive if (tier == "emotive" and self._tts_emotive) else self._tts_fast
    
    # ... existing pronunciation.preprocess() call ...
    # ... existing audio_lock + chunk pump ...
    
    # Catch v3 length error and fall back to fast tier
    try:
        # synthesize and stream
        ...
    except V3TextTooLongError:
        log.warning(f"v3 text too long ({len(text)} chars), falling back to fast tier")
        return await self._speak(text, tier="fast")
```

**4. Hard cap on emotive tier latency:**

```python
EMOTIVE_TTS_TIMEOUT_S = 8.0

if tier == "emotive":
    try:
        result = await asyncio.wait_for(
            self._stream_tts(tts_instance, text),
            timeout=EMOTIVE_TTS_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        log.warning("emotive TTS exceeded 8s; falling back to fast tier")
        return await self._speak(text, tier="fast")
```

**5. Backchannels always use fast tier:**

In `_fire_backchannel_during_engine`:

```python
await self._speak(phrase, tier="fast")  # explicit, never v3
```

**6. Pass tier + tags to TurnMetrics:**

```python
metrics_sink.emit(TurnMetrics(
    # ... existing fields ...
    tts_tier=tier,
    audio_tags_used=tags_used,
    user_emotion=self._adapter.last_user_emotion,
    expression_decorated=(self._personality == "sally_emotive"),
))
```

### Tests for Phase F — extend `test_integration.py`

- `sally_warm` turn: expression layer NOT called, tier="fast", `audio_tags_used=[]`
- `sally_emotive` turn with empty `allowed_tags`: expression called but no tags inserted, tier="fast"
- `sally_emotive` turn with populated `allowed_tags`: expression inserts a tag, tier="emotive", v3 TTS called
- `V3TextTooLongError` thrown by adapter → runner falls back to Flash, single warning logged
- 8s emotive timeout → fallback to Flash, single warning logged
- Backchannel during emotive turn uses Flash, not v3 (assert v3 TTS was called exactly once for the response, never for the filler)

---

## 10. Phase G — Metrics

### Add to `TurnMetrics`

```python
@dataclass
class TurnMetrics:
    # ... existing fields ...
    tts_tier: Optional[str] = None              # "fast" | "emotive" | None for legacy
    audio_tags_used: Optional[list[str]] = None # tags inserted by expression layer
    user_emotion: Optional[str] = None          # from L1, None if unavailable
    expression_decorated: bool = False          # True iff expression layer ran
```

JSONL serialization: `audio_tags_used: None` should serialize as `null`, `[]` should serialize as `[]`. Distinguish "didn't decorate" (None) from "decorated but no tags inserted" ([]).

### Tests — extend `test_metrics.py`

- Roundtrip: `TurnMetrics(audio_tags_used=["[chuckles]"])` → JSONL → parsed dict matches
- `audio_tags_used=None` serializes as `null`
- `audio_tags_used=[]` serializes as `[]`
- `tts_tier` field is in every emitted row after the runner change

---

## 11. Phase H — Assignment (4-Way)

### Update `assignment.py`

```python
_ARMS: Final[tuple] = ("sally_warm", "sally_confident", "sally_direct", "sally_emotive")
```

That's it for the data change. The uniform-random selection logic doesn't need to change — it's already arm-count-agnostic.

### Update the assignment_method log marker

Bump from `"uniform_random_day4"` to `"uniform_random_day4_4arm"` so future analysis can filter out the 3-arm-era draws cleanly.

```python
log.info(
    f"assigned personality={personality} method=uniform_random_day4_4arm n_arms={len(_ARMS)}"
)
```

### Sample-velocity warning

With 4 arms instead of 3, each arm now gets ~25% of traffic instead of ~33%. Hitting n=40 per arm now requires ~160 sessions total instead of ~120. Add a one-line log warning at startup if `len(_ARMS) > 3`:

```python
if len(_ARMS) > 3:
    log.warning(
        f"Running with {len(_ARMS)} arms; each arm receives ~{100/len(_ARMS):.0f}% of traffic. "
        f"CDS sample target n=40/arm requires ~{40 * len(_ARMS)} total sessions."
    )
```

### Tests for Phase H — extend `test_assignment.py`

- Distribution over 8000 draws is uniform across 4 arms (each within 22%–28%)
- Seeded RNG is deterministic
- All 4 arms appear in the output
- Stratum hook still accepted but ignored

---

## 12. Phase I — CDS Rollup

### Update `cds_rollup.py`

**1. Add tier slicing to per-arm summary:**

```python
def compute_arm_summary(rows_for_arm: list[dict]) -> dict:
    return {
        # ... existing latency_stats, phase_changes, etc. ...
        "tier_distribution": {
            "fast":    sum(1 for r in rows_for_arm if r.get("tts_tier") == "fast"),
            "emotive": sum(1 for r in rows_for_arm if r.get("tts_tier") == "emotive"),
            "none":    sum(1 for r in rows_for_arm if r.get("tts_tier") is None),
        },
        "latency_stats_by_tier": {
            "fast":    _latency_stats([r for r in rows_for_arm if r.get("tts_tier") == "fast"]),
            "emotive": _latency_stats([r for r in rows_for_arm if r.get("tts_tier") == "emotive"]),
        },
        "top_audio_tags": _count_top_tags(rows_for_arm, n=5),
    }
```

**2. New CLI flag `--tier`:**

```bash
python -m backend.voice_agent.cds_rollup --arm sally_emotive --tier emotive
python -m backend.voice_agent.cds_rollup --arm sally_emotive --tier fast
```

**3. Helper for top tags:**

```python
def _count_top_tags(rows: list[dict], *, n: int = 5) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for row in rows:
        for tag in (row.get("audio_tags_used") or []):
            counter[tag] += 1
    return counter.most_common(n)
```

### Tests — extend or add `test_cds_rollup.py`

- Tier distribution counts correctly
- `latency_stats_by_tier` returns `{n: 0}` if no rows match a tier
- Top tags returns most-frequent tags across all rows
- `--tier emotive` filter on CLI works

---

## 13. Phase J — Tests

Most tests are covered phase-by-phase above. Final integration test to add to `test_integration.py`:

### Full-stack `sally_emotive` happy-path test

1. Mock engine returns: `"Yeah, that sounds frustrating. Tell me more about what happens when that's not working."`
2. Mock L1 user_emotion: `"frustrated"`
3. Personality `sally_emotive` with `allowed_tags=["[sighs]", "[empathetic]"]`
4. Seeded expression RNG
5. Assert:
   - Expression layer ran
   - At least one of the allowed tags was inserted
   - Tier returned "emotive"
   - Pronunciation preprocessing preserved the tag verbatim
   - Mock v3 TTS was called with the decorated text
   - TurnMetrics row has `tts_tier="emotive"`, non-empty `audio_tags_used`, `user_emotion="frustrated"`
6. Assert that for the same setup with `personality="sally_warm"`:
   - Expression layer NOT called
   - Tier="fast"
   - Mock Flash TTS was called with the original text

### Run the full suite

```bash
source venv/bin/activate
pytest backend/voice_agent/ -v
```

All tests must pass before the runner change is considered complete.

---

## 14. Validation Checklist

Before declaring the v3 emotive arm production-ready:

- [ ] **API key health:** `curl -H "xi-api-key: $ELEVENLABS_API_KEY" https://api.elevenlabs.io/v1/user` returns 200
- [ ] **Adapter unit tests pass:** `pytest backend/voice_agent/test_elevenlabs_v3_tts.py -v`
- [ ] **Expression unit tests pass:** `pytest backend/voice_agent/test_expression.py -v`
- [ ] **Pronunciation tag protection tests pass:** `pytest backend/voice_agent/test_pronunciation.py -v`
- [ ] **Full integration tests pass:** `pytest backend/voice_agent/test_integration.py -v`
- [ ] **Existing 3 arms unchanged:** Run a `sally_warm` call end-to-end, confirm `tts_tier="fast"`, `audio_tags_used=[]` in the JSONL row
- [ ] **Smoke test passes** (see §15)
- [ ] **Latency within budget:** Run 10 emotive turns, confirm p50 ≤ 1.2s, p95 ≤ 2.0s for `tts_first_frame_ms`
- [ ] **Cost projection:** Estimate per-session v3 char count from one full session; multiply by remaining n=40 sessions; confirm vs available credits + auto-top-up cap
- [ ] **CDS rollup produces sane output:** `python -m backend.voice_agent.cds_rollup --arm sally_emotive --tier emotive` returns a non-empty summary
- [ ] **`allowed_audio_tags` populated** in `personalities.py` from Jessica audition results

---

## 15. Smoke Test Script

After implementation, run this to verify end-to-end:

1. **Start the agent:**
   ```bash
   source venv/bin/activate
   python -m backend.voice_agent.sally dev
   ```

2. **Force assignment to `sally_emotive`** (for testing only — temporarily hardcode in `sally.py` or set an env var override):
   ```python
   # In sally.py entrypoint, temporarily:
   personality = "sally_emotive"  # was: assign_personality()
   ```

3. **Connect via the LiveKit Agents Playground** ([https://agents-playground.livekit.io/](https://agents-playground.livekit.io/)) using your `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` from `.env`.

4. **Test sequence (speak each line):**
   - "Hey Sally, what's up?" → Expect: warm greeting, possibly with `[chuckles]` if it landed in the right phase
   - "I've been struggling with my mortgage business for years now and I just feel stuck." → Expect: empathic response with `[sighs]` or `[empathetic]` tag, audible difference vs Flash
   - "Tell me about the NEPQ thing." → Expect: pronunciation correct ("N-E-P-Q"), tag preserved if any
   - "Okay sounds good, gotta go bye." → Expect: closing greeting (fast-path match, NOT v3)

5. **Inspect the JSONL:**
   ```bash
   tail -n 4 /tmp/sally_turns.jsonl | jq '{turn: .turn_index, tier: .tts_tier, tags: .audio_tags_used, latency: .user_latency_ms}'
   ```
   Expect: turn 1 `tier="fast"` (greeting), turn 2 or 3 `tier="emotive"` with non-empty `tags`, turn 4 `tier="fast"` (fast-path).

6. **Check the rollup:**
   ```bash
   python -m backend.voice_agent.cds_rollup --arm sally_emotive --since $(date -d "10 minutes ago" -Iminutes)
   ```
   Expect: 4 turns, mix of tiers, top_audio_tags shows what was inserted.

7. **Restore real assignment** in `sally.py` (remove the hardcode).

---

## 16. Known Issues & Things to Watch

| Issue | Severity | Mitigation |
|-------|----------|-----------|
| v3 first-frame latency 5–10× Flash | Medium — by design | Two-tier routing keeps it scoped to genuinely emotive turns |
| 5 concurrent connections (Creator plan) | Low at research scale | Cost guard already caps at 3 concurrent calls |
| 401 errors in last week's analytics | Medium — could disrupt v3 | Manual step #1 in main response — rotate keys before implementation |
| 5K char per-request limit on v3 | Low — defensive check in adapter | Adapter raises `V3TextTooLongError`; runner falls back to Flash |
| Audio tag rendering varies per voice | High — affects whitelist | Manual step #3 — audition Jessica before populating `allowed_audio_tags` |
| 4-arm assignment slows per-arm sample velocity | Low | Documented in startup warning; experimental cohort budget needs ~160 sessions to hit n=40/arm |
| `eleven_v3` does not honor `speed` parameter | Low | Documented in arm spec; speaking_rate still works on Flash tier |
| Layer 3 emotion field plumbing may require log-tap | Medium | Phase E falls back to phase-only tag selection if blocked; do NOT modify `backend/app/` |
| Backchannel during emotive turn could hit v3 if not gated | High — would defeat latency masking | Phase F explicitly forces `tier="fast"` for `_fire_backchannel_during_engine` |
| Concurrent v3 calls may hit 429 if 3 calls overlap | Low | One retry with 250ms backoff in adapter; surfaces as `V3RateLimitError` if persistent |

---

## End of Implementation Guide
