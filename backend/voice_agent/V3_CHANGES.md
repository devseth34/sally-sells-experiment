# Sally Emotive Arm (v3) — Implementation Change Log

> **Written:** 2026-04-26  
> **Author:** Dev + Claude  
> **Status:** Working in production on `phase-2-voice` branch  
> **Base:** `backend/voice_agent/` — all existing 3 arms untouched

---

## What We Built

A 4th personality arm `sally_emotive` that uses ElevenLabs Eleven v3 with audio-generation tags (`[laughs]`, `[sighs]`, `[exhales]`) and warm disfluencies (`yeah,`, `so,`, `ugh,`) to make the voice feel genuinely emotionally responsive. The arm runs the same engine (Jessica / `sally_empathy_plus`) as `sally_warm` so the only experimental variable is the expression layer.

---

## New Files

### `backend/voice_agent/elevenlabs_v3_tts.py`

Custom TTS adapter that bypasses `livekit-plugins-elevenlabs` and calls the ElevenLabs SDK's `AsyncElevenLabs.text_to_speech.stream()` directly.

**Why it exists:**  
The livekit plugin routes TTS through a WebSocket/streaming path that does **not** render audio generation tags — it reads `[laughs]` as the literal word "laughs". The ElevenLabs REST API via the official SDK does render them.

**Key discoveries during debugging:**

| What we tried | Result |
|---|---|
| `livekit-plugins-elevenlabs` Flash v2.5 | Tags read literally ("laughs", "sighs") |
| Raw HTTP POST to `/stream` with `Accept: text/event-stream` | Zero audio (SSE parser got no bytes — endpoint returns raw binary, not SSE events) |
| Raw HTTP POST to `/stream` without SSE header | Audio returned but tags still read literally |
| Raw HTTP to `/stream` with `eleven_v3` model | Audio returned, tags STILL read literally |
| `eleven_flash_v2_5` via raw HTTP | Tags read literally |
| `eleven_flash_v2_5` via ElevenLabs SDK `convert()` | **Tags rendered correctly** |
| `eleven_v3` via ElevenLabs SDK `stream()` | **Tags rendered correctly — best quality** |

**Root causes found:**
1. The ElevenLabs `/stream` endpoint returns **chunked raw binary PCM**, not SSE events — our initial `Accept: text/event-stream` header caused the parser to find zero matching lines
2. Audio generation tags (`[laughs]`, `[sighs]`, etc.) require **`eleven_v3` model** — Flash/Turbo models read them as literal text per ElevenLabs docs
3. The livekit plugin's streaming path (even with v3) does not render tags — must use the SDK's REST path

**Final implementation:**
```python
class ElevenLabsV3TTS(lk_tts.TTS):
    # Wraps AsyncElevenLabs.text_to_speech.stream()
    # model_id = "eleven_v3"
    # Subclasses lk_tts.TTS + lk_tts.ChunkedStream for runner compatibility
```

Exceptions:
- `V3AuthError` — bad API key
- `V3TextTooLongError` — text > 4800 chars (v3 limit is 5000; 200-char safety margin)
- `V3RateLimitError` — HTTP 429
- `V3ServerError` — 5xx

---

### `backend/voice_agent/expression.py`

Pure-function expression layer. Only runs for `sally_emotive`; all 3 existing arms short-circuit immediately.

**`decorate(text, *, phase, user_emotion, personality, allowed_tags, disfluency_density, rng)`**

Returns `(decorated_text, tags_used, recommended_tier)` where `tier="emotive"` iff a tag was inserted.

**Tag selection logic:**
1. Pick tag pool: emotion override from L1 `emotional_tone` beats phase pool
2. Intersect with `allowed_audio_tags` whitelist from `personalities.py`
3. **Context filter**: check if the response text itself signals the tag fits (e.g. `[sighs]` only fires when the response contains words like "tough", "hard", "hear you", "frustrat" — prevents a sigh on "What do you do?")
4. If a tag passes all gates: prepend it at position 0 (`[sighs] I hear you...`)

**Why position 0 (not mid-sentence):**  
Emotional sounds precede speech in natural conversation. A person sighs THEN speaks, not mid-sentence. Initial implementation placed tags after sentence 1, which produced unnatural results like "I hear you. [sighs] Walk me through it."

