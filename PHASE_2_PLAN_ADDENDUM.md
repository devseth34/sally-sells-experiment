# Sally Sells — Phase 2 Plan Addendum: Gap Remediation

**Status:** Supplement to `PHASE_2_VOICE_AGENT_PLAN.md`
**Date:** April 18, 2026
**Purpose:** Close 20 gaps identified in the original plan — add concrete designs, numbers, and decisions where the plan had hand-waves.

Read the original plan first. Where this addendum conflicts with the original, **this addendum controls**.

Sections are ordered by severity:
- **Part A** — critical blockers; resolve before Day 1
- **Part B** — important, but can be staged through Week 1
- **Part C** — operational cleanup and updated checklists

---

## Part A — Critical Gaps (Blockers)

### A1. Latency Budget & Parallelization Strategy

**Problem:** Original plan targets P50 < 1.5s first-audio latency. A naive serial pipeline hits 2.5–3.2s. The target is unachievable without an explicit parallelization strategy.

**Real latency math (per turn, serial baseline):**

| Stage | Time | Notes |
|-------|------|-------|
| VAD endpointing (last speech → finalized transcript) | 300–500ms | Depends on EOT silence threshold |
| Layer 1 — Gemini Flash comprehension | 600–1200ms | Full roundtrip |
| Layer 2 — deterministic Python | <20ms | Negligible |
| Layer 3 — Claude Sonnet first token (streaming on) | 400–800ms | Streaming reduces time-to-first-token |
| TTS first audio (first sentence) | 150–300ms | Cartesia ~150, ElevenLabs ~300 |
| **Naive serial total** | **~2.5–3.2s** | **Too slow** |

**Parallelization strategy (locked):**

1. **Stream Layer 3 → TTS at sentence boundaries.** Do not wait for Claude to finish. First sentence flushed to TTS as soon as it completes. Target first-audio: 1.0–1.4s from EOT.
2. **Immediate backchannel at EOT (for non-trivial turns).** Fire a scripted backchannel audio within 100ms of EOT detection. The backchannel plays while Layer 1 runs — masks 500–800ms of perceived latency. See B6 for backchannel trigger rules.
3. **Fast path for trivial utterances.** Skip Layer 1 entirely for greetings/confirmations/negations. See B2.
4. **Speculative Layer 1 on interim transcripts.** Deepgram's interim transcripts feed Layer 1 speculatively at ≥80% confidence; result is accepted on EOT if transcript is stable, discarded if it shifts materially. Saves ~400ms on stable phrasings.

**Revised, achievable targets:**
- Perceived latency (backchannel included): **P50 < 800ms**
- Time to first Sally content word: **P50 < 1.4s, P95 < 2.0s**
- Time to full response finished (not user-visible): P50 < 3.5s

Instrument each stage's latency separately and log to DB (`DBMessage.latency_ms` becomes a JSON object with `vad`, `l1`, `l3_ttft`, `tts_ttfb`, `backchannel_fired`).

---

### A2. Streaming Layer 3 vs Circuit Breaker

**Problem:** The existing Layer 3 circuit breaker validates the full response before releasing it to the frontend. Streaming means audio plays before the full response exists, so full-response validation breaks the streaming design.

**Decision: Sentence-boundary validation with graceful rollback.**

Implementation rules:
1. Layer 3 uses Anthropic streaming (`stream=True`).
2. A token accumulator flushes at sentence boundaries (`.`, `?`, `!` followed by whitespace).
3. Each completed sentence passes through a lightweight validator:
   - Length check (≤ phase max)
   - Forbidden-phrase regex (hype words, unreviewed claims)
   - Phase-appropriate content check (no pitching pre-CONSEQUENCE, no advice pre-OWNERSHIP)
4. On pass → push to TTS queue.
5. On fail for the **first** sentence → halt generation, emit "let me put that a different way," regenerate with stronger system-prompt guardrails.
6. On fail for a **later** sentence (already streaming) → cut TTS at the next natural pause boundary; emit a recovery phrase ("…actually, let me ask you this instead…"); restart from that point.

**New files:**
- `backend/voice_agent/streaming_validator.py`
- `backend/voice_agent/sally_voice_runner.py` (the wrapper; does not modify `app/agent.py` or `app/layers/response.py`)

**Fallback:** If mid-stream cuts happen more than once per 20 calls in Stage 1 testing, revert to full-response validation + eat the latency. The backchannel still masks most of the perceived delay.

