# Sally Sells — Complete Technical Reference

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [Tech Stack](#3-tech-stack)
4. [Backend: Three-Layer NEPQ Engine](#4-backend-three-layer-nepq-engine)
   - [Layer 1: Comprehension (Gemini Flash)](#41-layer-1-comprehension-gemini-flash)
   - [Layer 2: Decision (Deterministic)](#42-layer-2-decision-deterministic)
   - [Layer 3: Response (Claude Sonnet)](#43-layer-3-response-claude-sonnet)
   - [Engine Orchestrator](#44-engine-orchestrator-agentpy)
5. [Data Models](#5-data-models)
   - [ProspectProfile](#51-prospectprofile)
   - [ComprehensionOutput](#52-comprehensionoutput)
   - [DecisionOutput](#53-decisionoutput)
   - [PhaseExitEvaluation](#54-phaseexitevaluation)
   - [ConversationQualityScore](#55-conversationqualityscore)
6. [Phase Definitions & NEPQ Framework](#6-phase-definitions--nepq-framework)
7. [Situation Playbooks](#7-situation-playbooks)
8. [Circuit Breaker & Guardrails](#8-circuit-breaker--guardrails)
9. [OWNERSHIP Close Sequence](#9-ownership-close-sequence)
10. [State Tracking & Counters](#10-state-tracking--counters)
11. [API Endpoints](#11-api-endpoints)
12. [Database Schema](#12-database-schema)
13. [Frontend](#13-frontend)
14. [Integrations](#14-integrations)
15. [Quality Scoring System](#15-quality-scoring-system)
16. [Environment Variables](#16-environment-variables)
17. [Deployment](#17-deployment)
18. [Directory Structure](#18-directory-structure)
19. [Data Flow: Complete Request Lifecycle](#19-data-flow-complete-request-lifecycle)

---

## 1. Project Overview

**Sally Sells** is an AI-powered NEPQ (Neuro-Emotional Persuasion Questioning) sales agent built for 100x. Sally conducts real-time chat-based sales conversations to sell a $10,000 AI Discovery Workshop led by 100x CEO Nik Shah.

The system uses a proprietary three-layer AI engine that separates analysis, decision-making, and response generation into distinct layers, producing natural, empathetic, and strategically sequenced conversations that guide prospects through the NEPQ sales framework.

**What Sally Does:**
- Engages prospects in natural, text-based conversations
- Follows the 7-phase NEPQ methodology (Connection through Commitment)
- Mirrors prospect language for deep rapport building
- Handles objections using NEPQ diffusion techniques (not scripted rebuttals)
- Collects contact information and sends payment/booking links
- Offers a free workshop fallback for prospects who decline the paid option
- Logs all sessions to Google Sheets and escalates hot leads via Gmail
- Scores conversation quality post-completion

---

## 2. Architecture

### High-Level Architecture

```
                         +---------------------+
                         |   Vercel (Frontend)  |
                         |  React + Vite + TS   |
                         +---------+-----------+
                                   |
                              HTTPS (REST API)
                                   |
                         +---------v-----------+
                         |  Render (Backend)    |
                         |  FastAPI + Python    |
                         +---------+-----------+
                                   |
              +--------------------+--------------------+
              |                    |                     |
    +---------v------+   +--------v-------+   +---------v------+
    | Neon PostgreSQL |   | Google Gemini  |   | Anthropic API  |
    | (Primary DB)    |   | Flash (L1)     |   | Claude (L3/QS) |
    +-----------------+   +----------------+   +----------------+
              |
    +---------+----+----+----+
    |              |         |
    v              v         v
  Stripe       TidyCal    Gmail        Google Sheets
  (Payments)   (Booking)  (Escalation) (Webhook Log)
```

### Three-Layer Engine Architecture

```
User Message
    |
    v
+---------------------------------------------------+
| Layer 1: COMPREHENSION (The Analyst)               |
| Model: Gemini 2.0 Flash (google-generativeai)      |
| Temp: 0.1 | Max tokens: 1500                       |
| Role: Analyze user intent, extract profile data,   |
|       evaluate exit criteria checklist (boolean),   |
|       detect objections, assess emotional signals,  |
|       response richness, emotional depth, energy    |
| Output: ComprehensionOutput (structured JSON)       |
+---------------------------------------------------+
    |
    v
+---------------------------------------------------+
| Layer 2: DECISION (The Manager)                    |
| Model: None (pure deterministic logic)             |
| Role: Phase transitions, objection routing,        |
|       probing, break glass, min turn enforcement,  |
|       emotional depth gating, repetition detection, |
|       situation playbook selection                  |
| Output: DecisionOutput (action + target_phase)      |
+---------------------------------------------------+
    |
    v
+---------------------------------------------------+
| Layer 3: RESPONSE (The Speaker)                    |
| Model: Claude Sonnet 4 (claude-sonnet-4-20250514)  |
| System: SALLY_PERSONA (cached with ephemeral CC)    |
| Max tokens: 120-300 (phase-dependent)               |
| Role: Generate Sally's reply constrained by        |
|       Layer 2's decision + NEPQ persona + playbooks |
| Post-processing: Circuit breaker validation         |
| Output: response_text (string)                      |
+---------------------------------------------------+
    |
    v
Save to DB + Integrations (Sheets, Gmail, Stripe)
```

---

## 3. Tech Stack

### Backend

| Tool | Purpose | Details |
|------|---------|---------|
| **Python** | Runtime | 3.13+ |
| **FastAPI** | Web framework | REST API server |
| **Uvicorn** | ASGI server | Production server with `$PORT` |
| **SQLAlchemy** | ORM | Database abstraction, lazy engine init |
| **Pydantic** | Data validation | Request/response schemas + internal models |
| **psycopg2-binary** | PostgreSQL driver | Neon database connectivity |
| **python-dotenv** | Environment config | Single load in `database.py` |
| **google-generativeai** | Layer 1 AI | Gemini 2.0 Flash for comprehension |
| **Anthropic SDK** | Layer 3 AI | Claude Sonnet 4 for response + quality scoring |
| **Stripe SDK** | Payments | Checkout Sessions for $10K workshop |
| **eval-type-backport** | Compatibility | Type evaluation backport |

### Frontend

| Tool | Purpose | Details |
|------|---------|---------|
| **React** | UI framework | 19.2.0 |
| **TypeScript** | Language | Type-safe frontend code |
| **Vite** | Build tool | Fast dev server + production builds |
| **React Router** | Routing | 7.13.0, client-side navigation |
| **Tailwind CSS** | Styling | Utility-first CSS framework |
| **Lucide React** | Icons | Consistent icon library |
| **date-fns** | Date formatting | Human-readable timestamps |

### Infrastructure & Services

| Tool | Purpose | Details |
|------|---------|---------|
| **Render** | Backend hosting | Free tier, auto-deploy from `main` |
| **Vercel** | Frontend hosting | Auto-deploy from `main`, Vite build |
| **Neon** | PostgreSQL database | Serverless Postgres (primary DB) |
| **Google Gemini** | Layer 1 AI | Gemini 2.0 Flash for comprehension analysis |
| **Anthropic API** | Layer 3 AI | Claude Sonnet 4 for response generation + quality scoring |
| **Stripe** | Payment processing | Checkout Sessions, test mode |
| **Google Sheets** | Conversation logging | Apps Script webhook, fire-and-forget |
| **Gmail SMTP** | Email escalation | App password auth, hot lead alerts |
| **TidyCal** | Booking calendar | Free workshop scheduling |

---

## 4. Backend: Three-Layer NEPQ Engine

### 4.1 Layer 1: Comprehension (Gemini Flash)

**File:** `backend/app/layers/comprehension.py`

**Purpose:** Analyze each user message and produce structured JSON output. This layer listens and analyzes -- it never talks to the prospect.

**Model:** Gemini 2.0 Flash (`gemini-2.0-flash`) via `google-generativeai` SDK
- Temperature: 0.1 (near-deterministic)
- Max output tokens: 1500
- Safety settings: BLOCK_NONE for all categories (conversational content needs this)
- Lazy config: `_ensure_gemini_configured()` on first call using `GEMINI_API_KEY`

**Environment Variables:** `GEMINI_API_KEY`

**System Prompt Structure:**
- `COMPREHENSION_SYSTEM_PROMPT_BASE`: Covers factual analysis, emotional intelligence, exit criteria evaluation rules, response richness, emotional depth, new information detection, objection types
- `COMPREHENSION_OWNERSHIP_SECTION`: Added only for OWNERSHIP/COMMITMENT phases, covers diffusion status tracking, self-persuasion criteria, price/definitive response rules

**Input (via `build_comprehension_prompt()`):**
- Current NEPQ phase + phase definition/purpose
- Exit criteria checklist (phase-specific, machine-readable)
- Conversation history (last 10 messages)
- Current prospect profile (accumulated)
- Latest user message
- Phase-specific extraction targets

**Output: `ComprehensionOutput`** containing:

| Field | Type | Description |
|-------|------|-------------|
| `user_intent` | Enum | DIRECT_ANSWER, DEFLECTION, QUESTION, OBJECTION, SMALL_TALK, AGREEMENT, PUSHBACK, CONFUSION |
| `emotional_tone` | String | e.g. engaged, skeptical, frustrated, defensive, excited, neutral, warm, guarded |
| `emotional_intensity` | String | low, medium, or high |
| `objection_type` | Enum | PRICE, TIMING, AUTHORITY, NEED, NONE |
| `objection_detail` | String | Specific objection text (if any) |
| `profile_updates` | Dict | Key-value pairs to update on ProspectProfile |
| `exit_evaluation` | PhaseExitEvaluation | Per-criterion boolean checklist with evidence |
| `response_richness` | String | thin (1-5 words/filler) / moderate (real sentence) / rich (multi-sentence, vivid) |
| `emotional_depth` | String | surface (factual) / moderate (expressed feeling) / deep (vulnerability, personal stakes) |
| `new_information` | Bool | Whether this turn contains substantive NEW information |
| `objection_diffusion_status` | String | not_applicable / diffused / isolated / resolved / repeated |
| `prospect_exact_words` | List[str] | 2-3 exact phrases worth mirroring |
| `emotional_cues` | List[str] | Specific emotional signals with context |
| `energy_level` | String | low/flat, neutral, warm, high/excited |
| `summary` | String | One-sentence turn summary |

**Critical Analysis Rules:**
- Only extract information the prospect EXPLICITLY stated
- Never infer or assume pain points
- Exit criteria are evaluated cumulatively across full conversation
- Short answers CAN satisfy criteria (e.g., "dev at fintech startup" = role + industry)
- "yeah" or "ok" with no new info satisfies NOTHING new
- Check existing profile -- if role is already filled from a previous turn, "role_shared" IS met
- CONFUSION is NOT PUSHBACK (separate intent classification)

**Error Handling:**
- If Gemini returns invalid JSON, retry once
- If both attempts fail, return safe defaults (all criteria unmet, DIRECT_ANSWER intent)
- Markdown wrapping (```json...```) is stripped automatically

---

### 4.2 Layer 2: Decision (Deterministic)

**File:** `backend/app/layers/decision.py`

**Purpose:** Pure deterministic logic. No LLM calls. Makes all phase transition and action decisions based on Layer 1's structured output.

**Key Constants:**
- `PHASE_ORDER`: Strict sequence from CONNECTION through COMMITMENT
- `CRITICAL_PHASES`: PROBLEM_AWARENESS, CONSEQUENCE, OWNERSHIP (require substantive engagement)
- `LATE_PHASES`: OWNERSHIP, COMMITMENT (handle objections in-phase, never reroute backward)
- `OBJECTION_ROUTING`: Map of objection types to earlier phases (early phases only)

**Decision Priority (`make_decision()`) -- evaluated in order:**

| # | Check | Action | Retry Effect |
|---|-------|--------|--------------|
| 1 | Session time limit (30 min / 1800s) | END | N/A |
| 2 | Already in TERMINATED | END | N/A |
| 3 | Objection detected | REROUTE (early) / STAY with DIFFUSE context (late) / STAY for AUTHORITY / STAY for caveats (AGREEMENT+objection) | No increment |
| 3b | CONFUSION intent | STAY with confusion_recovery playbook | No increment |
| 4 | Gap Builder constraint (missing required profile fields) | STAY | No increment |
| 5 | Minimum turns not reached | STAY | No increment |
| 6 | All exit criteria met | ADVANCE (or END if next is TERMINATED) | Reset to 0 |
| 6a | Emotional depth gate (CONSEQUENCE->OWNERSHIP) | STAY if depth insufficient | No increment |
| 6b | OWNERSHIP substep enforcement (8+ turns = ceiling) | STAY with ownership_ceiling playbook | No increment |
| 7 | Thin/surface response in critical phase | PROBE with target criterion | +1 |
| 8 | Repetition (2+ turns no new info) | ADVANCE if 50%+ criteria met / BREAK_GLASS otherwise | Reset or +1 |
| 9 | Retry count >= max_retries | ADVANCE if 50%+ criteria met / BREAK_GLASS / ADVANCE at hard ceiling (max+2) | Reset or +1 |
| 10 | Default | STAY | +1 |

**Actions:**

| Action | Description | Retry Count |
|--------|-------------|-------------|
| `ADVANCE` | Move to next NEPQ phase | Reset to 0 |
| `STAY` | Remain in current phase | Usually +1 (exceptions: min turns, gap builder, confusion) |
| `PROBE` | Dig deeper on thin response | +1 |
| `REROUTE` | Jump to earlier phase (objection routing, early phases only) | Reset to 0 |
| `BREAK_GLASS` | Try different angle (stuck too long) | +1 |
| `END` | Terminate the session | N/A |

**Objection Routing Map (early phases only):**

| Objection | Routes To | Rationale |
|-----------|-----------|-----------|
| PRICE | CONSEQUENCE | Remind cost of inaction |
| TIMING | PROBLEM_AWARENESS | Remind pain |
| NEED | SOLUTION_AWARENESS | Remind desired state |
| AUTHORITY | Stay in current phase | Clarify decision process |

**Late Phase Exception:** OWNERSHIP and COMMITMENT handle objections in-phase via NEPQ diffusion. Never reroute backward -- the prospect has already progressed through the emotional journey.

**Emotional Depth Gate (CONSEQUENCE -> OWNERSHIP):**
- "deep" emotional depth: always passes
- "moderate" depth: passes after 3+ turns in phase
- "surface" depth: passes after 4+ turns (hard fallback to prevent infinite loops)
- Rationale: Getting to OWNERSHIP where the sale happens is more important than perfect emotional depth

**Situation Playbook Detection (`detect_situation()`):**
Runs AFTER `make_decision()` to overlay additional playbook instructions. Priority-ordered, first match wins:

| Priority | Situation | Playbook |
|----------|-----------|----------|
| 1 | Hard no in late phases (PUSHBACK + high intensity) | `graceful_exit` |
| 1.5 | Repeated price objection in COMMITMENT after 4+ turns | `graceful_alternative` |
| 2 | Spontaneous buy signal in CONSEQUENCE/OWNERSHIP | `dont_oversell` |
| 3 | Same objection repeated after diffusion | `graceful_alternative` |
| 4 | Prospect said yes to isolation in OWNERSHIP | `resolve_and_close` |
| 5 | 3 consecutive thin/flat turns | `energy_shift` |
| 6 | Thin/surface in critical phase during PROBE | `specific_probe` |

---

### 4.3 Layer 3: Response (Claude Sonnet)

**File:** `backend/app/layers/response.py`

**Purpose:** Generate Sally's actual response text, tightly constrained by Layer 2's decision.

**Model:** Claude Sonnet 4 (`claude-sonnet-4-20250514`) via Anthropic SDK
- System prompt: `SALLY_PERSONA` (cached with `cache_control: {"type": "ephemeral"}`)
- Max tokens: Phase-dependent (120-300)
- Lazy client initialization via `_get_client()`

**Environment Variables:** `ANTHROPIC_API_KEY`, `TIDYCAL_PATH`

**SALLY_PERSONA (System Prompt) -- Key Elements:**

*Core Identity:*
- Sharp, genuinely curious NEPQ sales consultant at 100x
- Problem finder, NOT product pusher (prospect talks 80% of the time)
- Texts like a real person (fragments, contractions, casual tone)
- Confident but never pushy

*NEPQ Tonalities (adapted for text chat):*
- CURIOUS: Question-forward in phases 1-4
- CONCERNED: Slower pacing, "..." pauses in phase 5
- EMPATHETIC: Reflect emotional words back simply
- SKEPTICAL: Of the status quo, not the prospect
- CONVICTION: Grounded calm in phases 6-7

*Tone by Phase:*
- Phases 1-4 (CONNECTION through SOLUTION_AWARENESS): Curious and NEUTRAL. No editorializing. Doctor taking a history.
- Phase 5 (CONSEQUENCE): Can reflect emotions back, but ONLY those the prospect expressed. Use "..." pauses.
- Phases 6-7 (OWNERSHIP, COMMITMENT): Warmer, earned through the journey. CONVICTION tonality.

*Response Structure:*
1. MIRROR (optional, 2-5 words): Brief acknowledgment using 1-2 of their key words
2. ONE QUESTION: Specific, builds on what they said

*Hard Rules:*
1. ONE question per response max (never stack with "and" or "like")
2. 1-2 sentences in phases 1-4, up to 4 in later phases
3. Never mention workshop/100x/Nik Shah/price before OWNERSHIP phase
4. Never give advice before OWNERSHIP phase
5. No hype words (19 forbidden words)
6. Never start response with prospect's words as a fragment echo
7. Use "..." only in CONSEQUENCE, OWNERSHIP, COMMITMENT
8. Stop selling when they say yes
9. Never repeat a question
10. No em dashes or semicolons
11. In phases 1-4: NO editorializing
12. VARY question structure (never same opener twice in a row)

**Response Prompt Builder (`build_response_prompt()`):**

The prompt is dynamically assembled from many components:

| Component | When Active | Purpose |
|-----------|-------------|---------|
| Phase instructions | Always | Length limits, phase purpose |
| Emotional intelligence briefing | When Layer 1 provides context | Exact words, energy, intensity, cues |
| Criteria guidance (`CRITERIA_GUIDANCE` dict) | When criteria are unmet | Tells Sally WHAT to steer toward |
| Mirror variation enforcement | When 2+ recent mirrors detected | Force different opener |
| PROBE instructions | When action=PROBE | Dig deeper on specific criterion |
| OWNERSHIP substep instructions | OWNERSHIP phase | Steps 1-6 of NEPQ close sequence |
| Playbook injection | When playbook detected | Override default phase behavior |
| NEPQ objection diffusion protocol | Late phases with objection | Diffuse/isolate/resolve sequence |
| Break Glass instructions | When action=BREAK_GLASS | Try completely different angle |
| Transition instructions | When action=ADVANCE | Smooth phase bridging |
| Contact collection | COMMITMENT/TERMINATED | Email -> phone -> link sequence |
| Post-objection closing | COMMITMENT when link already sent | Don't re-send Stripe link |
| End instructions | When action=END | Graceful wrap-up |
| Fact sheet RAG | Always (loaded from `fact_sheet.txt`) | Ground truth about 100x |

**Criteria Guidance Map (`CRITERIA_GUIDANCE` dict):**
Maps each unmet criterion ID to natural-language guidance for Sally. Examples:
- `role_shared` -> "Find out what they do. Ask about their role or position."
- `specific_pain_articulated` -> "Get them to describe a specific pain point in their OWN words. Don't suggest pains."
- `cost_acknowledged` -> "Help them quantify the cost of not fixing this. Time, money, people, opportunity."

**Token Limits by Phase:**

| Phase | max_sentences | max_tokens |
|-------|---------------|------------|
| CONNECTION | 2 | 120 |
| SITUATION | 2 | 120 |
| PROBLEM_AWARENESS | 3 | 150 |
| SOLUTION_AWARENESS | 3 | 150 |
| CONSEQUENCE | 3 | 180 |
| OWNERSHIP | 4 | 200 |
| COMMITMENT | 4 | 300 |
| Closing messages | 10 (relaxed) | 300 |

---

### 4.4 Engine Orchestrator (`agent.py`)

**File:** `backend/app/agent.py`

**Class:** `SallyEngine` (all static methods)

**`process_turn()` -- Full Orchestration Flow:**

```
1. Parse profile from JSON
2. Layer 1: run_comprehension() -> ComprehensionOutput
3. Update profile with Layer 1 extractions (list fields append, scalars replace)
4. Track objections in profile (append to objections_encountered)
5. Update state counters:
   a. consecutive_no_new_info (reset on new info, increment otherwise)
   b. deepest_emotional_depth (only upgrades: surface -> moderate -> deep)
   c. objection_diffusion_step (0-3 progression, reset on agreement)
   d. ownership_substep (0-6 state machine, see OWNERSHIP section)
   e. turns_in_current_phase (+1)
6. Layer 2: make_decision() -> DecisionOutput
7. Situation playbook detection: detect_situation() -> overlay on decision
8. Build emotional_context dict from Layer 1 for Layer 3
9. Layer 3: generate_response() -> response_text (with circuit breaker)
10. Build ThoughtLog record
11. Determine phase_changed, session_ended
12. Reset phase-specific counters on phase change (turns, diffusion, substep)
13. Return result dict with all state
```

**Return Dict Structure:**
```python
{
    "response_text": str,           # Sally's message to prospect
    "new_phase": str,               # Phase after this turn
    "new_profile_json": str,        # Updated prospect profile
    "thought_log_json": str,        # Full thought log for this turn
    "phase_changed": bool,          # Whether phase transitioned
    "session_ended": bool,          # Whether session is over
    "retry_count": int,             # Updated retry counter
    "consecutive_no_new_info": int, # Repetition counter
    "turns_in_current_phase": int,  # Phase turn counter
    "deepest_emotional_depth": str, # Emotional depth high watermark
    "objection_diffusion_step": int,# Diffusion protocol progress
    "ownership_substep": int,       # OWNERSHIP state machine step
}
```

**Latency Logging:** Each layer's execution time is logged:
```
[Turn 3] LATENCY SUMMARY: L1=450ms | L2=1ms | L3=1200ms | Total=1651ms
```

---

## 5. Data Models

**File:** `backend/app/models.py`

### 5.1 ProspectProfile

Sally's "notepad" -- accumulates facts extracted from each message:

```python
class ProspectProfile(BaseModel):
    # Connection phase
    name: Optional[str]
    role: Optional[str]
    company: Optional[str]
    industry: Optional[str]

    # Situation phase
    current_state: Optional[str]
    team_size: Optional[str]
    tools_mentioned: List[str]        # append-only

    # Problem Awareness
    pain_points: List[str]            # append-only
    frustrations: List[str]           # append-only

    # Solution Awareness
    desired_state: Optional[str]
    success_metrics: List[str]        # append-only

    # Consequence
    cost_of_inaction: Optional[str]
    timeline_pressure: Optional[str]
    competitive_risk: Optional[str]

    # Ownership
    decision_authority: Optional[str]
    decision_timeline: Optional[str]
    budget_signals: Optional[str]

    # Contact info (collected at close)
    email: Optional[str]
    phone: Optional[str]

    # Objection tracking
    objections_encountered: List[str]  # append-only
    objections_resolved: List[str]     # append-only
```

**Update behavior:** List fields (pain_points, frustrations, tools_mentioned, success_metrics, objections_encountered, objections_resolved) are append-only (deduplicated). Scalar fields are replaced when a new non-empty value is provided.

### 5.2 ComprehensionOutput

Complete output from Layer 1 (see Layer 1 section for full field descriptions).

### 5.3 DecisionOutput

```python
class DecisionOutput(BaseModel):
    action: str          # ADVANCE, STAY, PROBE, REROUTE, BREAK_GLASS, END
    target_phase: str    # Phase Sally should respond from
    reason: str          # Human-readable explanation
    objection_context: Optional[str]  # Objection details or "PLAYBOOK:name"
    retry_count: int     # Updated retry counter
    probe_target: Optional[str]       # Criterion ID to probe (for PROBE action)
```

### 5.4 PhaseExitEvaluation

Checklist-based evaluation (replaced the old confidence scoring system):

```python
class PhaseExitEvaluation(BaseModel):
    criteria: dict[str, CriterionResult]  # {criterion_id: {met: bool, evidence: str}}
    reasoning: str
    missing_info: List[str]

    # Computed properties:
    criteria_met_count -> int
    criteria_total_count -> int
    all_met -> bool           # True when ALL criteria met
    fraction_met -> float     # 0.0 to 1.0
```

Each `CriterionResult` is `{met: bool, evidence: Optional[str]}`.

**Key change from old system:** Phase transitions are now driven by boolean checklist evaluation (all criteria must be met) rather than subjective confidence percentages.

### 5.5 ConversationQualityScore

Post-conversation evaluation (see Quality Scoring section):

```python
class ConversationQualityScore(BaseModel):
    mirroring_score: int            # 0-100
    mirroring_details: str
    energy_matching_score: int      # 0-100
    energy_matching_details: str
    structure_score: int            # 0-100
    structure_details: str
    emotional_arc_score: int        # 0-100
    emotional_arc_details: str
    overall_score: int              # 0-100 (weighted average)
    recommendations: List[str]
```

---

## 6. Phase Definitions & NEPQ Framework

**File:** `backend/app/phase_definitions.py`

7 active phases plus a terminal state. Each phase has exit criteria, min turns, max retries, and response length limits.

### Phase Specifications

| # | Phase | Purpose | Exit Criteria | Min Turns | Max Retries |
|---|-------|---------|---------------|-----------|-------------|
| 1 | **CONNECTION** | Build rapport. Get role, company, reason for interest. | `role_shared` + `company_or_industry_shared` + `ai_interest_stated` | 2 | 3 |
| 2 | **SITUATION** | Map current operations. Understand workflows, team, tools. | `workflow_described` + `concrete_detail_shared` | 1 | 3 |
| 3 | **PROBLEM_AWARENESS** | Surface a REAL pain point in the prospect's own words. | `specific_pain_articulated` + `pain_is_current` | 3 | 4 |
| 4 | **SOLUTION_AWARENESS** | Get them to paint their ideal future. Create the gap. | `desired_state_described` + `gap_is_clear` | 2 | 3 |
| 5 | **CONSEQUENCE** | Make cost of inaction real and personal. Build urgency. | `cost_acknowledged` + `urgency_felt` | 2 | 4 |
| 6 | **OWNERSHIP** | Present $10K workshop. Handle objections. Offer free fallback. | `commitment_question_asked` + `prospect_self_persuaded` + `price_stated` + `definitive_response` | 2 | 4 |
| 7 | **COMMITMENT** | Close. Collect email + phone. Send payment/booking link. | `positive_signal_or_hard_no` + `email_collected` + `phone_collected` + `link_sent` | 1 | 5 |
| 8 | **TERMINATED** | Session ended. | N/A | N/A | N/A |

### Exit Criteria Details

**CONNECTION:**
- `role_shared`: Prospect shared their role, job title, or what they do
- `company_or_industry_shared`: Prospect shared company name, what it does, or their industry
- `ai_interest_stated`: ANY reason they're interested in AI (even vague like "checking it out")

**SITUATION:**
- `workflow_described`: Described their current workflow, day-to-day, or process
- `concrete_detail_shared`: Mentioned something concrete (team size, tools, processes, volume)

**PROBLEM_AWARENESS:**
- `specific_pain_articulated`: Articulated a SPECIFIC pain/frustration in their OWN words (not suggested by Sally)
- `pain_is_current`: Pain is real and happening NOW (not hypothetical)

**SOLUTION_AWARENESS:**
- `desired_state_described`: Described what success or improvement would look like
- `gap_is_clear`: Clear contrast between current pain and desired state

**CONSEQUENCE:**
- `cost_acknowledged`: Acknowledged tangible cost of NOT solving (money, time, clients, stress)
- `urgency_felt`: Understands waiting has a price, expressed urgency/concern about inaction

**OWNERSHIP:**
- `commitment_question_asked`: Sally asked "do you feel like..." commitment question
- `prospect_self_persuaded`: PROSPECT articulated specific reason they feel solution could work (their own words, not "yeah")
- `price_stated`: $10,000 price explicitly communicated
- `definitive_response`: Clear yes to paid, yes to free, or hard no

**COMMITMENT:**
- `positive_signal_or_hard_no`: Positive signal (yes, sure) OR definitive hard no
- `email_collected`: Email address collected
- `phone_collected`: Phone number collected
- `link_sent`: Payment or booking link sent

**Helper Functions:**
- `get_phase_definition(phase)` -> full phase config dict
- `get_exit_criteria_checklist(phase)` -> `{criterion_id: description}` dict
- `get_confidence_threshold(phase)` -> int (legacy, still used in some paths)
- `get_max_retries(phase)` -> int
- `get_min_turns(phase)` -> int
- `get_response_length(phase)` -> `{max_sentences, max_tokens}` dict
- `get_required_profile_fields(phase)` -> list (for Gap Builder)

---

## 7. Situation Playbooks

**File:** `backend/app/playbooks.py`

Named playbooks that Layer 2 selects based on detected micro-situations. Layer 3 injects the playbook instructions into its prompt, overriding default phase behavior for that turn.

| Playbook | Trigger | Overrides Action | Max Uses | What It Does |
|----------|---------|------------------|----------|--------------|
| `confusion_recovery` | Prospect says "I don't understand" / CONFUSION intent | Yes (STAY) | 2 | Apologize briefly, restate value in 1 sentence tied to their pain, ask simple yes/no |
| `bridge_with_their_words` | Self-persuasion failed in OWNERSHIP (thin/confused response) | Yes (STAY) | 1 | Use prospect's EXACT pain words + consequences, state + connect + ask yes/no |
| `resolve_and_close` | Prospect said yes to isolation question in OWNERSHIP | No | 1 | "If we could figure out the [objection] piece, would you want to move forward?" |
| `graceful_alternative` | Same objection repeated after diffusion, OR price objection in COMMITMENT 4+ turns in | Yes (STAY) | 1 | Offer free workshop as POSITIVE option (not consolation), zero pressure |
| `dont_oversell` | Spontaneous buy signal ("I need to do something", "what do I need to do") | Yes (STAY) | 1 | Present offer directly. No more questions. They're already there. |
| `graceful_exit` | Hard no in late phases (PUSHBACK + high intensity) | Yes (STAY) | 1 | Acknowledge warmly, offer free workshop with zero pressure, end |
| `energy_shift` | 3 consecutive thin/flat turns | No | 1 | "I know I'm asking a lot of questions", share observation, ask easier question |
| `specific_probe` | Thin/surface in critical phase during PROBE | No | 2 | Ask about LIVED EXPERIENCE (time-anchored: "When was the last time...") |
| `ownership_ceiling` | 8+ turns in OWNERSHIP | Yes (STAY) | 1 | Offer free workshop once, then close |

**Template Variables:** Playbook instructions are templated with profile data:
- `{pain_points}`, `{frustrations}`, `{cost_of_inaction}`
- `{first_pain}`, `{pain_summary}`, `{consequence}`
- `{prospect_name}`, `{objection_type}`

---

## 8. Circuit Breaker & Guardrails

**File:** `backend/app/layers/response.py` (function: `circuit_breaker()`)

Post-generation validation that catches rule violations before they reach the prospect:

| Check | Detection | Action | Skip For Closing? |
|-------|-----------|--------|--------------------|
| Em dashes & semicolons | `—` or `;` in text | Replace with commas/periods | No |
| Multiple questions | Count of `?` > 1 | Keep only first question | Yes |
| "And" question stacking | `, and ` before `?` | Keep only first part | Yes |
| "Like" question stacking | `, like ` before `?` | Keep only first part | Yes |
| Forbidden words (19) | Word-level match | Replace ENTIRE response with fallback | No |
| Forbidden phrases (14) | Word-boundary regex match | Strip phrase, clean orphaned punctuation | No |
| Editorial phrases (22) | Word-boundary regex in early phases only | Strip phrase, clean punctuation | No |
| Fragment echo opener | 3+ consecutive user words in first 6 words of response | Strip echo, keep question | No |
| Pitching before CONSEQUENCE | $10,000/workshop/nik shah/100x in early phases | Replace with safe fallback | No |
| Response too long | > phase_max sentences | Trim to 4 sentences (10 for closing) | Relaxed |
| Response too short after cleaning | < 4 clean words | Return fallback | No |

**Forbidden Words (19):** guaranteed, revolutionary, game-changing, cutting-edge, transform, unlock, skyrocket, supercharge, unleash, incredible, amazing, unbelievable, mind-blowing, powerful, leverage, synergy, paradigm, disrupt, innovate

**Forbidden Phrases (14):** that's a great question, great point, i appreciate you sharing, absolutely, i completely understand, that's completely understandable, that makes total sense, that makes a lot of sense, i hear you, no worries, happens to the best of us, got it, tell me more, that's interesting

**Editorial Phrases (22, early phases only):** that's a whole thing, those are the worst, that's the dream, that's huge, that's no joke, that's a lot, that sounds tough, that sounds rough, that's really something, that's brutal, that sounds brutal, that's the worst, that's so frustrating, that's a crowded space, that's a hot combo, that's real work, that's a tough one, that's no small thing, that's tricky, that's rough, that's cool, that's smart, that's wild, wow

**Fallback Response:** `"How has that been playing out for you day-to-day?"`

**Mirror Repetition Detection (`_detect_mirror_repetition()`):**
Checks if 2+ of the last 3 Sally responses started by mirroring the prospect (3+ consecutive user words in first 8 words). If true, Layer 3 receives instructions to vary its opener.

---

## 9. OWNERSHIP Close Sequence

The OWNERSHIP phase follows Jeremy Miner's NEPQ close formula via a 6-step state machine tracked by `ownership_substep`:

### Substep State Machine

```
0 -> 1: First OWNERSHIP turn (auto-advance)
1 -> 2: Commitment question asked AND prospect gave positive response
2 -> 3: Self-persuasion failed (thin/vague/confused response)
2 -> 4: Self-persuasion succeeded (prospect articulated why)
3 -> 4: Bridge auto-advance (bridge is ONE attempt, advance next turn regardless)
4 -> 5: Price stated AND prospect objected
4 -> 6: Price stated AND prospect agreed (or definitive response)
5 -> 6: Objection resolved OR prospect agreed
```

### Substep Details

**Substep 1 - COMMITMENT QUESTION:**
"Based on everything we've talked about... do you feel like having a customized AI plan could help you [their specific desired outcome]?"
- Use "feel" not "think" (emotions drive 95% of decisions)
- Reference THEIR specific pain/desired state
- Use "..." pause. Curious tone, not assumptive.
- Do NOT mention price/workshop/100x/Nik yet

**Substep 2 - SELF-PERSUASION:**
"What makes you feel like it could work for you?"
- Get THEM to articulate their own reasons
- If vague: "Yeah? What specifically about it feels right?"
- Maximum 2 attempts at self-persuasion

**Substep 3 - BRIDGE (use their words):**
"Look, you told me [their exact pain]. And [their exact consequence]. This workshop is built to fix exactly that. Would you want to hear what it looks like?"
- Use THEIR exact words from earlier
- Max 2-3 sentences + yes/no
- ONE bridge attempt, then move to offer

**Substep 4 - PRESENT OFFER + CLOSING QUESTION:**
"So our CEO Nik Shah does a hands-on Discovery Workshop where he comes to [their company] and builds a customized AI plan with your team. It's a $10,000 investment."
- IMMEDIATELY follow with: "Would you be opposed to making that investment toward [their specific desired outcome]?"
- Use "opposed" or "against" framing (psychologically easier to say yes)
- 3 sentences max: offer + price + closing question

**Substep 5 - OBJECTION HANDLING (NEPQ Diffusion):**
1. DIFFUSE: "That's not a problem..." (lower temperature)
2. ISOLATE: "[Objection] aside, do you feel like this is the right move?"
3. RESOLVE: "If we could figure out the [objection] piece, would you want to move forward?"
- ONE step per message. Do NOT stack.
- NEVER throw pain back at them
- After full diffusion with continued objection -> offer free workshop

**Substep 6 - CLOSE OR FALLBACK:**
- YES to paid -> Advance to COMMITMENT (collect email)
- Chose free workshop -> Advance to COMMITMENT (collect email for free link)
- HARD NO -> End gracefully, leave door open

**Hard Ceiling:** After 8 turns in OWNERSHIP, `ownership_ceiling` playbook fires (offer free workshop once, then close).

---

## 10. State Tracking & Counters

Session-level counters stored in DB and passed through each turn:

| Counter | Updated When | Reset When | Purpose |
|---------|-------------|------------|---------|
| `retry_count` | +1 on STAY/PROBE/BREAK_GLASS | Reset to 0 on ADVANCE | Triggers Break Glass when max exceeded |
| `consecutive_no_new_info` | +1 when no new info / reset to 0 on new info | Never auto-reset | Triggers ADVANCE or BREAK_GLASS at 2+ |
| `turns_in_current_phase` | +1 every turn | Reset to 0 on phase change | Enforces min turns, emotional depth gate |
| `deepest_emotional_depth` | Upgrades: surface -> moderate -> deep | Reset to "surface" on phase change | Gates CONSEQUENCE -> OWNERSHIP transition |
| `objection_diffusion_step` | Progresses 0-3 through diffusion protocol | Reset to 0 on phase change or agreement | Tracks diffusion progress |
| `ownership_substep` | Advances through 0-6 state machine | Reset to 0 on phase change | Controls OWNERSHIP close sequence |
| `turn_number` | +1 every turn | Never reset | Global conversation turn counter |
| `message_count` | +1 for each message (user and assistant) | Never reset | Total messages in session |

---

## 11. API Endpoints

**File:** `backend/app/main.py`

### Session Management

| Method | Endpoint | Request Body | Response | Description |
|--------|----------|-------------|----------|-------------|
| `POST` | `/api/sessions` | `{pre_conviction: 1-10}` | `{session_id, current_phase, pre_conviction, greeting}` | Create new session with greeting |
| `POST` | `/api/sessions/{id}/messages` | `{content: str}` | `{user_message, assistant_message, current_phase, previous_phase, phase_changed, session_ended}` | Send user message, get Sally's response |
| `GET` | `/api/sessions` | - | `[{id, status, phase, pre/post_conviction, cds, msg_count, times}]` | List all sessions |
| `GET` | `/api/sessions/{id}` | - | `{id, status, phase, conviction, times, messages[], profile, thought_logs[]}` | Full session detail with thought logs |
| `POST` | `/api/sessions/{id}/end` | - | `{status: "ok"}` | Mark session as abandoned |
| `GET` | `/api/sessions/{id}/thoughts` | - | `{session_id, phase, turn, retry, profile, thought_logs[]}` | Debug: view Sally's inner monologue |

### Scoring & Metrics

| Method | Endpoint | Request Body | Response | Description |
|--------|----------|-------------|----------|-------------|
| `POST` | `/api/sessions/{id}/post-conviction` | `{post_conviction: 1-10}` | `{session_id, pre_conviction, post_conviction, cds_score}` | Submit post-conviction score, calculate CDS |
| `POST` | `/api/sessions/{id}/quality-score` | - | `ConversationQualityScore` | Run/re-run quality scoring on completed session |
| `GET` | `/api/metrics` | - | `{total, active, completed, abandoned, avg_conviction, avg_cds, conversion_rate, phase_dist, failure_modes}` | Real-time dashboard stats |

### Payments & Config

| Method | Endpoint | Request Body | Response | Description |
|--------|----------|-------------|----------|-------------|
| `POST` | `/api/checkout` | `?session_id=optional` | `{checkout_url, session_id}` | Create Stripe Checkout Session ($10,000) |
| `GET` | `/api/checkout/verify/{id}` | - | `{payment_status, status, customer_email, amount, currency, metadata}` | Verify payment status |
| `GET` | `/api/config` | - | `{stripe_payment_link, stripe_publishable_key, tidycal_path}` | Return client-safe config |

### Export

| Method | Endpoint | Response | Description |
|--------|----------|----------|-------------|
| `GET` | `/api/export/csv` | CSV file download | All sessions + transcripts as CSV |

### Root

| Method | Endpoint | Response |
|--------|----------|----------|
| `GET` | `/` | `{"status":"ok","service":"Sally Sells API","version":"2.0.0","engine":"three-layer-nepq"}` |

---

## 12. Database Schema

**File:** `backend/app/database.py`

**Database:** PostgreSQL (Neon serverless) via SQLAlchemy ORM

### `sessions` Table

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `id` | String (PK) | - | 8-character uppercase UUID |
| `status` | String | "active" | active, completed, abandoned |
| `current_phase` | String | "CONNECTION" | Current NEPQ phase |
| `pre_conviction` | Integer | null | Pre-chat conviction score (1-10) |
| `post_conviction` | Integer | null | Post-chat conviction score (1-10) |
| `cds_score` | Integer | null | Conviction Delta Score (post - pre) |
| `start_time` | Float | - | Unix timestamp of session creation |
| `end_time` | Float | null | Unix timestamp of session end |
| `message_count` | Integer | 0 | Total messages in session |
| `retry_count` | Integer | 0 | Current retry count for Break Glass |
| `turn_number` | Integer | 0 | Current conversation turn |
| `consecutive_no_new_info` | Integer | 0 | Turns with no new info (repetition detection) |
| `turns_in_current_phase` | Integer | 0 | Turns in current phase |
| `deepest_emotional_depth` | String | "surface" | Emotional depth high watermark |
| `objection_diffusion_step` | Integer | 0 | Diffusion protocol progress (0-3) |
| `ownership_substep` | Integer | 0 | OWNERSHIP state machine step (0-6) |
| `prospect_profile` | Text (JSON) | "{}" | Accumulated prospect data |
| `thought_logs` | Text (JSON) | "[]" | Array of ThoughtLog objects |
| `escalation_sent` | String | null | Timestamp when Gmail escalation was sent |

### `messages` Table

| Column | Type | Description |
|--------|------|-------------|
| `id` | String (PK) | UUID |
| `session_id` | String (indexed) | FK to sessions.id |
| `role` | String | "user" or "assistant" |
| `content` | String | Message text |
| `timestamp` | Float | Unix timestamp |
| `phase` | String | NEPQ phase when message was sent |

### Schema Migration

`init_db()` handles schema creation and migration:
- `Base.metadata.create_all()` creates tables if they don't exist
- Migration check adds new columns (consecutive_no_new_info, turns_in_current_phase, deepest_emotional_depth, objection_diffusion_step, ownership_substep) if missing
- `SKIP_SCHEMA_CHECK=true` in production skips all of this for faster cold start (<500ms vs ~10s)

### Connection Pooling

- Lazy engine creation (`_get_engine()`)
- Pool size: 5, max overflow: 10
- `pool_pre_ping=True` for connection health checks

### `.env` Path Resolution

The `.env` file lives at **project root** (not `backend/`). `database.py` loads it once using:
```python
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"))
```
All other modules rely on this single load -- they do NOT call `load_dotenv()`.

---

## 13. Frontend

### Technology

React 19 + TypeScript + Vite + Tailwind CSS + React Router 7

### Pages & Routes

| Route | Component | Description |
|-------|-----------|-------------|
| `/` | `ChatPage` | Main conversation interface with Sally |
| `/dashboard` | `DashboardPage` | Real-time metrics dashboard (auto-refresh 10s) |
| `/history` | `HistoryPage` | Past session list with drill-down transcripts + CSV export |
| `/booking/:sessionId` | `BookingPage` | Stripe checkout + TidyCal booking |

### ChatPage (`frontend/src/pages/ChatPage.tsx`)

**State:**
- `sessionId`, `currentPhase`, `messages[]`, `isLoading`, `sessionEnded`
- `preConviction`, `showModal` (pre-conviction), `showPostModal` (post-conviction), `cdsResult`
- `seconds` (timer), `timerRef`, `messagesEndRef`, `sessionIdRef`, `sessionEndedRef`

**Features:**
- Pre-conviction modal (1-10 slider) before session starts
- Optimistic message rendering (user message shown immediately before API response)
- Phase indicator bar showing current NEPQ stage
- Session timer with warnings (25min amber, 28min+ red)
- "Sally is typing..." loading indicator
- Post-conviction modal after session ends -> CDS display
- "Book & Pay" button linking to BookingPage
- "New Session" button (ends current session first)
- Tab close/navigate detection: fires `endSessionBeacon()` via `pagehide`/`beforeunload`

### BookingPage (`frontend/src/pages/BookingPage.tsx`)

**Two-Step Flow:**
1. **Book:** TidyCal calendar link + embed for scheduling
2. **Pay:** Stripe Checkout button ($10,000)

**URL Parameters:**
- `?payment=success&checkout_session_id=xxx` -> Verify payment, show confirmation view
- `?payment=cancelled` -> Show retry banner

**Payment Success View:** Payment details (amount, receipt email, status), next steps (email -> prep call -> workshop day), TidyCal link for scheduling

### DashboardPage

Real-time metrics with 10-second auto-refresh:
- Total sessions, active/completed/abandoned counts
- Average pre-conviction score, average CDS
- Conversion rate
- Phase distribution (bar chart style)
- Drop-off analysis (abandoned sessions per phase)

### HistoryPage

- Session list table (ID, status, phase, pre-score, CDS, messages, duration, date)
- Click-through to full transcript view
- CSV export download link

### Key Components

| Component | File | Description |
|-----------|------|-------------|
| `MessageBubble` | `components/chat/MessageBubble.tsx` | Renders messages. Parses URLs: Stripe checkout -> green payment button, TidyCal -> blue booking button, others -> regular links |
| `ChatInput` | `components/chat/ChatInput.tsx` | Message input. Separate `disabled` (loading) and `sessionEnded` props |
| `PhaseIndicator` | `components/chat/PhaseIndicator.tsx` | Horizontal bar showing all 7 NEPQ phases with current highlighted |
| `ConvictionModal` | `components/chat/ConvictionModal.tsx` | Pre-session slider (1-10) |
| `PostConvictionModal` | `components/chat/PostConvictionModal.tsx` | Post-session slider (1-10) + CDS calculation |
| `Header` | `components/layout/Header.tsx` | Navigation bar (Chat, Dashboard, History) with "NEPQ ENGINE V1" label |
| `Badge/Button/Card/Input` | `components/ui/` | Tailwind-based component library |

### API Client (`frontend/src/lib/api.ts`)

- `API_BASE`: `VITE_API_URL` env var (defaults to `http://localhost:8000`) + `/api`
- All functions are `async` and throw on non-OK responses
- `endSessionBeacon()`: Uses `navigator.sendBeacon()` for tab close reliability
- Full TypeScript type definitions for all request/response shapes

### Phase Constants (`frontend/src/constants/index.ts`)

7 phases with labels, short labels, and colors:
- CONNECTION (#3b82f6/blue), SITUATION (#8b5cf6/purple), PROBLEM (#f59e0b/amber)
- SOLUTION (#10b981/green), CONSEQUENCE (#ef4444/red), OWNERSHIP (#ec4899/pink)
- COMMITMENT (#06b6d4/cyan)

---

## 14. Integrations

### 14.1 Stripe Payments

**Purpose:** Process $10,000 payments for the AI Discovery Workshop.

**Flow:**
1. Sally's response layer generates `[PAYMENT_LINK]` placeholder in COMMITMENT closing messages
2. `main.py` intercepts the placeholder and creates a real Stripe Checkout Session
3. Product: "100x AI Discovery Workshop" ($10,000 / 1,000,000 cents)
4. Metadata: sally_session_id, prospect_name, prospect_company, prospect_role
5. Customer email pre-filled from prospect profile
6. Success URL: `/booking/{sessionId}?payment=success&checkout_session_id={CHECKOUT_SESSION_ID}`
7. Cancel URL: `/booking/{sessionId}?payment=cancelled`
8. Placeholder is replaced with actual Stripe checkout URL in response text
9. Frontend `MessageBubble` renders Stripe URLs as styled green payment buttons
10. After payment, frontend calls `GET /api/checkout/verify/{checkoutSessionId}`
11. Backend logs conversion to Google Sheets

**Lazy Initialization:** `_get_or_create_stripe_price()` searches for existing product by name ("100x AI Discovery Workshop"), creates product + price on first use, caches in `_stripe_price_id` global.

**Fallback:** If Stripe checkout creation fails, falls back to static `STRIPE_PAYMENT_LINK` from `.env`.

**Post-objection handling:** If the payment link was already sent and prospect objected, Layer 3 receives instructions to NOT re-send the Stripe link. Instead, reference existing link or offer free workshop.

### 14.2 Google Sheets Logging

**File:** `backend/app/sheets_logger.py`

**Mechanism:** Apps Script webhook endpoint (`GOOGLE_SHEETS_WEBHOOK_URL`). Fire-and-forget via Python daemon threads.

**Custom redirect handler:** `_PostRedirectHandler` preserves POST method + body through 301/302/303/307/308 redirects (stdlib default converts to GET).

**Three Log Types:**

| Target | Trigger | Columns |
|--------|---------|---------|
| `session` | Session completes or is abandoned | 25 columns: session ID, status, phase, conviction scores, CDS, message count, turn count, timestamps, duration, profile (name/role/company/industry/pain_points/desired_state/cost_of_inaction/objections/email/phone), escalation sent, payment status, full transcript, log timestamp |
| `hot_lead` | Prospect reaches OWNERSHIP phase | 11 columns: session ID, phase, pre-conviction, turn, prospect name/role/company, pain points, cost of inaction, transcript, timestamp |
| `conversion` | Payment confirmed via Stripe | 10 columns: sally_session_id, checkout_session_id, payment status, amount, currency, email, prospect name/company/role, timestamp |

**Safety:** Transcripts are truncated at 49,000 characters (Google Sheets cell limit is 50,000).

### 14.3 Gmail Escalation

**Trigger:** First time a session enters OWNERSHIP phase (`escalation_sent` is null).

**Email Contents:**
- Subject: `Sally Sells Escalation -- {Prospect Name} ({Company})`
- Body: QUALIFIED LEAD header, prospect details (name, role, company), pain points, objections, full conversation transcript
- Sent via Gmail SMTP SSL (port 465) using App Password authentication

**Requirements:** `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `ESCALATION_EMAIL` in `.env`.

### 14.4 TidyCal Booking

**Purpose:** Allow prospects who chose the free workshop to book a session.

- `TIDYCAL_PATH` env var contains the booking path (e.g., `m4gek07/free-ai-discovery-workshop`)
- Sally's response includes full URL: `https://tidycal.com/{TIDYCAL_PATH}`
- BookingPage embeds TidyCal calendar via `data-path` attribute + script embed
- `GET /api/config` endpoint exposes `tidycal_path` to frontend
- MessageBubble renders TidyCal URLs as styled blue booking buttons

---

## 15. Quality Scoring System

**File:** `backend/app/quality_scorer.py`

**Purpose:** Post-conversation evaluation of Sally's performance. Runs asynchronously after session completion (not in the hot path).

**Model:** Claude Sonnet 4 (`claude-sonnet-4-20250514`)

**When It Runs:**
1. Automatically on session completion via daemon thread in `send_message()`
2. On-demand via `POST /api/sessions/{id}/quality-score`

**Input:** Full transcript + Sally's internal thought logs (per-turn analyst extractions including flagged phrases to mirror, emotional cues, energy levels)

**Dimensions (0-100):**

| Dimension | Weight | What It Measures |
|-----------|--------|------------------|
| **Mirroring** | 30% | Did Sally use the prospect's exact flagged phrases? |
| **Energy Matching** | 20% | Did Sally's tone match the analyst-detected energy? |
| **Structure** | 25% | Did Mirror -> Validate -> Question pattern hold? |
| **Emotional Arc** | 25% | Was the emotional progression coherent across phases? |

**Overall Score** = Weighted average of all four dimensions

**Storage:** Quality score is appended to the session's `thought_logs` JSON as `{"quality_score": {...}}`. Previous scores are removed on re-run.

---

## 16. Environment Variables

### Backend (Render / `.env`)

| Variable | Required | Used In | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | database.py | PostgreSQL connection string (Neon) |
| `GEMINI_API_KEY` | Yes | comprehension.py | Google Gemini API key for Layer 1 |
| `ANTHROPIC_API_KEY` | Yes | response.py, quality_scorer.py | Claude API key for Layer 3 + quality scoring |
| `STRIPE_SECRET_KEY` | Yes | main.py | Stripe secret key (test mode) |
| `STRIPE_PUBLISHABLE_KEY` | Yes | main.py (/api/config) | Stripe publishable key (exposed to frontend) |
| `STRIPE_PAYMENT_LINK` | Yes | main.py | Fallback Stripe payment link |
| `TIDYCAL_PATH` | Yes | response.py, main.py | TidyCal booking path |
| `GOOGLE_SHEETS_WEBHOOK_URL` | Optional | main.py, sheets_logger.py | Apps Script webhook URL for logging |
| `GMAIL_USER` | Optional | main.py | Gmail address for escalation emails |
| `GMAIL_APP_PASSWORD` | Optional | main.py | Gmail App Password (not regular password) |
| `ESCALATION_EMAIL` | Optional | main.py | Recipient for hot lead escalation emails |
| `FRONTEND_URL` | Optional | main.py | Frontend URL for Stripe redirects (defaults to `http://localhost:5173`) |
| `SKIP_SCHEMA_CHECK` | Optional | database.py | Skip schema creation on startup (production optimization) |

### Frontend (Vercel)

| Variable | Required | Description |
|----------|----------|-------------|
| `VITE_API_URL` | Yes | Backend base URL (e.g., `https://sally-sells-experiment.onrender.com`) |

### `.env` Path Resolution

The `.env` file must live at the **project root** (not `backend/`). Only `database.py` loads it, using:
```python
os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
```
This resolves from `backend/app/database.py` up 3 levels to project root. All other modules rely on this single load.

---

## 17. Deployment

### Backend (Render)

| Setting | Value |
|---------|-------|
| **Repository:** | `github.com/devseth34/sally-sells-experiment` |
| **Branch:** | `main` |
| **Root Directory:** | `backend` |
| **Runtime:** | Python 3 |
| **Build Command:** | `pip install -r requirements.txt` |
| **Start Command:** | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| **Auto-Deploy:** | On commit to `main` |

**Note:** Free tier spins down after inactivity. First request after idle may take ~50 seconds. Set `SKIP_SCHEMA_CHECK=true` to reduce cold start.

### Frontend (Vercel)

| Setting | Value |
|---------|-------|
| **Root Directory:** | `frontend` |
| **Framework:** | Vite |
| **Build Command:** | `tsc -b && vite build` |
| **Auto-Deploy:** | On commit to `main` |

---

## 18. Directory Structure

```
sally-sells-experiment/
├── .env                                   # Runtime secrets (gitignored, PROJECT ROOT)
├── .gitignore
├── experiment_manifest.txt
├── TECHNICAL_DOCUMENTATION.md             # This file
│
├── backend/
│   ├── requirements.txt                   # Python dependencies (11 packages)
│   ├── start.sh                           # Render start command
│   ├── fact_sheet.txt                     # 100x product fact sheet (RAG ground truth)
│   ├── test_brain.py                      # Testing utilities
│   │
│   └── app/
│       ├── __init__.py
│       ├── main.py                        # FastAPI app, all routes, integrations (~930 lines)
│       ├── agent.py                       # SallyEngine orchestrator (~378 lines)
│       ├── database.py                    # SQLAlchemy models + DB init + .env loading
│       ├── schemas.py                     # Pydantic API schemas (NepqPhase, requests, responses)
│       ├── models.py                      # Internal data models (Profile, Comprehension, Decision, ThoughtLog, Quality)
│       ├── phase_definitions.py           # NEPQ phase specs, exit criteria checklists, thresholds
│       ├── playbooks.py                   # 9 situation playbooks with template injection
│       ├── quality_scorer.py              # Post-conversation quality evaluation (Claude Sonnet)
│       ├── sheets_logger.py               # Google Sheets fire-and-forget webhook logger
│       │
│       └── layers/
│           ├── __init__.py
│           ├── comprehension.py           # Layer 1: Analyze (Gemini 2.0 Flash)
│           ├── decision.py                # Layer 2: Decide (deterministic, 10-step priority)
│           └── response.py                # Layer 3: Respond (Claude Sonnet + circuit breaker)
│
└── frontend/
    ├── package.json                       # Node dependencies
    ├── vite.config.ts                     # Vite build config
    ├── tsconfig.json                      # TypeScript config
    ├── tailwind.config.cjs                # Tailwind CSS config
    ├── postcss.config.cjs                 # PostCSS config
    ├── index.html                         # HTML entry point
    │
    └── src/
        ├── main.tsx                       # React entry point
        ├── App.tsx                        # Router (4 routes)
        ├── index.css                      # Tailwind imports
        │
        ├── lib/
        │   ├── api.ts                     # API client + TypeScript types + sendBeacon
        │   └── utils.ts                   # Utility functions (formatTime, formatDate, etc.)
        │
        ├── pages/
        │   ├── ChatPage.tsx               # Main conversation UI (optimistic rendering, timer, modals)
        │   ├── BookingPage.tsx            # Stripe + TidyCal checkout (payment verification)
        │   ├── DashboardPage.tsx          # Real-time metrics (10s auto-refresh)
        │   └── HistoryPage.tsx            # Session history (table + transcript drill-down + CSV)
        │
        ├── components/
        │   ├── chat/
        │   │   ├── ChatInput.tsx          # Message input (disabled vs sessionEnded)
        │   │   ├── MessageBubble.tsx      # Message display (Stripe/TidyCal URL -> styled buttons)
        │   │   ├── PhaseIndicator.tsx     # NEPQ phase bar
        │   │   ├── ConvictionModal.tsx    # Pre-conviction slider (1-10)
        │   │   └── PostConvictionModal.tsx # Post-conviction slider + CDS display
        │   ├── layout/
        │   │   └── Header.tsx             # Navigation header
        │   └── ui/
        │       ├── Badge.tsx
        │       ├── Button.tsx
        │       ├── Card.tsx
        │       ├── Input.tsx
        │       └── index.ts               # UI exports
        │
        └── constants/
            └── index.ts                   # Phase labels, colors, helpers
```

---

## 19. Data Flow: Complete Request Lifecycle

### Session Creation

```
1. User opens app -> Pre-conviction modal (1-10)
2. User submits score ->
   POST /api/sessions { pre_conviction: N }
3. Backend:
   a. Generate session ID (8-char uppercase UUID)
   b. Create DBSession with status="active", phase=CONNECTION
   c. Generate greeting: "Hey there! I'm Sally from 100x..."
   d. Save greeting as DBMessage
   <- { session_id, current_phase, pre_conviction, greeting }
```

### Message Processing (Core Loop)

```
4. User types message ->
   POST /api/sessions/{id}/messages { content: "..." }

5. Backend processes:
   a. Save user message to DB, increment message_count and turn_number
   b. Load full conversation history from DB
   c. SallyEngine.process_turn():
      i.   Layer 1: run_comprehension() [Gemini Flash]
           -> ComprehensionOutput { intent, objection, profile_updates,
              exit_eval checklist, richness, depth, exact_words, energy... }
      ii.  Update prospect profile with Layer 1 extractions
      iii. Track state: objections, depth, no_new_info, diffusion, substep
      iv.  Layer 2: make_decision() [deterministic logic]
           -> DecisionOutput { action: ADVANCE|STAY|PROBE|REROUTE|BREAK_GLASS|END,
              target_phase, reason, probe_target, objection_context }
      v.   Detect situation playbooks (overlay on decision)
      vi.  Build emotional_context from Layer 1 for Layer 3
      vii. Layer 3: generate_response() [Claude Sonnet]
           -> response_text (post-processed by circuit breaker)
   d. Update DB: phase, profile, thought_logs, all state counters
   e. If session ended:
      - Set status=completed, end_time
      - Log session to Google Sheets (daemon thread)
      - Launch quality scoring (daemon thread)
   f. If entering OWNERSHIP (first time):
      - Send Gmail escalation email
      - Log hot_lead to Google Sheets
   g. If [PAYMENT_LINK] in response:
      - Create Stripe Checkout Session
      - Replace placeholder with real URL
   h. Save assistant message to DB
   <- SendMessageResponse { user_message, assistant_message, phase,
      previous_phase, phase_changed, session_ended }

6. Frontend:
   - Replace optimistic user message with real one
   - Add assistant message
   - Update phase indicator
   - If session_ended: show post-conviction modal
```

### Session End

```
7. Post-conviction modal (1-10)
8. User submits ->
   POST /api/sessions/{id}/post-conviction { post_conviction: N }
   <- { cds_score: post - pre }
9. Optional: "Book & Pay" -> /booking/{sessionId}
10. Tab close: endSessionBeacon() -> POST /api/sessions/{id}/end
```

### Thought Log Structure (Per Turn)

```json
{
  "turn_number": 3,
  "user_message": "i run a small marketing agency",
  "comprehension": {
    "user_intent": "DIRECT_ANSWER",
    "emotional_tone": "warm",
    "emotional_intensity": "medium",
    "objection_type": "NONE",
    "response_richness": "moderate",
    "emotional_depth": "surface",
    "new_information": true,
    "energy_level": "warm",
    "prospect_exact_words": ["small marketing agency", "run"],
    "emotional_cues": ["pride in ownership"],
    "profile_updates": {
      "role": "Owner",
      "company": "Marketing agency",
      "industry": "Marketing"
    },
    "exit_evaluation": {
      "criteria": {
        "role_shared": {"met": true, "evidence": "said they run a marketing agency"},
        "company_or_industry_shared": {"met": true, "evidence": "marketing agency = industry"},
        "ai_interest_stated": {"met": false, "evidence": null}
      },
      "reasoning": "Role and industry met, still need AI interest",
      "missing_info": ["Why they're interested in AI"]
    }
  },
  "decision": {
    "action": "STAY",
    "target_phase": "CONNECTION",
    "reason": "Exit criteria not fully met: 2/3",
    "retry_count": 1
  },
  "response_phase": "CONNECTION",
  "response_text": "What got you curious about AI for the agency?",
  "profile_snapshot": {
    "name": null,
    "role": "Owner",
    "company": "Marketing agency",
    "industry": "Marketing"
  }
}
```

---

*Generated: February 2026*
*Engine Version: NEPQ Engine V2 (Three-Layer Architecture with Checklist-Based Exit Criteria)*