**Context signal table:**
```python
_TAG_CONTEXT_SIGNALS = {
    "[laughs]":  ["haha", "funny", "yeah right", "fair", "actually", "wild",
                  "honest", "kind of", "interesting", "good point", ...],
    "[sighs]":   ["tough", "hard", "frustrat", "stuck", "hear you",
                  "struggle", "rough", "real", "that makes sense", ...],
    "[exhales]": ["let me", "alright so", "let me think", "let me understand",
                  "makes sense", "that's a lot", "process that"],
}
```

**Disfluencies (always Flash, no tag needed):**
Per-sentence prefix injection at `disfluency_density=0.45` probability. Phrases: `"yeah, "`, `"so, "`, `"I mean, "`, `"um, "`, `"right, "`. Never on first sentence. Never two in a row. Never on sentences < 5 words.

**Valid eleven_v3 audio tags confirmed from ElevenLabs docs:**
```
[laughs]   [laughs harder]   [sighs]   [exhales]
[whispers] [excited]         [crying]  [sarcastic]
```

**Invalid tags (read literally despite appearing in EL docs/Studio):**
```
[chuckles]  [laughs softly]  [gentle laugh]  [warm chuckle]
[hmm]       [empathetic]     [hesitant]      [curious]
```

---

## Modified Files

### `backend/voice_agent/personalities.py`

Added `sally_emotive` as 4th personality entry. Added backward-compat fields to existing 3 arms (zero behavior change):

```python
"sally_emotive": {
    "engine_arm":                    "sally_empathy_plus",  # same as sally_warm
    "tts_provider":                  "elevenlabs",
    "tts_voice_id":                  "cgSgspJ2msm6clMCkdW9",  # Jessica — same as sally_warm
    "tts_models": {
        "fast":    "eleven_flash_v2_5",
        "emotive": "eleven_v3",
    },
    "speaking_rate":                 0.90,
    "backchannel_density":           "high",
    "post_response_pause_multiplier": 1.2,
    "allowed_audio_tags": ["[laughs]", "[sighs]", "[exhales]"],
    "disfluency_density":            0.45,
},
```

**Why same voice/engine/rate as `sally_warm`:** Isolates the experimental variable to the expression layer only. Any CDS delta between warm and emotive is attributable solely to audio tags + disfluencies, not voice character.

**Existing 3 arms** got these new keys (no behavior change):
```python
"tts_models":         {"fast": "eleven_flash_v2_5"},  # or cartesia_sonic_2
"allowed_audio_tags": [],    # empty → expression layer fires but inserts no tags
"disfluency_density": 0.0,   # no disfluencies
```

---

### `backend/voice_agent/tts.py`

**Added `tier` parameter:**
```python
def make_tts(personality_key: str, *, tier: Literal["fast", "emotive"] = "fast") -> lk_tts.TTS
```

- `tier="fast"` → existing behavior unchanged (Flash or Cartesia)
- `tier="emotive"` → returns `ElevenLabsV3TTS` for `sally_emotive`; defensively falls back to fast for other arms

**Added `_make_eleven_v3(personality_key)` helper** — builds `ElevenLabsV3TTS` with API key from env, voice_id from PERSONALITIES.

**Added `import os`** at top level (previously lazy-imported inside the elevenlabs branch).

---

### `backend/voice_agent/sally_voice_runner.py`

**`__init__` changes:**
- Added `tts_emotive: Optional[lk_tts.TTS] = None` parameter (kept for API compat)
- Renamed `self._tts` → `self._tts_fast` for clarity
- Added `self._tts_emotive` (the v3 adapter; `None` for all 3 existing arms)

**New method `_apply_expression(response_text)`:**
- Returns `(decorated_text, tags_used, tier)` 
- Short-circuits immediately for non-emotive personalities → zero cost to existing arms
- Calls `expression.decorate()` for `sally_emotive`
- Swallows expression layer exceptions gracefully (non-fatal, degrades to raw text)

**`_speak(text, *, tier="fast")` changes:**
- Two synthesis paths: emotive goes through `_tts_emotive` (v3 SDK adapter), fast through `_tts_fast` (livekit Flash plugin)
- If emotive fails for any reason → falls back to fast tier, logs warning
- Backchannels always explicitly pass `tier="fast"` (filler masking latency; v3 would add latency, not hide it)