---

### A3. Phase 1B Branch Strategy

**Problem:** The plan assumes a frozen brain. Phase 1B kill checkpoint is April 21 — it is not frozen yet. Every prompt change in 1B potentially invalidates voice calibration.

**Branch policy:**

```
main                        [Phase 1B iteration continues]
  └── phase-2-voice         [branched Apr 18 from 1B HEAD]
       └── merge gate       [when 1B signs off AND diff is whitelist-only]
```

**Merge gate (all required):**
1. Phase 1B CDS ≥ +0.5 confirmed by Stan in writing.
2. Diff of `app/layers/*.py`, `app/phase_definitions.py`, `app/persona_config.py` between `main` and `phase-2-voice` reviewed; only additive optional fields allowed without re-calibration.
3. Smoke test suite passes on merged branch.

**If Phase 1B slips past April 21:**
- Continue voice work on the Apr 18 brain snapshot. Do **not** block on 1B.
- Cherry-pick 1B bug fixes (not prompt/semantic changes) as needed.
- **Escalation deadline: Apr 23.** If 1B still iterating, send Stan this decision:
  > "To protect the May 3 early bonus (₹80K), I need to freeze the brain at the Apr 18 snapshot now. Alternative: accept the May 10 bonus tier (₹60K) to incorporate final 1B tuning. Your call by end of day Apr 23."

---

### A4. Recruitment Funnel & Throughput

**Problem:** Amendment requires ≥40 *valid* voice sessions. The plan doesn't model funnel losses between ad click and a legitimate completed session. 40 clicks ≠ 40 sessions.

**Funnel model:**

| Stage | Conversion | Cumulative |
|-------|-----------|------------|
| Ad click | 100% | 100% |
| Landing page load complete | 95% | 95% |
| Mic permission granted | 65% | 62% |
| Completes pre-survey | 85% | 53% |
| WebRTC call connects | 92% | 49% |
| ≥60s of conversation | 75% | 37% |
| Completes post-survey | 70% | 26% |
| Passes legitimacy gate | 85% | **22%** |

**Effective valid-session rate: ~20–22% of clicks.**

**Click requirements:**
- 40 valid sessions (amendment floor) → **~200 clicks**
- 90 valid sessions (proper 3-arm statistical power) → **~450 clicks**

**Daily pace after May 3 soft launch:**
- Target 40 valid sessions: ~4/day over 10 days → ~20 clicks/day → **$10–15/day Meta spend**
- Target 90 valid sessions: ~9/day over 10 days → ~45 clicks/day → **$25–35/day Meta spend**

Total Meta budget for 90 sessions: ~₹15,000 — well within the ₹85K Ramp allocation.

**Ad targeting:** reuse Phase 1B gig-worker audience to keep the CDS comparison clean across channels.

---

### A5. CDS Scoring Migration (Yes/Unsure/No)

**Problem:** Amendment §5.3.D defines a new Yes/Unsure/No enum with −2 to +2 scoring. Current DB and scorers assume 1–10 integer conviction. The plan references the new scale in the UI but doesn't update the DB, scoring, or reports.

**DB migration:**
```sql
ALTER TABLE sessions ADD COLUMN pre_conviction_enum  VARCHAR(8);  -- 'yes' | 'unsure' | 'no'
ALTER TABLE sessions ADD COLUMN post_conviction_enum VARCHAR(8);
ALTER TABLE sessions ADD COLUMN cds_score_v2         FLOAT;       -- voice CDS under new scoring
-- Keep pre_conviction / post_conviction / cds_score columns as-is for Phase 1A/1B backward compat.
```

**Scoring function (new):**
```python
def compute_voice_cds(pre: str, post: str) -> int:
    mapping = {
        ("no", "yes"):      +2,
        ("unsure", "yes"):  +1,
        ("no", "unsure"):   +1,
        ("yes", "unsure"):  -1,
        ("yes", "no"):      -2,
    }
    if pre == post:
        return 0
    return mapping.get((pre, post), 0)
```

