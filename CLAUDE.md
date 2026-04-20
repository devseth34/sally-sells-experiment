# CLAUDE.md — Phase 2 Voice Agent Handoff

> **If you are a fresh Claude Code session: read this top-to-bottom before
> touching anything. Then ask Dev (@dev@100x.inc) where to pick up.**
> Last updated: 2026-04-19, end of Day 2B.

---

## 1. Mission

Convert the existing Sally NEPQ chat sales agent into a **voice agent**
(real-time WebRTC call experience) without breaking the live Phase 1
chat product. The chat brain is frozen; only the voice surface is new.

- **Owner:** Dev (dev@100x.inc)
- **Founder / approver:** Nik Shah (WhatsApp handle: Barbie)
- **Kill date:** 2026-05-09 (20 days from this doc)
- **Success gate:** CDS (Conversion Deflection Score) ≥ +0.35 across
  ≥40 valid voice sessions, measured against the current chat baseline.
- **Abort if:** anything on that gate slips, or latency goes unusable.

---

## 2. Frozen files — DO NOT MODIFY

These ship the live Phase 1 chat product. Touching them invalidates
everything and violates the kill agreement with Nik.

```
backend/app/*                   # entire directory
backend/app/persona_config.py   # explicit — the NEPQ arms
backend/app/sms.py              # SMS pipeline
backend/app/followup.py         # drip follow-up logic
```

Read-only references are fine. **Write operations: NO.**

If you genuinely believe a frozen file needs to change, stop and ask Dev.
Do not "fix" or "refactor" them. Do not add imports, type hints, or
comments. Do not reformat.

---

## 3. Git state

- **Current branch:** `phase-2-voice` (all Phase 2 work lives here)
- **Base:** `main` — Phase 1 production, deploys to Render. Stays
  byte-identical throughout Phase 2.
- **Remote:** `origin/phase-2-voice` on GitHub (devseth34/sally-sells-experiment)
- **Nik reviews via:** that branch URL on GitHub

**Recent commits (most recent first):**

```
c7d63ca  Day 2B: lock voice picks from audition — Jessica/Alice/Thandi
0230dc8  Phase 2 Day 2A: lock Shah pronunciation as /ʃɑː/ per Nik
5b19bdc  Phase 2 Day 2A: LiveKit worker hello-world
```

**Git workflow Dev prefers:**
- Dev runs `git add / commit / push` from the VS Code terminal himself.
- Commit messages: concise imperative, end with `Co-Authored-By: Claude`
  when Claude helped author the change. Multi-line body via HEREDOC.
- **Never push to main.** Always `git push origin phase-2-voice`.
- Never force-push, never skip hooks, never rewrite history.

---

## 4. Environment

- **Python:** 3.12.13 (installed via Homebrew). The venv lives at `./venv/`.
  Activate with `source venv/bin/activate` before any Python work.
  Bumped from 3.11 on Day 4 because `backend/app/layers/comprehension.py`
  uses PEP 701 nested triple-quoted f-strings (3.12+ only). livekit-agents
  1.5.4, Deepgram + Cartesia plugins all support 3.12 without issue.
- **Deps:** `backend/voice_agent/requirements.txt` — installs fine on 3.12.
  3.9 (system default) does NOT work with livekit-agents 1.5.4.
  3.11 does NOT work with the frozen Phase 1 engine.