**`on_user_turn` changes:**
- Calls `_apply_expression(response_text)` after engine returns
- Passes `decorated_text` (with any tags) to `_speak(tier=...)`
- Passes `tts_tier`, `audio_tags_used`, `user_emotion`, `expression_decorated` to `_emit_metrics()`

**`_emit_metrics` changes:**
- 4 new params with defaults: `tts_tier="fast"`, `audio_tags_used=None`, `user_emotion=None`, `expression_decorated=False`

---

### `backend/voice_agent/metrics.py`

4 new fields on `TurnMetrics` dataclass (all defaulted → backward-compatible with old rows):

```python
tts_tier: Optional[str] = None           # "fast" | "emotive"
audio_tags_used: Optional[list] = None  # tags expression layer inserted; [] = ran but no tags; None = didn't run
user_emotion: Optional[str] = None      # L1 emotional_tone for this turn
expression_decorated: bool = False      # True iff expression layer ran for this turn
```

---

### `backend/voice_agent/engine_adapter.py`

**Emotion plumbing for the expression layer:**

- Added `self._last_user_emotion: Optional[str] = None`
- Added `@property last_user_emotion`
- In `turn()`: after engine result returns, parses `result["thought_log_json"]` (a JSON string the engine already returns) to extract `comprehension.emotional_tone`
- Added `_parse_user_emotion(thought_log_json)` module-level helper — defensive JSON parse with two fallback shapes (nested under `comprehension` or flat at root)
- Added `"user_emotion"` to `_last_turn_stats`

**Why `thought_log_json` instead of a log tap:** The engine already serializes `ComprehensionOutput` into `thought_log_json` in its result dict — no log filter needed, no frozen file changes, just a `json.loads()`.

**Why `emotional_tone` field:** `app/models.py:ComprehensionOutput` has 5 emotion-related fields. `emotional_tone` is the closest to a single-string emotion label (e.g. `"engaged, frustrated, defensive"`), and the expression layer uses substring matching against this string.

---

### `backend/voice_agent/pronunciation.py`

**Audio tag protection** — prevents LEXICON substitutions from clobbering tag content:

```python
_TAG_RE = re.compile(r"\[[^\]]+\]")

def preprocess(text, tts_provider):
    # 1. Stash [tag_name] spans behind NUL-byte sentinels (\x00TAG0\x00)
    # 2. Run LEXICON substitutions on protected text
    # 3. Restore tags verbatim
```

**Why NUL-byte sentinels:** They cannot appear in legitimate text or in any LEXICON key, so there's zero collision risk. Without this, `[sighs about the AI problem]` would become `[sighs about the A-I problem]` and v3 wouldn't recognize the tag.

---

### `backend/voice_agent/assignment.py`

- Extended `_ARMS` tuple to include `"sally_emotive"` (4-way uniform random)
- Bumped log marker from `"uniform_random_day4"` → `"uniform_random_day4_4arm"`
- Uniform random still used (Day 5 will switch to balanced allocation once voice sessions persist to DB)

---

### `backend/voice_agent/sally.py`

- Added `SALLY_FORCE_PERSONALITY` env var support for smoke testing (set in `.env`, picked up by every subprocess via `load_dotenv(override=True)`)
- Builds `tts_emotive = make_tts(personality, tier="emotive")` — returns `ElevenLabsV3TTS` for emotive arm, `None` for others (exception swallowed)
- Passes `tts_emotive=tts_emotive` to `SallyVoiceRunner`

---

### `backend/voice_agent/requirements.txt`

Added `aiohttp` (was needed during HTTP adapter phase; kept for potential future use). The final v3 adapter uses `elevenlabs` SDK which is already in requirements.

---

## Test Changes

### `test_assignment.py`
- Renamed test to `test_returns_one_of_the_locked_personalities` (from "three" to "locked")
- Updated distribution test: 4000 draws / 4 arms = 1000 expected each ±10%

### `test_backchannel.py`
- Added `last_user_emotion = None` to `_FakeAdapter` (new field from Phase E)

### `test_engine_adapter.py`
- Added 6 new tests for emotion plumbing:
  - Nested thought_log path (`comprehension.emotional_tone`)
  - Flat thought_log path (`emotional_tone` at root)
  - Missing thought_log → None
  - Malformed JSON → None
  - Missing field → None
  - Reset between turns (no leakage)
  - `last_turn_stats` includes `user_emotion`