**Affected files (voice path only — chat path unchanged):**
- `backend/app/database.py` — add new columns
- `backend/app/models.py` — add `PreConvictionEnum`, `PostConvictionEnum`
- `backend/app/main.py` — new `/api/voice/token` accepts enum
- `backend/app/quality_scorer.py` — branch on `session.channel`: int scale for web/SMS, enum scale for voice
- `backend/app/report_generator.py` — CSV adds `pre_enum`, `post_enum`, `cds_v2` columns; PDF breaks out Voice CDS separately from Phase 1A/1B CDS
- `frontend/src/pages/VoicePage.tsx` — Yes/Unsure/No three-button selector (not 1–10 slider)

**Analytics dashboard:** must render Phase 1A/1B (int) and Phase 2 (enum) CDS side-by-side without collapsing them. The two are not directly comparable — note that explicitly on the dashboard.

---

## Part B — Important Gaps (Before Week 2)

### B1. TTS Pronunciation Strategy

**Problem:** "Nik Shah", "NEPQ", "CDS", "100x", "$10,000" mispronounce by default. Painful first-call embarrassment is guaranteed without a lexicon.

**Strategy:**
1. Maintain `backend/voice_agent/pronunciation.py` as a preprocessing step between Layer 3 output and TTS input.
2. Each TTS provider has its own SSML/phoneme flavor:
   - **Cartesia:** inline `<phoneme alphabet="ipa" ph="...">` tags
   - **ElevenLabs:** SSML `<phoneme>` tags; also supports custom voice-level pronunciation dictionaries via their API
3. Verify every term in the lexicon during Day 2 by generating sample audio.

**Initial lexicon (confirm each with Stan):**
```python
LEXICON = {
    "Nik Shah":     "Nick Shah",          # Confirm: "shah" = /ʃɑː/ (shah), /ʃɔː/ (shaw), or /ʃeɪ/ (shay)?
    "NEPQ":         "N-E-P-Q",            # spell it out
    "CDS":          "C-D-S",
    "100x":         "one hundred X",
    "AI":           "A-I",
    "$10,000":      "ten thousand dollars",
    "$5M":          "five million dollars",
    "TidyCal":      "tidy cal",
    "Sally":        "Sally",               # baseline
    "Layer 1/2/3":  "layer one/two/three",
    "ASR":          "A-S-R",
    "TTS":          "T-T-S",
    "SMS":          "S-M-S",
}
```

**Number handling:** all dollar figures, percentages, and dates pre-expanded to words before TTS.

---

### B2. Voice Fast Path (Skip Layer 1 on Trivials)

**Problem:** Chat has a Layer 1 fast-path for trivial messages (hi/yes/no/ok/bye). Voice needs the same, and it's *more* impactful — early-phase voice turns are often single words. The plan omits it.

**Spec (`backend/voice_agent/voice_fast_path.py`):**

After ASR finalizes, match the transcript against these patterns before invoking Layer 1:

| Intent | Regex (case-insensitive, whole string) | Layer 2 action |
|--------|-----------------------------------------|----------------|
| Greeting | `^(hi\|hey\|hello)[\s!.]*$` | STAY, phase-appropriate opener |
| Confirmation | `^(yes\|yeah\|yep\|sure\|ok\|okay\|right\|correct\|exactly\|absolutely)[\s!.]*$` | STAY with `agreement=true` profile update |
| Negation | `^(no\|nope\|nah)[\s!.]*$` | STAY with `disagreement=true` update |
| Session end | `^(bye\|goodbye\|talk (to\|with) you (later\|soon)\|gotta go)[\s!.]*$` | END session |
| Filler | `^(uh\|um\|hmm\|mhm\|uh-huh\|let me think)[\s!.]*$` | STAY (treat as waiting; don't respond) |

When matched: skip Layer 1, use pre-computed `ComprehensionOutput` stub, pass to Layer 2 normally. Layer 3 still generates (or uses a templated response for filler intents).

**Latency savings:** ~700–1000ms per trivial turn. Expected to hit ~30% of turns in CONNECTION/SITUATION phases.

---

### B3. Barge-in + Frozen Layer 1 Contract

**Problem:** Section 7.5 of the original plan proposes passing `"Sally was interrupted while saying..."` to Layer 1 as context. Layer 1 is frozen per Section 10. This is a contradiction.

**Decision:** Do **not** modify Layer 1's prompt or output schema. Instead:

1. Add an additive optional field to `ComprehensionOutput`:
   ```python
   interruption_context: Optional[str] = None
   ```
2. The voice runner populates this field **before** calling Layer 1 when the prior Sally utterance was interrupted. The field contains:
   ```
   Sally was interrupted. She had said: "<completed_text>".
   She didn't get to say: "<truncated_text>".
   ```
3. Layer 1 treats it as metadata only — no prompt change, no new logic.
4. Layer 2 reads `interruption_context` for decision routing:
   - If interruption occurred during OWNERSHIP with user intent = OBJECTION → prioritize objection diffusion playbook.
   - If interruption occurred mid-question → treat user utterance as the actual answer, not a non-sequitur.

This satisfies the frozen-brain constraint because only the model *and* the `models.py` schema gain an optional field; no semantic change to any layer.

---

### B4. Voice Agent Hosting

**Problem:** The plan says "Hosting: LiveKit Cloud" but LiveKit Cloud hosts the *room*. The Python agent process needs its own host.

**Recommendation: Fly.io.**
- Cheaper than Railway for long-running processes with WebSockets.
- Multi-region; can co-locate with LiveKit Cloud region.
- Docker-native.

**Setup:**
- `backend/voice_agent/Dockerfile`:
  ```dockerfile
  FROM python:3.11-slim
  WORKDIR /app
  COPY requirements.txt .
  RUN pip install --no-cache-dir -r requirements.txt
  COPY . .
  CMD ["python", "-m", "voice_agent.agent"]
  ```
- `backend/voice_agent/fly.toml`:
  - Region: `iad` (US-East, matches default LiveKit Cloud)
  - Min machines: 1
  - Auto-scale to 3 on CPU > 70%
  - HTTP service disabled; internal only (agent is WebSocket client to LiveKit, not an HTTP server)

**Cost:** ~$5–15/month for Phase 2 traffic volumes.

The existing FastAPI backend continues on its current host and receives the agent's session lifecycle webhooks (`/api/voice/token`, `/api/voice/end`).

---

### B5. VAD & End-of-Turn Detection

**Problem:** Silence-based EOT at 800ms is a coarse 2020-era heuristic. Modern voice agents use learned turn-taking.

**Recommendation:** LiveKit Agents 1.x ships a `TurnDetector` model (small classifier) that scores "is the user done speaking?" every ~200ms based on prosody + content cues. Accuracy >95% on conversational data in LiveKit's published eval.

**Action:**
- Day 5 (Apr 23): swap raw silence-VAD for LiveKit `TurnDetector`.
- Per-phase tuning becomes "turn confidence threshold" instead of "silence ms":
  - CONNECTION: lower threshold (snappy)
  - PROBLEM_AWARENESS, CONSEQUENCE: higher threshold (let them think)
- Keep raw silence-VAD wired as fallback behind a feature flag in case TurnDetector integration has friction.

---

### B6. Backchannel Trigger Rules

**Problem:** The original plan fires a scripted backchannel at every EOT. That's the textbook "obvious AI" signature. Needs trigger rules.

**Rules (in `backchannel.py`):**

**Never** backchannel when:
- Fast-path match (trivial utterance)
- User utterance duration < 1s
- Last backchannel fired < 8s ago
- Current phase is CONNECTION (too early, feels performative)

**Always** backchannel when:
- User utterance ≥ 6s AND phase ∈ {PROBLEM_AWARENESS, CONSEQUENCE, OWNERSHIP}
- Interim ASR contains emotional markers (regex: `frustrat|stuck|tired|overwhelm|worr|stress|anxio`)

**Probabilistic (50%)** for:
- User utterance 3–6s in any phase past CONNECTION

**Per-personality density multipliers:**
| Personality | Always | Probabilistic |
|-------------|--------|---------------|
| Warm | 100% | 100% |
| Confident | 100% | 30% |
| Direct | 100% (only the "always" set) | 15% |

Backchannel variety: track last 2 used per session; never repeat consecutively.

---

### B7. Voice Audition Protocol

**Problem:** TTS voice ID choice has outsized impact on personality CDS, yet the plan treats it as a 1-line Day 1 checkbox.

**Protocol — allocate 3 hours on Apr 19:**

1. Write an audition script (~150 words) containing:
   - A NEPQ-style greeting
   - A mirroring response ("A headache… tell me more.")
   - A gentle push in OWNERSHIP tone
   - A goodbye
2. Render the script in 20 candidate voices:
   - ElevenLabs: 10 warm voices (mix of male/female)
   - Cartesia: 10 professional/confident voices
3. Score each on a 1–5 scale for: warmth, clarity, trust-inducement, naturalness. Total: 4–20.
4. Pick the top 3 non-overlapping voices for Warm / Confident / Direct. Log picks in `personalities.py` with rationale comments.
5. **Blind cross-check:** play samples to 2 outside people; ask "which feels like (a) a sales rep you'd trust, (b) a close friend, (c) a call-center agent." Reconcile with your ranking.

Do not treat voice selection as reversible after Day 2 — late-stage voice swaps invalidate calibration.

---

### B8. Consent & Recording Disclosure

**Problem:** Call recording in US two-party-consent states (CA, WA, FL, IL, MD, MA, MT, NV, NH, PA, and a few others) requires explicit disclosure. No consent flow in the plan.

**UX:**
1. **Landing page pre-survey:** required checkbox —
   > "I understand this call will be recorded for research purposes."

   The TALK button stays disabled until checked.
2. **On call connect:** Sally's first utterance includes an explicit disclosure —
   > "Hey, I'm Sally. Quick heads up — this call's being recorded for research. You good with that?"

   Proceed only if user response matches confirmation fast-path regex. If user says no → Sally: "Totally fine — I'll end the call now. Thanks for your time." → end session, do not save recording.
3. **DB:** add `consent_given_ui BOOLEAN`, `consent_given_verbal BOOLEAN` to `DBSession`. Exclude from analytics if either is false.

---

### B9. Noise Suppression / Echo Cancellation

**Problem:** Browser mics pick up keyboard, TV, background music. Speakerphone users hear Sally's own TTS echo back, causing false barge-ins.

**Action:**
- Enable LiveKit's built-in Krisp noise suppression (single flag in agent room config).
- Enable browser-side AEC + AGC via `getUserMedia` constraints:
  ```js
  navigator.mediaDevices.getUserMedia({
    audio: {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    }
  })
  ```
- Monitor false-positive barge-in rate during F&F testing. Definition: a barge-in where no human speech is detected in the 2s following. If >10% → tighten VAD sensitivity or disable agent audio during speaker-phone calls.

---

### B10. Silent User / No-Speech Handling

**Problem:** What if the user joins but says nothing? What if ASR returns only noise/filler?

**Timeout chain (after Sally's greeting completes):**
- **T+15s silence** → Sally: "Still there? Take your time."
- **T+30s more silence** → Sally: "No worries if now's not a great time. Want to try again later?"
- **T+15s more silence** → Sally: "I'll let you go. Bye for now." → end session (mark `abandonment_reason = silent_user`)

**ASR-empty handling:**
- 3 consecutive turns with ASR returning empty or only filler (<3 chars substantive) → Sally: "I'm having trouble hearing you — want to check your mic?"
- If it continues 2 more turns → end session with `abandonment_reason = mic_issue`.

**Mic permission denied at landing:**
- Show fallback CTA: "Want to text instead?" linking to the existing text experiment at `/experiment?platform=voice_fallback`.

---

### B11. Experiment Power & Assignment

**Problem:** 40 total sessions is the amendment floor but is underpowered for a confident 3-arm winner detection at CDS +0.35 effect size.

**Sample size math:**
- At 40 sessions: ~13/arm. Standard error of CDS mean ≈ 0.25. Detecting +0.35 with 80% power requires effect size ≥ ~2× SE. Marginal.
- At 90 sessions: ~30/arm. Standard error ≈ 0.14. Much more confident winner detection.

**Targets:**
- Amendment gate: ≥40 valid sessions (minimum for bonus).
- Internal target: ≥90 sessions for a defensible "this is the best personality" claim.

**Assignment algorithm (stratified random):**
```python
def assign_personality(pre_conviction_enum: str,
                       current_counts: dict) -> str:
    # Balance assignment within pre-conviction stratum
    # to reduce confounding.
    personalities = ["sally_warm", "sally_confident", "sally_direct"]
    stratum = current_counts.get(pre_conviction_enum, {})
    return min(personalities, key=lambda p: stratum.get(p, 0))
```

**Optional (post-Apr 30):** switch to Thompson sampling once 20 sessions/arm logged — biases assignment toward the leading personality while preserving exploration. Only do this if you're comfortable running it; static stratified is fine for the bonus.

---

### B12. Voice-Adapted Legitimacy Scoring

**Problem:** `legitimacy_scorer.py` scores on text metrics (user word count, topic relevance). Voice sessions need voice-specific signals.

**Additive voice signals (new file `backend/voice_agent/voice_legitimacy.py`):**

| Signal | Max pts | Logic |
|--------|---------|-------|
| Call duration | 20 | <60s = 0, 60–180s = 10, >180s = 20 |
| Speech-to-silence ratio | 15 | >40% = 15, 20–40% = 8, <20% = 0 |
| ASR avg confidence | 10 | >0.85 = 10, 0.7–0.85 = 5, <0.7 = 0 |
| Barge-in count | 10 | 1–4 = 10 (engaged), 0 or >8 = 0 |
| Completed post-survey | 10 | Binary |
| Consent given (UI + verbal) | −100 if absent | Auto-disqualify |

These **add** to the existing text-based signals computed on the ASR transcript. Total voice session legitimacy is capped at 100 across all signals.

---

### B13. Cost Cap & Concurrency Protection

**Problem:** If Meta ads overdeliver, parallel calls can blow through the per-minute cost budget. Rate limits on Deepgram/Cartesia/ElevenLabs/Claude can also silently drop calls.

**Guardrails (`backend/voice_agent/cost_guard.py`):**

Environment variables:
```bash
MAX_CONCURRENT_CALLS=3           # Raise to 5 after 20 stable calls
DAILY_SPEND_CAP_USD=25           # Agent refuses new calls when exceeded
HOURLY_CALL_CAP=15               # Burst protection
```

Rate-limit wrappers around each provider SDK:
- ElevenLabs Flash v2.5: cap at 10 req/s (docs: 40 req/s tier)
- Cartesia Sonic 2: cap at 20 req/s (docs: 100 req/s)
- Deepgram streaming: verify connection cap per account tier
- Claude Sonnet: reuse existing tier limits; budget for 3 concurrent streams

**Meta campaign daily cap:** ₹2,500/day absolute ceiling.

**Monitoring:** 11 PM IST daily email to Dev with: calls today, cost today, cost week-to-date, any rate-limit errors.

---

### B14. Voice Channel Rollback / Feature Flag

**Problem:** If voice misbehaves during the May 2 soft launch, there's no kill switch.

**Implementation:**
- Env var / DB config row: `VOICE_CHANNEL_ENABLED=true|false`.
- When `false`:
  - `POST /api/voice/token` returns `503` with `{ "error": "voice_unavailable", "fallback_url": "/experiment" }`.
  - Landing page reads the flag on mount; if false, shows "Try text chat instead" CTA linking to `/experiment`.
- Admin flip: `POST /api/admin/voice/disable` (auth-gated). Effect within 30s.
- All attempted-but-blocked sessions log to a `blocked_voice_attempts` table for outreach / re-targeting.

---

### B15. Open Questions Resolution Matrix

For each open question in the original plan's Section 13, pre-commit the fork so answers drive immediate action:

| Question | If YES | If NO |
|----------|--------|-------|
| 1B officially passed? | Proceed as planned | Follow A3: continue on Apr 18 snapshot; escalate Apr 23 |
| Reuse gig-worker pitch? | No prompt work, voice calibration uses Phase 1B prompts as-is | 3–4 day prompt rewrite; move early bonus target to May 10; notify Stan of the slip before starting |
| Same Ramp card for all subscriptions? | Sign up as planned on Day 1 | Request new card OR use personal → reimbursement; accept 1-day delay |
| LiveKit US-East region OK? | Proceed | EU/APAC adds ~100ms transatlantic latency; tighten VAD thresholds by 100ms to compensate |

**Action (EOD Apr 18):** send these four questions to Stan with this matrix attached so his answers map directly to pre-committed next steps. No ambiguity.

---

## Part C — Operational Cleanup

### C1. Clarification on Section 10 "Do Not Touch"

The original plan's Section 10 says `models.py`, `phase_definitions.py`, and the `layers/` files are frozen. The following **additive-only** changes are permitted under this addendum:

| File | Permitted additive change | Why |
|------|--------------------------|-----|
| `app/models.py` | Add optional `interruption_context: Optional[str] = None` to `ComprehensionOutput` | B3 — barge-in without modifying Layer 1 semantics |
| `app/phase_definitions.py` | Add optional `post_response_pause_ms: int` and `eot_silence_ms: int` per phase | Voice pacing (original plan 7.4, 7.6) |
| `app/models.py` | Add optional `is_voice_channel: bool = False` to the `process_turn` input shape | Lets Layer 3 tune sentence length for spoken delivery |

All other semantic behavior in `layers/*.py` stays frozen. Any deviation requires written Stan sign-off.

---

### C2. Revised Day 1 Checklist

Merge these into the original Section 11 checklist:

```
[ ] Create phase-2-voice branch from 1B HEAD (A3)
[ ] Send Open Questions to Stan with Resolution Matrix (B15)
[ ] Sign up for LiveKit Cloud, copy credentials
[ ] Sign up for Deepgram, copy API key
[ ] Sign up for Cartesia, copy API key
[ ] Confirm ElevenLabs API key; browse voice library
[ ] Add new env vars to .env (A1 latency logging + B13 cost caps)
[ ] Create backend/voice_agent/ directory scaffold (C3 layout)
[ ] Write initial pronunciation.py lexicon (B1)
[ ] Provision Fly.io account; test empty Dockerfile build (B4)
[ ] Enable LiveKit Krisp in account settings (B9)
[ ] Read LiveKit Agents Python quickstart end to end
[ ] Run LiveKit hello-world echo agent successfully
[ ] Schedule Apr 19 voice audition block (B7)
```

---

### C3. Revised File Layout

```
backend/voice_agent/
├── agent.py                    # LiveKit Agents entry point
├── sally_voice_runner.py       # Wraps SallyEngine; handles streaming + circuit break (A2)
├── streaming_validator.py      # Sentence-boundary validator (A2)
├── backchannel.py              # Trigger rules + scripted list (B6)
├── pause_manager.py            # Strategic silence per phase
├── personalities.py            # Warm/Confident/Direct TTS voice IDs
├── pronunciation.py            # Lexicon + preprocessor (B1)
├── voice_fast_path.py          # Trivial-utterance shortcut (B2)
├── voice_legitimacy.py         # Voice-adapted legitimacy (B12)
├── cost_guard.py               # Concurrency + spend cap (B13)
├── Dockerfile                  # Fly.io (B4)
├── fly.toml                    # Fly config
└── requirements.txt
```

---

### C4. Minimum Viable Monitoring Dashboard

Stage 1 testing (Apr 24) needs a real dashboard, not log-tailing. Minimum feature set for a new `/admin/voice` sub-page:

- Active calls (live count)
- Today's call volume + valid session count
- Per-personality CDS (rolling, last 25 sessions)
- Latency percentiles: VAD, Layer 1, Layer 3 TTFT, TTS TTFB — each per-phase
- Barge-in rate + false-positive rate (B9)
- Daily spend vs cap (B13)
- Voice channel flag state (B14)
- Error log tail (last 50 entries)

Implementation: extend existing `AdminPage.tsx` with a Voice tab; backend endpoint `GET /api/admin/voice/dashboard`.

---

### C5. Updated Testing Plan

Supplements the original Section 8:

**Stage 1 (internal, Apr 24):** add these specific stress tests:
- Long user monologue (60s+) — does Sally interrupt appropriately?
- User speaks over Sally mid-sentence — does barge-in cut cleanly?
- Silent user for 45s — does the timeout chain fire correctly (B10)?
- User with strong non-native-English accent — does ASR hold up?
- User on speakerphone — false barge-in rate check (B9)
- User hangs up mid-turn — does session finalization fire `DBSession.end_time` correctly?

**Stage 2 (F&F, Apr 29):** have each tester run one call per personality *plus* one 3-minute "gaming" call (intentionally short replies, off-topic, argumentative) to test legitimacy scoring (B12).

**Stage 3 (soft launch, May 2):** add a live kill-switch drill — flip `VOICE_CHANNEL_ENABLED=false` mid-day, confirm fallback UX works, flip back.

---

## Summary: What This Addendum Changes

- **5 critical blockers** get explicit designs (latency math, streaming-vs-circuit-breaker, branching, funnel, CDS migration).
- **10 important gaps** get concrete specs (pronunciation, fast path, barge-in contract, hosting, VAD upgrade, backchannel rules, voice audition, consent, noise, silence handling).
- **5 operational additions** (experiment power, voice legitimacy, cost cap, rollback flag, open-question matrix).
- **Revised Day 1 checklist, file layout, monitoring spec, and testing plan.**

Nothing here modifies the core Phase 1A/1B engine behavior. All changes are additive (new files, new optional fields, new endpoints). The "brain is frozen" constraint is preserved.

**End addendum.**