- **.env** is gitignored. Contains:
  ```
  LIVEKIT_URL          wss://sally-sells-580wrkyt.livekit.cloud
  LIVEKIT_API_KEY
  LIVEKIT_API_SECRET
  DEEPGRAM_API_KEY
  CARTESIA_API_KEY
  ELEVENLABS_API_KEY
  ```
  Plus the Phase 1 keys (ANTHROPIC, STRIPE, etc. — for the frozen app/*).
- **LiveKit region:** India South (auto-assigned).
- **ElevenLabs account tier:** FREE. Can use premade voices (Jessica,
  Alice, Sarah, Laura, Matilda, Bella, Lily, River). **Library voices
  fail with HTTP 402.** If Day 3+ needs a new ElevenLabs voice, check
  it's premade before wiring it.

---

## 5. Phase 2 plan — where we are

| Day | Task | Status |
|-----|------|--------|
| 1 | Scaffold (`backend/voice_agent/`) | ✅ done |
| 2A | LiveKit hello-world echo worker | ✅ done |
| 2B | Voice audition (3 personality picks) | ✅ done |
| **3** | **Deepgram Nova-3 ASR + Cartesia TTS parrot-back** | **⏭️ next** |
| 4 | Wire Sally engine via `sally_voice_runner.py` | pending |
| 5+ | Personality assignment, backchannel, metrics, launch prep | pending |

**Day 2B artifacts (just shipped in `c7d63ca`):**

- `backend/voice_agent/audition.py` — rendering + scoring harness. CLI
  modes: `list`, `smoke`, `render`, `html`.
- `backend/voice_agent/personalities.py` — three voice configs, all
  `tts_voice_id` fields filled in with locked picks.
- `backend/voice_agent/pronunciation.py` — LEXICON populated with
  Shah/NEPQ/CDS/100x/P&L/$10k etc. `preprocess()` is **still a stub**
  (`NotImplementedError`) — needs to land by Day 3 or Day 4.
- `backend/voice_agent/auditions/` — gitignored, regenerable via
  `python -m backend.voice_agent.audition render`.
- `.gitignore` excludes the `auditions/` directory.

---

## 6. Voice picks — LOCKED. Do NOT swap.

Swapping voices mid-experiment invalidates CDS calibration across the
≥40-session sample (Addendum §B11). If a voice goes unavailable,
escalate to Nik before re-picking.

| Personality | Voice | Provider | voice_id | Score |
|-|-|-|-|-|
| `sally_warm` | Jessica | ElevenLabs | `cgSgspJ2msm6clMCkdW9` | 20.00 |
| `sally_confident` | Alice | ElevenLabs | `Xb7hH8MSUJpSbSDYk0k2` | 18.50 |
| `sally_direct` | Thandi | Cartesia | `692846ad-1a6b-49b8-bfc5-86421fd41a19` | 16.00 |

**Scoring rubric (for reference only — don't re-run):**
`total = warmth × 1.0 + clarity × 1.2 + trust × 1.3 + naturalness × 1.5`
Max = 25.0. Trust + naturalness weighted highest because they're the
hardest dims to fake in a sales context.

**Why sally_confident broke the provider split:** originally planned as
Cartesia (for provider diversity + latency hedge). Cartesia's confident
field was thin — 7/10 voices got 1/1/1/1, only confident-coded voice
(Linda) scored 12.20. Alice (British "Clear, Engaging Educator") at
18.50 dominates and Flash v2.5 is actually faster than Sonic-2
(~75ms vs ~90ms), so the provider assumption wasn't a latency hedge
after all. Provider diversity preserved via Thandi on Cartesia.

---

## 7. Pronunciation landmines

The LEXICON in `backend/voice_agent/pronunciation.py`. `preprocess()` is
a stub — when implementing for Day 3/4, apply whole-word substitutions
BEFORE the TTS call. Number/date/percentage expansion runs first, then
lexicon pass, then optional provider-specific phoneme tags.

| Written form | Spoken form | Notes |
|-|-|-|
| `Shah` | `/ʃɑː/` (rhymes with spa) | Locked by Nik 2026-04-19 |
| `Nik` → `Nick` | prevents "Nike" | |
| `NEPQ` → `N-E-P-Q` | letter-by-letter | |
| `CDS` → `C-D-S` | prevents "cuds" | |
| `AI` → `A-I` | | |
| `100x` → `one hundred X` | | |
| `$10,000` → `ten thousand dollars` | | |
| `P&L` → `P and L` | **plain spaces**, not hyphens — hyphens rendered as "pandle" on Flash v2.5 | |
| `TidyCal` → `tidy cal` | | |
| `Layer 1/2/3` → `layer one/two/three` | | |

**Provider-specific phoneme tag fallbacks (if drift reappears):**
```
cartesia:    <phoneme alphabet="ipa" ph="ʃɑː">Shah</phoneme>
elevenlabs:  <phoneme alphabet="ipa" ph="ʃɑː">Shah</phoneme>   (SSML)
```

---

## 8. Day 3 spec — what to build NEXT

**Goal:** prove the audio round-trip works end-to-end in a LiveKit room.
User speaks → Deepgram Nova-3 transcribes → Cartesia Sonic-2 TTS echoes
the user's own words back. No Sally brain yet. This is a vertical
slice of the real pipeline to surface integration bugs early.

**Deliverable:** a new entrypoint, likely `backend/voice_agent/parrot.py`,
that replaces the Day 2A echo-worker's no-op body with the real
ASR → TTS loop. Keep `agent.py` intact as the registration scaffold;
parrot.py is its own runnable module.

**Success criteria:**
- Run `python -m backend.voice_agent.parrot dev`
- Join via LiveKit Agents Playground (browser)
- Speak a phrase
- Hear the same phrase back in Thandi's Cartesia voice within ~2s of
  finishing the phrase (end-of-utterance → first audio)
- Pronunciation landmines (Nik Shah, NEPQ, etc.) come out correctly
  when spoken — requires `pronunciation.preprocess()` to be implemented
  (it's currently a stub raising NotImplementedError)

**Voice choice for parrot-back:** use the `sally_direct` personality
(Thandi, Cartesia) since the direct arm has the tightest pacing
(speaking_rate 1.1, post_response_pause 0.85) — best for proving
low-latency round-trip. Pull voice_id from personalities.py rather
than hardcoding.

**Known gotchas (learned the hard way):**
1. **LiveKit `participant_connected` event** only fires for participants
   joining AFTER the agent. For pre-existing participants (e.g. the
   Playground user who connects before the worker dispatches),
   enumerate `ctx.room.remote_participants` dict explicitly on
   connect. Day 2A worker works around this by logging both.
2. **Cartesia SDK deprecation:** `client.tts.bytes()` emits
   `DeprecationWarning: Use .generate() instead`. Works for now, but
   switch to `.generate()` when wiring parrot.py. ElevenLabs SDK is
   `client.text_to_speech.convert(...)`.
3. **Byte stream topic `lk.agent.session`:** Playground sends these
   every 5s. They're Playground metadata, nothing to do with audio —
   ignore. Current agent.py logs "ignoring byte stream..." which is
   noisy; consider filtering in parrot.py.
4. **Deepgram Nova-3 streaming:** use the `livekit-plugins-deepgram`
   adapter (ships with livekit-agents 1.5.4). Do NOT hand-roll the
   WebSocket — the plugin handles reconnect, VAD, and timestamp sync.
5. **ElevenLabs free tier** rejects library voices with HTTP 402.
   Our three picks (Jessica, Alice) are premade — safe. Don't pull
   anything new from the ElevenLabs library without upgrading.

**Latency budget (for Day 3 self-assessment):**
- VAD end-of-utterance detection: ~200ms
- Deepgram Nova-3 final transcript: ~300ms
- pronunciation.preprocess(): <10ms
- Cartesia Sonic-2 first-byte: ~90ms
- Network + playback: ~100ms
- **Target: end-of-speech → first audio out < 700ms.** Anything >1.5s
  feels wrong on voice.

---

## 9. Day 4 outline (after Day 3 works)

Wire the real Sally engine. Create `backend/voice_agent/sally_voice_runner.py`
that:
- Reads `assign_personality()` output (stratified random — Addendum §B11).
- Routes to the correct `engine_arm` in the frozen `app/persona_config.py`
  (one of `sally_empathy_plus`, `sally_nepq`, `sally_direct`).
- Feeds transcribed user turns into the engine.
- Pipes engine responses through `pronunciation.preprocess()` → TTS.
- Applies personality pacing: `speaking_rate`, `backchannel_density`,
  `post_response_pause_multiplier` (last one is gate-and-wait after TTS).

**Do not modify persona_config.py.** Import and call it read-only.

---

## 10. Command cheatsheet

```bash
# activate venv (always first step in a new shell)
source venv/bin/activate

# Day 2A LiveKit hello-world worker
python -m backend.voice_agent.agent dev

# Voice audition CLI
python -m backend.voice_agent.audition list          # free, hit both SDK APIs
python -m backend.voice_agent.audition smoke         # render 2/provider (~$0.10)
python -m backend.voice_agent.audition render        # render all 20 (~$1)
python -m backend.voice_agent.audition html          # regenerate scoring HTML

# listen to rendered voices
open backend/voice_agent/auditions/index.html

# Day 3 (after you build it)
python -m backend.voice_agent.parrot dev

# Browser test client
# https://agents-playground.livekit.io/
# Enter LiveKit URL, API key, API secret from .env
```

**LiveKit dispatch mode:** `agent_name=""` in `WorkerOptions` means
automatic dispatch — any Playground room without an explicit agent
routes to our worker. Good for Day 2/3; revisit for Day 4+.

---

## 11. Working style notes for Claude

Dev prefers:
- **Direct, short answers.** No unnecessary preamble, no "here's what
  I'll do" filler. Get to the point.
- **`why` comments in code, not just `what`.** Future-us needs to
  understand the decision, not re-derive it.
- **Verify before declaring done.** Read terminal logs, check files
  on disk, run the actual command. Don't claim success from a summary.
- **Escalate when unsure** about frozen files, voice changes, or
  anything Nik-approval-shaped. Don't just guess.
- **No emojis in code.** Prose/docstrings are fine when clarifying.

When Dev says "we good?" or "does that work?" — he wants a yes/no
plus any non-obvious caveat. Not a status report.

---

## 12. External references

- **LiveKit Agents docs:** https://docs.livekit.io/agents/
- **LiveKit Agents Playground:** https://agents-playground.livekit.io/
- **Deepgram Nova-3 docs:** https://developers.deepgram.com/docs/models-nova-3
- **Cartesia Sonic-2:** https://docs.cartesia.ai/api-reference/tts
- **ElevenLabs Flash v2.5:** https://elevenlabs.io/docs/api-reference

Addendum docs (§B1-§B11) referenced in code comments live in Dev's
Google Drive — not in the repo. Ask Dev for links if needed.