### `test_expression.py` (new file)
- 14 tests covering: determinism, whitelist enforcement, emotion override, short-text guard, tier semantics, tag positioning (now position 0), disfluency density approximation, unknown phases, TERMINATED phase

### `test_pronunciation.py`
- Added 7 tag-protection tests: tag content protected, LEXICON applies outside tags, multiple tags, multi-word LEXICON keys inside tags, sentinel leakage check, idempotency

---

## What Does NOT Work / Known Limitations

| Item | Status |
|------|--------|
| `[chuckles]`, `[laughs softly]`, `[gentle laugh]`, `[warm chuckle]` | Not valid v3 tags — read literally |
| `[hmm]`, `[empathetic]`, `[hesitant]`, `[curious]` | Not valid v3 tags — read literally |
| ElevenLabs Studio vs API parity | Studio UI renders more tag types than the API |
| `speed` param on v3 | Ignored by v3 model (speaking_rate only honored on Flash tier backchannels) |
| `allowed_audio_tags` needs manual audition | Must verify each tag works on the specific voice before adding to the whitelist |
| `SALLY_FORCE_PERSONALITY` in production | Must be removed from `.env` before shipping (currently set to `sally_emotive` for smoke testing) |
| 4-arm assignment slows per-arm CDS sample | ~160 sessions needed to hit n=40/arm (vs 120 with 3 arms) |

---

## Architecture Diagram (Emotive Turn)

```
User speaks
    ↓
Deepgram Nova-3 STT (Flash livekit plugin — unchanged)
    ↓
SallyEngineAdapter.turn()
  → asyncio.to_thread(SallyEngine.process_turn)
  → parses thought_log_json → stores emotional_tone as last_user_emotion
    ↓
SallyVoiceRunner._apply_expression(response_text)
  → expression.decorate(
        text=response_text,
        phase=adapter.current_phase,
        user_emotion=adapter.last_user_emotion,  ← from thought_log_json
        allowed_tags=["[laughs]", "[sighs]", "[exhales]"],
        disfluency_density=0.45,
    )
  → context gate: does response text warrant this tag?
  → returns ("[sighs] I hear you, that sounds tough.", ["[sighs]"], "emotive")
    ↓
pronunciation.preprocess()
  → stash [sighs] behind \x00TAG0\x00
  → run LEXICON substitutions
  → restore [sighs] verbatim
    ↓
SallyVoiceRunner._speak(decorated_text, tier="emotive")
  → ElevenLabsV3TTS.synthesize(text)       ← eleven_v3 via SDK
  → AsyncElevenLabs.text_to_speech.stream()
  → v3 model renders [sighs] as actual sigh sound
  → PCM chunks → AudioSource → LiveKit → user hears sigh + speech
    ↓
Metrics: tts_tier="emotive", audio_tags_used=["[sighs]"], user_emotion="frustrated"
    → /tmp/sally_turns.jsonl
```

**Backchannels (mid-engine fillers)** always use `tier="fast"` (Flash livekit plugin) — their job is masking latency, so using v3 would defeat the purpose.

**Greeting** always uses `tier="fast"` — expression layer only runs on engine-processed user turns.

---

## How to Force the Emotive Arm for Testing

```bash
# Set in .env (picked up by all subprocesses):
SALLY_FORCE_PERSONALITY=sally_emotive

# Restart agent:
source venv/bin/activate && python -m backend.voice_agent.sally dev

# Watch expression layer in real time:
tail -f /tmp/sally_live.log | grep -E "Expression layer|emotive|tags"

# Check JSONL for tier + tags per turn:
tail -f /tmp/sally_turns.jsonl | while read line; do
  echo "$line" | python3 -c "
import sys,json; d=json.load(sys.stdin)
print(f\"turn={d['turn_index']} tier={d.get('tts_tier')} tags={d.get('audio_tags_used')} emotion={d.get('user_emotion')}\")
print(f'  {d[\"sally_text\"][:80]}')
" 2>/dev/null; done
```

Remove `SALLY_FORCE_PERSONALITY` from `.env` before production launch to re-enable 4-way random assignment.
