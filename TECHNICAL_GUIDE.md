# Sally Sells: Complete Technical Architecture Guide

> **Purpose**: This document is a complete context file for AI assistants or developers working on the Sally Sells codebase. It covers every architectural decision, data flow, state machine, prompt template, validation rule, and edge case in the system.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Tech Stack](#2-tech-stack)
3. [Three-Layer Architecture](#3-three-layer-architecture)
4. [NEPQ Phase Sequence](#4-nepq-phase-sequence)
5. [Layer 1: Comprehension](#5-layer-1-comprehension)
6. [Layer 2: Decision](#6-layer-2-decision)
7. [Layer 3: Response](#7-layer-3-response)
8. [State Machines](#8-state-machines)
9. [Situation Playbooks](#9-situation-playbooks)
10. [Data Models](#10-data-models)
11. [API Endpoints](#11-api-endpoints)
12. [Quality Scoring](#12-quality-scoring)
13. [External Integrations](#13-external-integrations)
14. [Frontend Architecture](#14-frontend-architecture)
15. [Turn-by-Turn Data Flow](#15-turn-by-turn-data-flow)
16. [Critical Edge Cases](#16-critical-edge-cases)
17. [Key Constants Reference](#17-key-constants-reference)

---

## 1. System Overview

Sally Sells is an **NEPQ (Neuro-Emotional Persuasion Questioning) AI sales agent** that sells 100x's $10,000 Discovery Workshop. The system uses a **three-layer architecture** (Comprehension -> Decision -> Response) to guide prospects through a structured 7-phase sales conversation.

**What it sells**: CEO Nik Shah comes onsite to build a customized AI transformation plan, identifying how the client can save $5M annually with AI. Price: $10,000. Free alternative: online AI Discovery Workshop.

**Core principle**: Layer 2 (Decision) is **pure deterministic code** with zero LLM calls. Only Layers 1 and 3 use Claude. This makes the conversation flow predictable, debuggable, and auditable.

---

## 2. Tech Stack

**Backend**: FastAPI + Uvicorn, Python 3.9+, PostgreSQL (SQLAlchemy ORM), Anthropic Claude API (claude-sonnet-4-20250514), Stripe, Gmail SMTP, Google Sheets webhook

**Frontend**: React 19 + TypeScript, Vite, Tailwind CSS, React Router v7

**Key files**:
```
backend/app/
  agent.py              — Orchestrator (process_turn)
  main.py               — FastAPI routes (13+ endpoints)
  models.py             — Pydantic models (enums, profiles, thought logs)
  schemas.py            — API request/response schemas
  database.py           — SQLAlchemy ORM (DBSession, DBMessage)
  phase_definitions.py  — Phase configs, exit criteria, response lengths
  playbooks.py          — 9 situation playbook templates
  quality_scorer.py     — Post-conversation quality scoring
  sheets_logger.py      — Google Sheets fire-and-forget logging
  layers/
    comprehension.py    — Layer 1: LLM message analysis
    decision.py         — Layer 2: Deterministic decision logic
    response.py         — Layer 3: LLM response generation
```

---

## 3. Three-Layer Architecture

### Layer 1: Comprehension (The Analyst)
- **File**: `layers/comprehension.py`
- **Uses LLM**: Yes (Claude Sonnet 4)
- **Job**: Analyze user message, extract intent/objections/profile/emotions/exit criteria
- **Output**: `ComprehensionOutput` with 18+ fields

### Layer 2: Decision (The Manager)
- **File**: `layers/decision.py`
- **Uses LLM**: No (pure Python logic)
- **Job**: Decide action (ADVANCE/STAY/PROBE/REROUTE/BREAK_GLASS/END) based on Layer 1 output
- **Output**: `DecisionOutput` with action, target_phase, reason, retry_count

### Layer 3: Response (The Speaker)
- **File**: `layers/response.py`
- **Uses LLM**: Yes (Claude Sonnet 4)
- **Job**: Generate Sally's response constrained by Layer 2's decision
- **Output**: Response text, validated by circuit breaker

### Orchestrator
- **File**: `agent.py` (`SallyEngine.process_turn()`)
- **Job**: Wire layers together, maintain state (emotional depth, ownership substeps, objection diffusion, repetition tracking)

---

## 4. NEPQ Phase Sequence

Defined in `phase_definitions.py`. Phases progress strictly forward (except objection rerouting).

| # | Phase | Purpose | Min Turns | Max Retries | Confidence | Response Limit |
|---|-------|---------|-----------|-------------|------------|----------------|
| 1 | CONNECTION | Build rapport, learn role/company/AI interest | 2 | 3 | 65% | 2 sentences, 120 tokens |
| 2 | SITUATION | Map current operations and day-to-day | 1 | 3 | 65% | 2 sentences, 120 tokens |
| 3 | PROBLEM_AWARENESS | Surface real pain in prospect's own words | 3 | 4 | 65% | 3 sentences, 150 tokens |
| 4 | SOLUTION_AWARENESS | Paint desired future, create gap | 2 | 3 | 65% | 3 sentences, 150 tokens |
| 5 | CONSEQUENCE | Make cost of inaction real and personal | 2 | 4 | 70% | 3 sentences, 180 tokens |
| 6 | OWNERSHIP | Present offer, handle objections with NEPQ | 2 | 4 | 65% | 4 sentences, 200 tokens |
| 7 | COMMITMENT | Collect email + phone, send link, close | 1 | 5 | 70% | 4 sentences, 300 tokens |

### Exit Criteria (all must be met to advance)

**CONNECTION**: `role_shared`, `company_or_industry_shared`, `ai_interest_stated`

**SITUATION**: `workflow_described`, `concrete_detail_shared`

**PROBLEM_AWARENESS**: `specific_pain_articulated` (in prospect's OWN words), `pain_is_current`

**SOLUTION_AWARENESS**: `desired_state_described`, `gap_is_clear`

**CONSEQUENCE**: `cost_acknowledged` (tangible cost), `urgency_felt`

**OWNERSHIP**: `commitment_question_asked`, `prospect_self_persuaded` (prospect articulated reason, not just "yeah"), `price_stated` ($10K mentioned), `definitive_response` (yes paid/yes free/hard no)

**COMMITMENT**: `positive_signal_or_hard_no`, `email_collected`, `phone_collected`, `link_sent`

---

## 5. Layer 1: Comprehension

### System Prompt Rules
- Extract ONLY explicit information, never infer
- Pain points must come from prospect, not suggested by Sally
- Exit criteria: TRUE only with clear evidence, FALSE if vague
- Short answers CAN satisfy multiple criteria ("I'm a dev at fintech" = role + company)
- "yeah" or "ok" with no new info satisfies NOTHING
- new_information: TRUE only for concrete not-yet-in-profile facts; FALSE for filler/repetition

### Output Fields
```json
{
  "user_intent": "DIRECT_ANSWER|DEFLECTION|QUESTION|OBJECTION|SMALL_TALK|AGREEMENT|PUSHBACK|CONFUSION",
  "emotional_tone": "engaged|skeptical|frustrated|defensive|excited|neutral|warm|guarded",
  "emotional_intensity": "low|medium|high",
  "objection_type": "PRICE|TIMING|AUTHORITY|NEED|NONE",
  "objection_detail": "specific objection text or null",
  "profile_updates": {"field": "value"},
  "exit_evaluation": {
    "criteria": {"criterion_id": {"met": true/false, "evidence": "..."}},
    "reasoning": "...",
    "missing_info": ["..."]
  },
  "response_richness": "thin|moderate|rich",
  "emotional_depth": "surface|moderate|deep",
  "new_information": true/false,
  "objection_diffusion_status": "not_applicable|diffused|isolated|resolved|repeated",
  "prospect_exact_words": ["2-3 phrases worth mirroring"],
  "emotional_cues": ["frustrated about X consuming Y hours/week"],
  "energy_level": "low/flat|neutral|warm|high/excited",
  "summary": "one sentence"
}
```

### Richness/Depth Definitions
- **thin**: 1-5 words, filler, vague ("yeah", "ok", "not sure")
- **moderate**: Real sentence with specifics, no emotional language
- **rich**: Multi-sentence, vivid detail, emotional language, vulnerability
- **surface**: Named a topic factually, no feeling
- **moderate depth**: Expressed a feeling or emotional engagement
- **deep**: Real vulnerability, fear, personal stakes

### Confusion Detection
- "I don't understand", "what do you mean", "huh?", "what?" (in context) = CONFUSION
- CONFUSION != PUSHBACK. If both, classify as CONFUSION (clarity first)

### API Config
- Model: `claude-sonnet-4-20250514`
- Max tokens: 800
- Conversation window: Last 10 messages
- Prompt caching: ephemeral on system prompt

---

## 6. Layer 2: Decision

**Pure deterministic code. No LLM.**

### Decision Priority (checked in this exact order)

1. **Session time limit**: > 30 minutes = END
2. **Already terminated**: current_phase == TERMINATED = END
3. **Objection routing**:
   - AGREEMENT/DIRECT_ANSWER + objection = STAY (address naturally)
   - Late phases (OWNERSHIP/COMMITMENT): objections handled in-phase via NEPQ diffusion, never reroute. Returns STAY + `DIFFUSE:{type}:{detail}`
   - AUTHORITY: always STAY (never reroute)
   - Early phases: reroute backward (PRICE->CONSEQUENCE, TIMING->PROBLEM_AWARENESS, NEED->SOLUTION_AWARENESS) only if current phase is ahead of target
4. **Confusion**: STAY + `PLAYBOOK:confusion_recovery`. Does NOT increment retry_count
5. **Gap Builder constraint**: required profile fields missing = STAY
6. **Minimum turns**: turns_in_current_phase < min_turns = STAY. Does NOT increment retry_count
7. **Exit criteria evaluation** (most complex):
   - If ALL met:
     - CONSEQUENCE->OWNERSHIP gate: `deepest_emotional_depth` must be "deep" or STAY
     - Contact info gate: can't END without email/phone
     - Gap Builder check for next phase's required fields
     - If passes all gates: ADVANCE (retry_count reset to 0)
8. **Ownership substep enforcement**:
   - 8+ turns in OWNERSHIP: force `PLAYBOOK:ownership_ceiling`
   - substep==2, self-persuasion not met: force `PLAYBOOK:bridge_with_their_words`
9. **Probing trigger**: thin + surface responses, or thin + critical phase (PROBLEM_AWARENESS/CONSEQUENCE/OWNERSHIP) = PROBE (retry_count += 1)
10. **Repetition detection**: consecutive_no_new_info >= 2:
    - fraction_met >= 0.5: force ADVANCE
    - else: BREAK_GLASS (retry_count += 1)
11. **Break Glass / retry ceiling**:
    - retry_count >= max_retries AND fraction >= 0.5: force ADVANCE
    - retry_count >= max_retries + 2: hard ceiling force ADVANCE
    - else: BREAK_GLASS (retry_count += 1)
12. **Default**: STAY (retry_count += 1)

### Situation Playbook Detection (runs AFTER make_decision)
Skips if decision already has playbook, or action is ADVANCE/END. First match wins:

1. **graceful_exit**: PUSHBACK + high intensity + late phase
2. **dont_oversell**: CONSEQUENCE/OWNERSHIP + agreement/direct_answer + medium/high intensity + buy-signal phrases
3. **graceful_alternative**: late phase + objection repeated after diffusion
4. **resolve_and_close**: OWNERSHIP + diffusion step >= 2 + agreement + no current objection
5. **energy_shift**: 3+ consecutive thin/flat turns
6. **specific_probe**: thin + surface + critical phase + PROBE action

---

## 7. Layer 3: Response

### Sally Persona
- Sharp, genuinely curious NEPQ consultant at 100x
- Sounds like smart friend, not salesperson
- REAL uncertainty in phases 1-4: "not yet sure if I can help"
- Texts like a real person (lowercase fine, fragments fine)

### Tone by Phase
- **Phases 1-4** (CONNECTION -> SOLUTION_AWARENESS): CURIOUS and NEUTRAL. No editorializing. Minimal validation. Like a doctor taking history, not a therapist.
- **Phase 5** (CONSEQUENCE): Can reflect emotions prospect EXPLICITLY expressed. Use "..." for weight.
- **Phases 6-7** (OWNERSHIP, COMMITMENT): Warmer, earned through journey. Never hype.

### Mirroring Rules
- Pick 1-2 KEY WORDS, not full phrases
- Weave into OWN natural question (build something NEW)
- Test: if first 5 words are just their words rearranged, rewrite
- Good: They say "it takes forever" -> You say "How long are we talking?"
- Bad: "It takes forever. How long does it take?"
- Mirror detection: if 2+ of last 3 responses start with mirroring, inject variation instructions

### Hard Rules
1. ONE question per response (never stack with "and")
2. Keep responses SHORT (phase-dependent sentence limits)
3. NEVER mention workshop/100x/price before OWNERSHIP
4. NEVER give advice before OWNERSHIP (questions only)
5. NO hype words (forbidden list)
6. Weave 1-2 key words naturally
7. "..." for emphasis in later phases only
8. If asked a question: answer briefly (1 sentence) then redirect
9. STOP SELLING when they say yes
10. Never repeat a question
11. Never use "Tell me more" - reference THEIR topic specifically
12. No em dashes or semicolons
13. Phases 1-4: NO editorializing

### Forbidden Words
```
guaranteed, revolutionary, game-changing, cutting-edge, transform, unlock,
skyrocket, supercharge, unleash, incredible, amazing, unbelievable,
mind-blowing, powerful, leverage, synergy, paradigm, disrupt, innovate
```

### Forbidden Phrases
```
that's completely understandable, i appreciate you sharing, that makes a lot of sense,
that makes total sense, that's a great question, i completely understand,
happens to the best of us, that's interesting, great point, i hear you,
no worries, absolutely, tell me more, got it
```

### Editorial Phrases (blocked in phases 1-4 only)
```
that's a whole thing, those are the worst, that's the dream, that's huge,
that's no joke, that's a lot, that sounds tough, that sounds rough,
that sounds brutal, that's really something, that's brutal, that's the worst,
that's so frustrating, wow
```

### Circuit Breaker (post-generation validation)
Runs on every generated response. Checks in order:

1. Strip em dashes and semicolons (replace with commas/periods)
2. Multiple questions: keep only up to first "?"
3. Forbidden words: return fallback "How has that been playing out for you day-to-day?"
4. Forbidden phrases: remove phrase, clean orphaned punctuation
5. Editorial phrases in early phases: same removal + cleaning
6. Pitch signals in early phases ($10,000, discovery workshop, nik shah, 100x): return fallback "What's been the biggest challenge with that so far?"
7. Length check: keep first N sentences per phase limit (relaxed to 10 for closing)
8. Safety net: if <4 clean words remain, return fallback

### Ownership Phase Substep Prompting
Layer 3 receives the current `ownership_substep` and generates accordingly:

- **Substep 0-1**: Ask commitment question ("do you FEEL like having a customized AI plan could help you get [their desired state]?")
- **Substep 2**: Self-persuasion probe ("What makes you feel like it could work for you?")
- **Substep 3**: Bridge using their exact pain words
- **Substep 4**: Present offer ($10K Discovery Workshop, state price, then STOP)
- **Substep 5**: Objection handling (DIFFUSE -> ISOLATE -> RESOLVE sequence)
- **Substep 6+**: Close or fallback (collect info, offer free, or end gracefully)

### NEPQ Objection Diffusion Protocol (in response prompt)
Three-step sequence, ONE step per message:

1. **DIFFUSE**: Lower emotional temperature ("That's not a problem..." / "Totally fair...")
   - NEVER counter with "but you said..."
   - NEVER use "I get it, but..." (the "but" negates diffusion)
2. **ISOLATE**: Separate objection from desire ("[Objection] aside... do you feel like a customized AI plan is the right move?")
3. **RESOLVE**: Let them solve it ("If we could figure out the [objection] piece, would you want to move forward?")

### Contact Collection Flow (COMMITMENT phase)
1. Email first: "What's the best email to send the details to?"
2. Phone second: "And what's the best number to reach you at?"
3. Links:
   - Free workshop: Include exact TidyCal URL (`https://tidycal.com/{tidycal_path}`)
   - Paid workshop: Include literal text `[PAYMENT_LINK]` (auto-replaced with Stripe URL)

### API Config
- Model: `claude-sonnet-4-20250514`
- Max tokens: 300 (closing), else phase-specific (~200)
- Conversation window: Last 8 messages
- Prompt caching: ephemeral on SALLY_PERSONA system prompt

---

## 8. State Machines

### 8.1 Emotional Depth Ratchet
Tracked in `agent.py`. Never downgrades, only upgrades.

```
DEPTH_ORDER: {"surface": 0, "moderate": 1, "deep": 2}
```

Each turn: if current emotional_depth > deepest_emotional_depth, upgrade. Used as gate for CONSEQUENCE -> OWNERSHIP advancement (must reach "deep").

### 8.2 Objection Diffusion Steps
Tracked in `agent.py`, used in `decision.py`. Steps 0-3:

- **0**: No active objection being diffused
- **1**: Objection detected in OWNERSHIP/COMMITMENT, diffusion begins
- **2**: Objection isolated (prospect confirmed they still want solution)
- **3**: Objection resolved (prospect agreed to move forward)

Transitions:
- Objection detected in late phase: 0 -> 1
- Repeated diffusion status: restart at 1
- Diffused status: maintain >= 1
- Isolated status: maintain >= 2
- Resolved status: set to 3
- User says AGREEMENT while step > 0: hard reset to 0

Resets to 0 on phase change.

### 8.3 Ownership Substep Machine
Tracked in `agent.py`, enforced in `decision.py`. Steps 0-6:

| From | To | Condition |
|------|----|-----------|
| 0 | 1 | First turn in OWNERSHIP |
| 1 | 2 | Commitment question asked + prospect positive response |
| 2 | 3 | Self-persuasion failed (thin/vague) |
| 2 | 4 | Self-persuasion succeeded (prospect articulated reason) |
| 3 | 4 | Auto-advance next turn (bridge lasts one turn only) |
| 4 | 5/6 | Price stated, then: objection -> 5, agreement -> 6 |
| 5 | 6 | Objection resolved or agreement received |

Resets to 0 on phase change.

### 8.4 Repetition Detection
Tracked via `consecutive_no_new_info` counter:
- new_information == true: reset to 0
- new_information == false: increment
- Threshold >= 2: triggers force-advance (if >= 50% criteria met) or BREAK_GLASS

### 8.5 Retry Counter
Incremented by: PROBE, BREAK_GLASS, default STAY
NOT incremented by: confusion routing, minimum turn enforcement
Reset to 0 by: ADVANCE, REROUTE

---

## 9. Situation Playbooks

Defined in `playbooks.py`. Each has: instruction template, max_consecutive_uses, overrides_action flag.

| Playbook | Trigger | Override Action? | Max Uses | Strategy |
|----------|---------|-----------------|----------|----------|
| `confusion_recovery` | user_intent == CONFUSION | Yes (STAY) | 2 | Apologize briefly, state value in 1 sentence tied to pain, ask yes/no |
| `bridge_with_their_words` | Ownership substep 2, thin response | Yes (STAY) | 1 | Use prospect's exact pain words to bridge to offer |
| `resolve_and_close` | OWNERSHIP + isolated objection + agreement | No | 1 | Ask conditional close: "if we could figure out the [objection]..." |
| `graceful_alternative` | Late phase + same objection repeated | Yes (STAY) | 1 | Offer free workshop as positive option, not consolation |
| `dont_oversell` | Spontaneous buy signal in CONSEQUENCE/OWNERSHIP | Yes (STAY) | 1 | Stop asking. Present offer directly. State $10K. Wait. |
| `graceful_exit` | Hard no + high intensity + late phase | Yes (STAY) | 1 | Acknowledge warmly, offer free workshop, end. No re-selling. |
| `energy_shift` | 3+ consecutive thin/low-energy turns | No | 1 | Acknowledge "I know I'm asking a lot", share observation, easier question |
| `specific_probe` | Thin + surface + critical phase + PROBE | No | 2 | Ask lived-experience question: "When was the last time...?" |
| `ownership_ceiling` | 8+ turns in OWNERSHIP | Yes (STAY) | 1 | Force free workshop offer. If yes -> COMMITMENT, if no -> end |

Templates use `{variable}` substitution from prospect profile (pain_points, frustrations, cost_of_inaction, prospect_name, objection_type). Falls back to raw instruction on template errors.

---

## 10. Data Models

### Enums (`models.py`, `schemas.py`)

**UserIntent**: DIRECT_ANSWER, DEFLECTION, QUESTION, OBJECTION, SMALL_TALK, AGREEMENT, PUSHBACK, CONFUSION

**ObjectionType**: PRICE, TIMING, AUTHORITY, NEED, NONE

**NepqPhase**: CONNECTION, SITUATION, PROBLEM_AWARENESS, SOLUTION_AWARENESS, CONSEQUENCE, OWNERSHIP, COMMITMENT, TERMINATED

**SessionStatus**: ACTIVE, COMPLETED, ABANDONED

### ProspectProfile (`models.py`)
```python
# Connection
name, role, company, industry: Optional[str]
# Situation
current_state: Optional[str], team_size: Optional[str], tools_mentioned: List[str]
# Problem Awareness
pain_points: List[str], frustrations: List[str]
# Solution Awareness
desired_state: Optional[str], success_metrics: List[str]
# Consequence
cost_of_inaction, timeline_pressure, competitive_risk: Optional[str]
# Ownership
decision_authority, decision_timeline, budget_signals: Optional[str]
# Commitment
email, phone: Optional[str]
# Cross-phase
objections_encountered: List[str], objections_resolved: List[str]
```

Profile updates: list fields APPEND (deduplicated), scalar fields REPLACE if non-null.

### ThoughtLog (`models.py`)
Stored as JSON array in DBSession.thought_logs. Each turn appends:
```python
turn_number, user_message, comprehension (ComprehensionOutput),
decision (DecisionOutput), response_phase, response_text, profile_snapshot
```

### Database Tables (`database.py`)

**DBSession**: id (8-char UUID), status, current_phase, pre/post_conviction, cds_score, start/end_time, message_count, retry_count, turn_number, consecutive_no_new_info, turns_in_current_phase, deepest_emotional_depth, objection_diffusion_step, ownership_substep, prospect_profile (JSON text), thought_logs (JSON text), escalation_sent

**DBMessage**: id (UUID), session_id (indexed), role, content, timestamp, phase

---

## 11. API Endpoints

Base: `/api`

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/sessions` | Create session (requires pre_conviction: 1-10) |
| POST | `/sessions/{id}/messages` | Send message, get Sally's response |
| GET | `/sessions/{id}` | Get session detail + messages + thought logs |
| GET | `/sessions` | List all sessions |
| POST | `/sessions/{id}/end` | Abandon session |
| GET | `/sessions/{id}/thoughts` | Debug: get thought logs |
| POST | `/sessions/{id}/post-conviction` | Submit post-conviction, compute CDS |
| POST | `/sessions/{id}/quality-score` | Run/re-run quality scoring |
| GET | `/metrics` | Aggregate statistics |
| GET | `/export/csv` | Export all sessions as CSV |
| GET | `/config` | Client config (Stripe keys, TidyCal path) |
| POST | `/checkout` | Create Stripe checkout session ($10,000) |
| GET | `/checkout/verify/{id}` | Verify Stripe payment status |

### Key Endpoint: POST `/sessions/{id}/messages`
1. Validate session active
2. Save user message to DB
3. Build conversation_history from all prior messages
4. Call `SallyEngine.process_turn()` with all state
5. Update session state from engine result
6. If session ended: fire async quality scoring + sheets logging
7. If entering OWNERSHIP (first time): send escalation email
8. Replace `[PAYMENT_LINK]` with real Stripe checkout URL
9. Save assistant message to DB
10. Return response

### Stripe Payment Link Replacement
When response contains `[PAYMENT_LINK]`:
- Creates Stripe checkout session: $10,000, payment mode
- Metadata: sally_session_id, prospect name/company/role
- success_url: `/booking/{sessionId}?payment=success&checkout_session_id={CHECKOUT_SESSION_ID}`
- cancel_url: `/booking/{sessionId}?payment=cancelled`
- Replaces `[PAYMENT_LINK]` with `checkout_session.url`

---

## 12. Quality Scoring

**File**: `quality_scorer.py`. Runs async (daemon thread) when session ends.

### Four Dimensions (0-100 scale)

| Dimension | Weight | What it measures |
|-----------|--------|------------------|
| Mirroring | 30% | Did Sally use prospect's exact phrases flagged by Layer 1? |
| Energy Matching | 20% | Did Sally's tone match analyst-detected energy level? |
| Structure | 25% | Did Mirror -> Validate -> Question pattern hold per turn? |
| Emotional Arc | 25% | Coherent emotional progression across phases? |

### Scoring Input
- Full conversation transcript formatted as `[Phase] Role: Content`
- Thought log summary per turn: prospect_exact_words, emotional_cues, energy_level, emotional_tone, new_information, response_text (first 200 chars)

### Output: `ConversationQualityScore`
```python
mirroring_score, mirroring_details, energy_matching_score, energy_matching_details,
structure_score, structure_details, emotional_arc_score, emotional_arc_details,
overall_score, recommendations: List[str]
```

---

## 13. External Integrations

### Stripe
- Product: "100x AI Discovery Workshop" ($10,000)
- Lazy price creation: searches for existing product, creates if not found
- Checkout sessions with session metadata
- Payment verification endpoint logs conversion to Sheets

### Gmail Escalation
- Triggers on first entry to OWNERSHIP phase
- Sends email to ESCALATION_EMAIL with prospect info + full transcript
- Uses SMTP_SSL (smtp.gmail.com:465)

### Google Sheets
- Fire-and-forget logging via webhook (daemon threads)
- Three log types: "session" (completed/abandoned), "hot_lead" (OWNERSHIP reached), "conversion" (payment confirmed)
- Custom redirect handler preserves POST method through redirects
- Transcript truncated to 49,000 chars (Sheets cell limit)

### TidyCal
- Free workshop booking link: `https://tidycal.com/{TIDYCAL_PATH}`
- Included verbatim in response text for free workshop prospects

---

## 14. Frontend Architecture

### Pages
- **ChatPage** (`/`): Main conversation interface with conviction modals, timer, phase indicator
- **DashboardPage** (`/dashboard`): Metrics and analytics
- **HistoryPage** (`/history`): List all completed sessions
- **BookingPage** (`/booking/:sessionId`): Post-conversation booking/payment flow

### Key Components
- `ConvictionModal`: Pre-chat 1-10 conviction score
- `PostConvictionModal`: Post-chat conviction + CDS display
- `PhaseIndicator`: Visual phase progression bar
- `MessageBubble`: Renders individual messages
- `ChatInput`: Message input (disabled when loading or ended)

### UX Flow
1. User opens ChatPage, shown ConvictionModal (pre-conviction 1-10)
2. Session created, greeting displayed
3. Messages exchanged with optimistic UI (user message shows before API response)
4. Timer runs with color warnings (amber > 25min, red > 28min)
5. Session ends -> PostConvictionModal appears
6. CDS (Conviction Delta Score) = post - pre conviction displayed
7. "Book & Pay" navigates to BookingPage

---

## 15. Turn-by-Turn Data Flow

```
USER MESSAGE ARRIVES
  |
  v
SAVE TO DB (user message with current phase)
  |
  v
LAYER 1: COMPREHENSION (LLM)
  -> Extracts: intent, objection, profile_updates, exit_criteria, emotional intel
  |
  v
UPDATE PROFILE (append lists, replace scalars)
  |
  v
TRACK STATE:
  -> consecutive_no_new_info (increment or reset)
  -> deepest_emotional_depth (ratchet up, never down)
  -> objection_diffusion_step (0-3 progression)
  -> ownership_substep (0-6 state machine)
  -> turns_in_current_phase (increment)
  |
  v
LAYER 2: DECISION (pure code)
  -> 12 priority-ordered checks
  -> Returns: action, target_phase, retry_count
  |
  v
SITUATION DETECTION (after decision)
  -> Checks for playbook triggers
  -> May override action to STAY, inject playbook instructions
  |
  v
BUILD EMOTIONAL CONTEXT (for Layer 3)
  -> prospect_exact_words, emotional_cues, energy_level
  -> exit_evaluation_criteria, ownership_substep
  |
  v
LAYER 3: RESPONSE (LLM)
  -> Generates Sally's response
  -> Circuit breaker validates output
  |
  v
SIDE EFFECTS:
  -> If session_ended: async quality scoring, sheets logging
  -> If entering OWNERSHIP: escalation email
  -> If [PAYMENT_LINK] in response: create Stripe checkout
  |
  v
SAVE TO DB + RETURN TO CLIENT
  -> Updated phase, retry_count, all state counters
  -> phase_changed, session_ended flags
```

---

## 16. Critical Edge Cases

### State Machine Edge Cases
- **Ownership substep 3 (bridge)**: Uses `original_substep` variable to distinguish "just entered 3" from "was already in 3" to prevent double-advance
- **Emotional depth ratchet**: ONLY metric that persists across phase changes (never resets)
- **Objection diffusion hard reset**: User says AGREEMENT while step > 0 = reset to 0
- **All state counters reset on phase change**: turns_in_current_phase, objection_diffusion_step, ownership_substep

### Decision Layer Edge Cases
- **Confusion does NOT increment retry_count** (Sally's fault, not prospect's)
- **Minimum turn check does NOT increment retry_count** (pacing, not failure)
- **Exit criteria checked BEFORE probe**: all criteria met = ADVANCE even if thin response
- **Late phase objections never reroute backward**: handled in-phase via NEPQ diffusion
- **Authority objections always STAY** (never reroute, ask "who else needs to weigh in?")
- **Contact info gate**: can't END without email/phone after positive signal
- **CONSEQUENCE -> OWNERSHIP requires deep emotional depth**
- **Break Glass two-tier**: force advance at max_retries if >= 50% criteria, hard ceiling at max_retries + 2

### Response Layer Edge Cases
- **No conversation history**: return hardcoded greeting
- **Multiple questions**: keep only up to first "?"
- **Response too short after cleaning**: return fallback
- **Quote-wrapped response**: unwrap before circuit breaker
- **Closing messages**: relaxed to 10 sentence limit, 300 max tokens

### API Edge Cases
- **Engine processing error**: return safe response, increment retry, continue
- **Profile/thought_log parse failure**: treat as empty
- **Quality scoring thread error**: log, don't crash
- **Stripe missing API key**: fall back to STRIPE_PAYMENT_LINK env var
- **Gmail config missing**: log warning, skip escalation

---

## 17. Key Constants Reference

| Constant | Value | Location |
|----------|-------|----------|
| LLM Model | claude-sonnet-4-20250514 | comprehension.py, response.py, quality_scorer.py |
| Workshop price | $10,000 (1000000 cents) | main.py, response.py |
| Session time limit | 30 minutes | decision.py |
| Comprehension max_tokens | 800 | comprehension.py |
| Response max_tokens (normal) | ~200 (phase-dependent) | phase_definitions.py |
| Response max_tokens (closing) | 300 | response.py |
| Comprehension context window | Last 10 messages | comprehension.py |
| Response context window | Last 8 messages | response.py |
| Quality scorer max_tokens | 1500 | quality_scorer.py |
| Session ID format | 8-char uppercase UUID | main.py |
| Mirror detection window | Last 3 user/Sally pairs | response.py |
| Mirror trigram length | 3+ consecutive words in first 8 words | response.py |
| Repetition threshold | 2 consecutive no-new-info turns | decision.py |
| CRITICAL_PHASES (probe trigger) | PROBLEM_AWARENESS, CONSEQUENCE, OWNERSHIP | decision.py |
| LATE_PHASES (no reroute) | OWNERSHIP, COMMITMENT | decision.py |
| EARLY_PHASES (no editorializing) | CONNECTION, SITUATION, PROBLEM_AWARENESS, SOLUTION_AWARENESS | response.py |
| Ownership hard ceiling | 8 turns | decision.py |
| Prompt caching type | ephemeral | all LLM layers |
| Sheets transcript limit | 49,000 chars | sheets_logger.py |
| Depth order | surface=0, moderate=1, deep=2 | agent.py |

### Objection Routing Map (early phases only)
| Objection | Reroute Target |
|-----------|---------------|
| PRICE | CONSEQUENCE |
| TIMING | PROBLEM_AWARENESS |
| NEED | SOLUTION_AWARENESS |
| AUTHORITY | Never reroutes (STAY) |

### Environment Variables
```
DATABASE_URL          — PostgreSQL connection string
ANTHROPIC_API_KEY     — Claude API key
STRIPE_SECRET_KEY     — Stripe secret
STRIPE_PUBLISHABLE_KEY — Stripe publishable
STRIPE_PAYMENT_LINK   — Fallback payment link
TIDYCAL_PATH          — TidyCal booking path
GMAIL_USER            — Gmail sender
GMAIL_APP_PASSWORD    — Gmail app password
ESCALATION_EMAIL      — Hot lead notification email
GOOGLE_SHEETS_WEBHOOK_URL — Sheets logging webhook
FRONTEND_URL          — Frontend base URL (for Stripe redirects)
VITE_API_URL          — Frontend API base URL
```

---

## Evolution (Git History)

The system was built incrementally:

1. **V0.5**: Basic UI and logic
2. **Sprint 1-2**: NEPQ chat agent with SQLite, dashboard, history
3. **Deployment prep**: Dependencies, CORS, API URL config
4. **Three-layer engine**: PostgreSQL migration, Stripe/Calendly integration
5. **Block 2-6**: Post-conviction CDS, CSV export, fact sheet RAG, Gmail escalation
6. **Tollgate**: Sheets logging, Stripe checkout, TidyCal booking, NEPQ tuning
7. **Mirroring overhaul**: Sally mirrors prospect language naturally
8. **Robustness**: Timeouts, retry UI, crash prevention
9. **Emotional intelligence**: Pipeline across all 3 layers
10. **Checklist exit criteria**: Repetition detection, quality scoring
11. **NEPQ pacing**: Probing, emotional depth gating, detached tone
12. **Fix probe blocking**: Fixed PROBE preventing advancement + verbatim parroting
13. **Response pacing**: Phase-specific response length, prompt caching, reduced min_turns
14. **OWNERSHIP state machine**: Ownership substeps and situation playbook system
