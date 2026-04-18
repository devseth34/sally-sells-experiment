# Sally Sells — Complete Codebase Documentation

## Project Overview

> **Status: Phase 1B APPROVED (April 2026).** All Phase 1B benchmarks were met and the NEPQ brain — Layer 1 (`app/layers/comprehension.py`), Layer 2 (`app/layers/decision.py`), Layer 3 (`app/layers/response.py`), `app/phase_definitions.py`, and `app/persona_config.py` — is **frozen** as of this commit. Phase 2 (voice agent) builds on top of the frozen brain; only additive optional fields are permitted per `PHASE_2_PLAN_ADDENDUM.md` §C1. Do not modify frozen-brain semantics without written sign-off.

**Sally Sells** is an AI-powered NEPQ (Neuro-Emotional Persuasion Questioning) sales agent that sells 100x's $10,000 AI Discovery Workshop for mortgage professionals. The system guides prospects through a structured 7-phase conversation designed to measure "Conviction Delta Score" (CDS) — the change in conviction from pre to post-conversation.

**Key Innovation: Multi-Bot Phase 1B A/B Experiment**
The system supports 8 different bot arms for testing:
- **Sally (NEPQ)**: Full three-layer structured sales engine (original agent)
- **Hank (Hypes)**: Aggressive traditional sales bot using urgency and ROI framing
- **Ivy (Informs)**: Neutral information-only bot presenting balanced facts
- **6 Hybrid Arms**: Sally + Hank Close, Sally + Ivy Bridge, Sally Empathy+, Sally Direct, Hank Structured

**Product**: CEO Nik Shah comes onsite for a full-day Discovery Workshop identifying $5M+ in annual savings through AI transformation.
**Target**: C-suite executives at 50+ person companies in real estate, financial services, and professional services.
**Alternative**: Free online AI Discovery Workshop (via TidyCal) offered if they decline paid option.

---

## Architecture Overview

```
User Message (Web or SMS)
     │
┌─────────────────────────┐
│      BOT ROUTER         │  (bot_router.py)
│  Dispatches by arm      │
└─────────────────────────┘
     │           │           │
   Sally      Hank/Ivy    Hybrid Arms
   (3-layer)  (Single API) (3-layer + persona override)
     │
┌──────────────────────────────────────────────────┐
│  SALLY ENGINE (Three-Layer Pipeline)             │
├──────────────────────────────────────────────────┤
│  Layer 1: Comprehension (Gemini Flash)           │
│  - Analyzes user message                         │
│  - Extracts intent, objections, profile updates  │
│  - Evaluates exit criteria for current phase     │
├──────────────────────────────────────────────────┤
│  Layer 2: Decision (Pure Python)                 │
│  - No LLM calls — deterministic logic            │
│  - Decides: ADVANCE, STAY, PROBE, REROUTE, etc.  │
│  - Applies phase gating and safety mechanisms    │
│  - Detects situation playbooks                   │
├──────────────────────────────────────────────────┤
│  Layer 3: Response (Claude Sonnet)               │
│  - Generates Sally's reply                       │
│  - Applies persona overrides for hybrid arms     │
│  - Injects conversation context & profile        │
│  - Circuit breaker validates response            │
└──────────────────────────────────────────────────┘
     │
┌─────────────────────────┐
│  Invitation/Session End │
│  SMS Follow-up Worker   │
│  Memory Extraction      │
│  Quality Scoring        │
└─────────────────────────┘
```

**Design Decision**: Layer 2 is pure deterministic Python with zero LLM calls, making conversation flow completely predictable, debuggable, and auditable. This is the critical differentiator.

---

## Directory Structure

```
sally-sells-experiment/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI app, all endpoints
│   │   ├── agent.py                   # SallyEngine (3-layer orchestrator)
│   │   ├── bot_router.py              # Routes to correct bot based on arm
│   │   ├── schemas.py                 # Pydantic models (BotArm, NepqPhase, etc.)
│   │   ├── models.py                  # ProspectProfile, ComprehensionOutput, DecisionOutput
│   │   ├── database.py                # SQLAlchemy ORM (DBSession, DBMessage, DBUser, DBMemoryFact)
│   │   ├── auth.py                    # User registration, login, JWT tokens
│   │   ├── layers/
│   │   │   ├── comprehension.py       # Layer 1: Gemini-powered message analysis
│   │   │   ├── decision.py            # Layer 2: Pure logic phase transitions & decisions
│   │   │   └── response.py            # Layer 3: Claude Sonnet response generation
│   │   ├── bots/
│   │   │   ├── base.py                # ControlBot base class (Hank/Ivy foundation)
│   │   │   ├── hank.py                # Hank Hypes (aggressive sales bot)
│   │   │   └── ivy.py                 # Ivy Informs (neutral information bot)
│   │   ├── phase_definitions.py       # NEPQ phase specs: exit criteria, min_turns, max_retries
│   │   ├── persona_config.py          # Persona overrides for hybrid arms
│   │   ├── playbooks.py               # Situation playbooks (confusion_recovery, bridge, etc.)
│   │   ├── memory.py                  # Memory extraction & retrieval for returning visitors
│   │   ├── sms.py                     # Twilio SMS webhook & conversation routing
│   │   ├── followup.py                # Background SMS follow-up worker
│   │   ├── invitation.py              # Builds tracked invitation URLs with UTM params
│   │   ├── legitimacy_scorer.py       # Session Legitimacy Score (0–100)
│   │   ├── quality_scorer.py          # Post-conversation quality evaluation
│   │   ├── report_generator.py        # PDF report generation with insights
│   │   ├── sheets_logger.py           # Google Sheets webhook integration
│   │   └── __init__.py
│   ├── tests/
│   │   ├── smoke_test.py              # Full conversation end-to-end test
│   │   ├── test_bot_switch.py         # Multi-arm routing tests
│   │   ├── test_control_bots.py       # Hank/Ivy specific tests
│   │   ├── test_hybrid_arms.py        # Hybrid arm persona tests
│   │   ├── test_hybrid_integration.sh # Full integration test script
│   │   ├── test_auth.py               # Auth flow tests
│   │   ├── test_sms_integration.py    # SMS webhook & state machine tests
│   │   ├── test_memory_phase_*.py     # Memory extraction tests
│   │   ├── test_report_generator.py   # Report generation tests
│   │   └── test_relationship_memory.py # Returning visitor memory tests
│   ├── fact_sheet.txt                 # Optional fact sheet for bots
│   ├── requirements.txt               # Python dependencies
│   └── test_brain.py
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── ChatPage.tsx           # Main chat UI (bot selection, conversation)
│   │   │   ├── ExperimentPage.tsx     # Blinded experiment UI (random assignment)
│   │   │   ├── DashboardPage.tsx      # Admin analytics dashboard
│   │   │   ├── HistoryPage.tsx        # Session history & transcripts
│   │   │   ├── AdminPage.tsx          # Admin controls (cleanup, allocation reset)
│   │   │   └── BookingPage.tsx        # TidyCal booking page integration
│   │   ├── components/
│   │   │   ├── chat/
│   │   │   │   ├── ChatInput.tsx          # Message input box
│   │   │   │   ├── MessageBubble.tsx      # Message display (user/assistant)
│   │   │   │   ├── ConvictionModal.tsx    # Pre-conviction (1–10) modal
│   │   │   │   ├── PostConvictionModal.tsx # Post-conviction modal
│   │   │   │   ├── PhaseIndicator.tsx     # Current NEPQ phase display
│   │   │   │   ├── BotSwitcher.tsx        # Bot selection UI
│   │   │   │   ├── AuthModal.tsx          # Login/register modal
│   │   │   │   └── ExperimentSurveyModal.tsx # Experiment pre-survey
│   │   │   ├── layout/
│   │   │   │   └── Header.tsx             # Navigation header
│   │   │   └── ui/
│   │   │       ├── Button.tsx
│   │   │       ├── Input.tsx
│   │   │       ├── Card.tsx
│   │   │       └── Badge.tsx
│   │   ├── lib/
│   │   │   ├── api.ts                 # API client & session management
│   │   │   └── utils.ts               # Format functions
│   │   ├── App.tsx                    # Router & route definitions
│   │   ├── main.tsx                   # React entry point
│   │   └── constants/index.ts
│   ├── package.json                   # Frontend dependencies (React, Vite, Tailwind)
│   ├── vercel.json                    # Vercel deployment config + SPA rewrites
│   └── tsconfig.json
├── .env                               # Secrets (API keys, DB URL)
├── .gitignore
├── TECHNICAL_GUIDE.md                 # Full technical documentation
├── CHANGELOG_4_WEEKS.md               # 4-week changelog
├── RECENT_UPDATES.md                  # Recent updates log
├── CODEBASE.md                        # This file
└── test_conversations.sh              # Bash script for manual testing
```

---

## Backend API Endpoints

### Session Management

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/sessions` | Create new session (choose bot or random) |
| GET | `/api/visitors/{visitor_id}/active-session` | Resume existing session by visitor |
| POST | `/api/sessions/{session_id}/messages` | Send message, get response |
| GET | `/api/sessions/{session_id}` | Get session details |
| GET | `/api/sessions` | List all sessions (paginated) |
| POST | `/api/sessions/{session_id}/end` | Explicitly end session |
| POST | `/api/sessions/{session_id}/post-conviction` | Record post-chat conviction score |
| POST | `/api/sessions/{session_id}/switch` | Switch bot mid-conversation |

### Authentication

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/auth/register` | Create new user account |
| POST | `/api/auth/login` | Authenticate & get JWT token |
| GET | `/api/auth/me` | Get authenticated user info |
| POST | `/api/auth/identify` | Non-auth identification by name+phone |

### Memory & Visitor

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/visitors/{visitor_id}/memory` | Load persistent visitor memory |
| DELETE | `/api/visitors/{visitor_id}/memory` | Clear visitor memory |

### Analytics & Admin

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/metrics` | Summary metrics (sessions, CDS, etc.) |
| GET | `/api/analytics/trends` | Time-series analytics |
| GET | `/api/monitoring/cds-summary` | CDS breakdown by arm |
| GET | `/api/admin/analytics` | Full admin analytics dashboard |
| POST | `/api/admin/reset-allocation` | Reset allocation counter for rebalancing |
| POST | `/api/admin/cleanup-stale-sessions` | End sessions older than 24h |

### Exports & Reports

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/export/csv` | Export all sessions as CSV |
| GET | `/api/export/pdf` | Generate PDF research report |
| GET | `/api/sessions/{session_id}/thoughts` | Get thought logs for session |
| POST | `/api/sessions/{session_id}/quality-score` | Compute quality metrics |

### SMS & Twilio

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/sms/webhook` | Twilio inbound SMS webhook |
| POST | `/api/debug/trigger-followups` | Manually trigger follow-up cycle |

### Other

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/` | Health check |
| GET | `/api/config` | Client config (API URL, etc.) |
| POST | `/api/checkout` | Stripe checkout session |
| GET | `/api/checkout/verify/{session_id}` | Verify Stripe payment |

---

## Core Backend Components

### SallyEngine (agent.py)

Orchestrates the three-layer pipeline for a single conversation turn.

**Key Method**: `SallyEngine.process_turn()`
- **Input**: `current_phase`, `user_message`, `conversation_history`, `profile_json`, etc.
- **Output**: `{response_text, new_phase, new_profile_json, thought_log_json, phase_changed, session_ended, ...}`

**State Tracking**:
- `retry_count` — incremented on PROBE, reset on ADVANCE
- `consecutive_no_new_info` — track repetition
- `turns_in_current_phase` — for phase-specific minimum turns
- `deepest_emotional_depth` — tracks maximum engagement (surface → moderate → deep)
- `objection_diffusion_step` — NEPQ objection handling progression
- `ownership_substep` — fine-grained substates within OWNERSHIP phase

**Fast Path**: Trivial messages (hi, yes, no, ok, bye) skip Layer 1 (Gemini) entirely for latency.

---

### Layer 1: Comprehension (layers/comprehension.py)

Uses Gemini Flash to analyze each user message.

**Output: ComprehensionOutput**

| Field | Description |
|-------|-------------|
| `user_intent` | DIRECT_ANSWER, DEFLECTION, QUESTION, OBJECTION, SMALL_TALK, AGREEMENT, PUSHBACK, CONFUSION |
| `emotional_tone` | Sentiment analysis |
| `emotional_intensity` | Intensity of detected emotion |
| `objection_type` | PRICE, TIMING, AUTHORITY, NEED, NONE |
| `objection_detail` | Specific text of the objection |
| `profile_updates` | Extracted fields (name, role, company, pain_points, etc.) |
| `exit_evaluation` | PhaseExitEvaluation with per-criterion boolean + evidence |
| `prospect_exact_words` | 2–3 phrases worth mirroring |
| `emotional_cues` | Specific emotional signals with context |
| `energy_level` | low/flat, neutral, warm, high/excited |
| `response_richness` | thin, moderate, rich |
| `emotional_depth` | surface, moderate, deep |
| `new_information` | Boolean — did they say something new? |
| `objection_diffusion_status` | not_applicable, diffused, isolated, resolved, repeated |

**Critical Rules**:
- Only extract what was EXPLICITLY stated, never infer
- Exit criteria are cumulative across entire conversation
- Existing profile fields are checked (if name already filled, criterion is MET)
- Memory facts are considered already-known for criteria evaluation

---

### Layer 2: Decision (layers/decision.py)

Pure deterministic Python — no LLM calls.

**Output: DecisionOutput**

| Field | Description |
|-------|-------------|
| `action` | ADVANCE, STAY, PROBE, REROUTE, BREAK_GLASS, END |
| `target_phase` | Phase Sally should be in for her response |
| `reason` | Human-readable explanation |
| `objection_context` | Optional "PLAYBOOK:name" or "DIFFUSE:type" marker |
| `retry_count` | Incremented on PROBE |
| `probe_target` | Which unmet criterion to target |

**Decision Logic (Priority Order)**:
1. Session end conditions (time limit 30 min, already terminated)
2. Objection routing (rerouting or diffusion)
3. Confusion recovery (fire confusion_recovery playbook)
4. Gap Builder (check required profile fields)
5. Minimum turns enforcement per phase (except returning visitors in early phases)
6. Exit criteria evaluation — ADVANCE if all met (unless emotional depth gate blocks)
7. Emotional depth gate (CONSEQUENCE→OWNERSHIP): Deep always ok, Moderate needs 3+ turns, Surface needs 4+ turns
8. Probing: thin/flat responses trigger PROBE + retry_count++
9. Repetition detection: 2+ turns with no new info → force-advance or BREAK_GLASS
10. Retry ceiling: max retries exceeded → BREAK_GLASS or force-advance
11. Default: STAY in current phase

**Ownership Substeps** (fine-grained sub-phases):
- `0` — Initial
- `1` — First OWNERSHIP turn
- `2` — Commitment question asked, prospect gave positive response
- `3` — Self-persuasion failed, bridge attempted
- `4` — Self-persuasion succeeded (or bridge completed)
- `5` — Opportunity presented, objection encountered
- `6` — Ready to close or advance to COMMITMENT

**Criteria Latch**: Once an exit criterion is MET, it stays MET. Prevents Layer 1 from flip-flopping.

---

### Layer 3: Response (layers/response.py)

Claude Sonnet generates Sally's reply (or returns persona override for hybrid arms).

**Constraints**:
- Max 2–4 sentences (phase-dependent, from phase_definitions)
- ONE question per response, no stacking
- No hype language (guaranteed, revolutionary, game-changing)
- No pitching before CONSEQUENCE phase
- No advice before OWNERSHIP phase
- Stop selling when they say yes
- Circuit breaker validates output before returning to frontend

**Input Context**:
- `decision` — Layer 2 output
- `emotional_context` — exact phrases to mirror, emotional cues, energy level, missing criteria guidance
- `profile` — ProspectProfile with accumulated facts
- `conversation_history` — last 10 messages for context
- `memory_context` — formatted long-term memory facts
- `probe_mode` — if true, focus on specific criterion guidance
- `persona_override` — optional persona string from hybrid arm config

**Playbook Injection**: If Layer 2 detects a situation, Layer 3 receives playbook instructions overlaid on default behavior.

---

### Bot Router (bot_router.py)

**Route Logic**:
- `SALLY_ENGINE_ARMS` → `SallyEngine.process_turn()` (3-layer pipeline)
- `hank_hypes` → `HankBot.respond()` (single Claude API call)
- `ivy_informs` → `IvyBot.respond()` (single Claude API call)

**SALLY_ENGINE_ARMS**:
```python
{"sally_nepq", "sally_hank_close", "sally_ivy_bridge",
 "sally_empathy_plus", "sally_direct", "hank_structured"}
```

**ControlBot (base.py)**:
- Single Claude Sonnet call per message
- Turn tracking (turn_number, pacing guidance)
- Memory context injection
- Profile hint extraction (basic role/company/interest detection)
- Conversation history capping (max 20 messages)
- Link injection (replaces `[INVITATION_LINK]` placeholder)
- Session end detection (explicit "bye", history length > 100)
- Response shape matches SallyEngine output for uniform handling in main.py

---

## NEPQ Phase System

**7 Phases** (strict sequence):

| # | Phase | Min Turns | Description |
|---|-------|-----------|-------------|
| 1 | **CONNECTION** | 1–3 | Build rapport, get role/company/interest |
| 2 | **SITUATION** | 2–3 | Map current operations, workflow, team |
| 3 | **PROBLEM_AWARENESS** | 3+ | Surface real pain points (prospect's words) |
| 4 | **SOLUTION_AWARENESS** | 2–3 | Paint ideal future, create gap |
| 5 | **CONSEQUENCE** | 3+ | Quantify cost of inaction, build urgency |
| 6 | **OWNERSHIP** | 2–8 | Present 100x AI Academy, handle objections, self-persuasion |
| 7 | **COMMITMENT** | 1+ | Close, share invitation link, or graceful exit |

**Exit Criteria by Phase**:

| Phase | Criteria |
|-------|----------|
| CONNECTION | role_shared, company_or_industry_shared, ai_interest_stated |
| SITUATION | workflow_described, concrete_detail_shared |
| PROBLEM_AWARENESS | specific_pain_articulated, pain_is_current |
| SOLUTION_AWARENESS | desired_state_described, gap_is_clear |
| CONSEQUENCE | cost_acknowledged, urgency_felt |
| OWNERSHIP | commitment_question_asked, prospect_self_persuaded, opportunity_presented, definitive_response |
| COMMITMENT | positive_signal_or_hard_no, link_sent |

**Phase-Specific Limits**:
- `min_turns` — must stay for this many turns (prevents rushing)
- `max_retries` — max PROBE actions before break glass (2–3 per phase)
- `confidence_threshold` — reserved for future use
- `response_length` — max sentences and tokens

---

## Bot Arms (8 Total)

### Control Arms (Single Claude Call)

| Arm | Name | Style |
|-----|------|-------|
| `hank_hypes` | Hank | Aggressive, urgency-driven, ROI-focused. No phases. |
| `ivy_informs` | Ivy | Neutral, balanced, information-only. No phases. |

### Sally Engine Arms (3-Layer + Optional Persona Override)

| Arm | Name | Description |
|-----|------|-------------|
| `sally_nepq` | Sally | Original full NEPQ pipeline, default persona throughout |
| `sally_hank_close` | Sally/Hank | Sally for CONNECTION→CONSEQUENCE, Hank persona for OWNERSHIP→COMMITMENT |
| `sally_ivy_bridge` | Sally/Ivy | Sally for CONNECTION/SITUATION and CONSEQUENCE→COMMITMENT, Ivy-neutral for PROBLEM_AWARENESS/SOLUTION_AWARENESS |
| `sally_empathy_plus` | Sally+ | Sally with amplified emotional validation and warmth at every phase |
| `sally_direct` | Sally Direct | Sally but concise, efficient, minimal preamble |
| `hank_structured` | Hank Structured | Hank's personality running through Sally's 3-layer engine with phase gates |

**Allocation**: Balanced random assignment in experiment mode. For ChatPage, user selects bot.

---

## Database Schema

### DBSession

| Field | Type | Description |
|-------|------|-------------|
| `id` | String (PK) | Session ID |
| `status` | String | "active", "completed", "abandoned" |
| `current_phase` | String | Current NEPQ phase |
| `pre_conviction` | int | Pre-chat conviction score (1–10) |
| `post_conviction` | int | Post-chat conviction score (1–10) |
| `cds_score` | int | Conviction Delta Score (post − pre) |
| `start_time`, `end_time` | float | Unix timestamps |
| `message_count` | int | Total messages in session |
| `assigned_arm` | String | Bot arm name |
| `visitor_id` | String | Persistent visitor identity |
| `user_id` | String (FK, nullable) | Authenticated user |
| `phone_number` | String | E.164 format (SMS sessions) |
| `channel` | String | "web" or "sms" |
| `sms_state` | String | "pre_survey", "active", "post_survey", "done" |
| `platform` | String | "prolific", "mturk", "organic" |
| `platform_participant_id` | String | External platform participant ID |
| `experiment_mode` | String | "true" or null |
| `followup_count` | int | Number of SMS follow-ups sent |
| `legitimacy_score` | int | 0–100 legitimacy score |
| `legitimacy_tier` | String | "verified", "marginal", "suspect" |
| `prospect_profile` | Text (JSON) | Accumulated profile data |
| `thought_logs` | Text (JSON array) | Layer thought logs |

### DBMessage

| Field | Type | Description |
|-------|------|-------------|
| `id` | String (PK) | Message ID |
| `session_id` | String (FK) | Parent session |
| `role` | String | "user" or "assistant" |
| `content` | String | Message text |
| `timestamp` | float | Unix timestamp |
| `phase` | String | NEPQ phase at time of message |

### DBUser

| Field | Type | Description |
|-------|------|-------------|
| `id` | String (PK) | User ID |
| `email` | String (unique) | Email address |
| `password_hash` | String | Hashed password |
| `display_name` | String | Display name |
| `phone` | String | Phone number |
| `created_at`, `last_login_at` | float | Unix timestamps |
| `is_active` | int | 1 = active, 0 = disabled |

### DBMemoryFact (Long-term Memory)

| Field | Type | Description |
|-------|------|-------------|
| `id` | String (PK) | Fact ID |
| `visitor_id` | String (FK) | Visitor this fact belongs to |
| `user_id` | String (FK, nullable) | Authenticated user |
| `source_session_id` | String | Session where fact was extracted |
| `category` | String | "identity", "situation", "pain_point", "preference", "objection_history" |
| `fact_key` | String | "name", "role", "company", "team_size", etc. |
| `fact_value` | Text | The actual fact value |
| `confidence` | float | 0–1 confidence score |
| `created_at`, `updated_at` | float | Unix timestamps |
| `is_active` | int | 1 = active, 0 = superseded |

---

## Key Features

### Memory System (memory.py)

**Extraction**: After session ends, Gemini extracts structured memory facts:
- Identity (name, role, company, industry)
- Situation (team_size, workflow, tools_mentioned, desired_state)
- Pain points, frustrations, objections
- Relationship context (rapport_level, trust_signals, resistance_signals, humor_moments)
- Emotional peaks
- Strategic notes (what_worked, what_didn't, unfinished_threads, next_session_strategy)
- Session summary (2–3 sentences for re-introduction)

**Retrieval**: On new session with visitor_id, `format_memory_for_prompt()` includes:
```
LONG-TERM MEMORY:
[Previously extracted facts about this person]

Use this memory naturally in the conversation.
```

**Returning Visitor Gate**: If memory exists and `current_phase=CONNECTION`, fire "relationship_reconnect" playbook to skip re-discovery.

---

### SMS / Twilio Integration (sms.py, followup.py)

**Inbound SMS Flow**:
1. Prospect texts Twilio number
2. `POST /api/sms/webhook` triggered with `From`, `Body`
3. Generate `visitor_id` from phone hash
4. Lookup active SMS session
5. If `pre_survey` state: validate conviction score (1–10), create session, advance to active
6. If `active`: route message through bot_router, save response, return via TwiML
7. If `post_survey`: validate post-conviction score, compute CDS, end session

**SMS State Machine**:
- `pre_survey` — waiting for conviction score (1–10)
- `active` — conversation in progress
- `post_survey` — waiting for post-conviction score
- `done` — session complete

**Follow-up Worker**: Background thread checks every 5 minutes for stale SMS sessions (no message for N hours):

| Arm | Interval | Max Follow-ups |
|-----|----------|---------------|
| hank_hypes | 12 hours | 3 |
| sally_nepq | 24 hours | 3 |
| ivy_informs | 48 hours | 3 |

Uses Claude Sonnet to generate persona-appropriate follow-up text. User can reply "PAUSE" to stop follow-ups.

---

### Legitimacy Scoring (legitimacy_scorer.py)

Computed immediately after session, zero LLM calls.

**Signals** (0–100 total):

| Signal | Max Points | Description |
|--------|-----------|-------------|
| Total user words | 35 | More engagement = higher score |
| Substantive message ratio | 25 | % of messages with 3+ words |
| Longest single message | 20 | Rich responses score higher |
| Topic relevance | 15 | Mortgage/business keyword hits |
| Off-topic penalty | −30 | "completing study", "not in mortgage", etc. |
| Duplicate detection | Auto-zero | Content hash matches other sessions |

**Tiers**:
- 70–100: **Verified**
- 40–69: **Marginal**
- 0–39: **Suspect**

---

### Quality Scoring (quality_scorer.py)

Post-conversation evaluation of Sally's performance (not real-time).

**Dimensions Scored** (weighted):

| Dimension | Weight | Description |
|-----------|--------|-------------|
| Mirroring | 30% | Did Sally use prospect's exact phrases? |
| Energy Matching | 20% | Did tone match emotional signals? |
| Structure | 25% | Mirror → Validate → Question pattern? |
| Emotional Arc | 25% | Coherent progression through phases? |

Returns 0–100 overall score + per-dimension details + recommendations.

---

### Invitation System (invitation.py)

Builds tracked URLs with UTM parameters:
```
https://www.100x.inc/academy/mortgage-ai-agents
  ?ref=[session_id]
  &arm=[bot_arm]
  &channel=[web|sms]
  &platform=[prolific|mturk|organic]
  &utm_source=sally_sells
  &utm_medium=[arm]
  &utm_campaign=phase1b
```

**Gating**: For web, if `engagement_gate_met=false`, invitation click triggers post-conviction modal first (collects post-score before redirect).

---

### Report Generation (report_generator.py)

Professional PDF research reports with:
- CDS analysis (per-arm, per-platform, percentiles)
- Funnel metrics (completion rate, conversion rate by phase)
- Session quality insights (via Claude analysis)
- Statistical summaries and recommendations
- Exported via `GET /api/export/pdf`

---

### Situation Playbooks (playbooks.py)

Named micro-situations detected by Layer 2, instruction-injected into Layer 3:

| Playbook | Trigger | Instruction |
|----------|---------|-------------|
| `confusion_recovery` | Prospect didn't understand | Apologize, simplify, ask yes/no question |
| `bridge_with_their_words` | Agrees but can't articulate why | Bridge using prospect's exact phrases |
| `resolve_and_close` | Agreed despite objection | Confirm & collect contact |
| `graceful_alternative` | Same objection raised again | Offer free workshop alternative |
| `dont_oversell` | Prospect signals readiness | Present offer directly, stop probing |
| `graceful_exit` | Hard no in late phases | Respect, thank warmly, leave door open |
| `energy_shift` | Thin/flat responses for 3+ turns | Acknowledge dynamic, reset with easier question |
| `specific_probe` | Thin response in critical phase | Ask for lived experience, not hypotheticals |
| `ownership_ceiling` | 8+ turns in OWNERSHIP | One final offer, wrap up gracefully |
| `relationship_reconnect` | Returning visitor in CONNECTION | Reference shared history, catch up first |

---

### Persona Config (persona_config.py)

Per-arm persona overrides injected into Layer 3's system prompt. Defines how the bot's voice, tone, and style change across phases for hybrid arms (e.g., `sally_hank_close` uses Hank's aggressive closing style only in OWNERSHIP and COMMITMENT phases).

---

## Frontend Pages

### ChatPage (`/`)
- User selects bot from dropdown (Sally, Hank, Ivy)
- `ConvictionModal` captures pre-conviction (1–10)
- Chat conversation with messages, timer, phase indicator
- `PostConvictionModal` collects post-conviction score at session end
- Invitation links gated behind post-score modal

### ExperimentPage (`/experiment`)
- Blinded random bot assignment (`experiment_mode=true`)
- `ExperimentSurveyModal`: name, email, conviction
- Bot assignment is hidden from participant
- Shows completion code after session ends
- URL params: `?platform=prolific&pid=XXXXX` for platform tracking

### DashboardPage (`/dashboard`)
- Total sessions, active, completed, abandoned
- CDS trends over time
- Arm breakdown (session count, avg CDS, conversion rate)
- Phase distribution
- Failure mode summary

### HistoryPage (`/history`)
- List all sessions (paginated)
- Session transcript viewer
- Download CSV/PDF exports
- Filter by date, arm, status

### AdminPage (`/admin`)
- Reset allocation counter
- Cleanup stale sessions
- View detailed analytics
- Manual configuration controls

### BookingPage (`/booking/:sessionId`)
- TidyCal booking integration for free workshop alternative
- Shown when prospect declines paid option

---

## Frontend Components

| Component | Purpose |
|-----------|---------|
| `MessageBubble` | Displays user/assistant messages with phase context |
| `ChatInput` | Text input with send button and typing indicators |
| `ConvictionModal` | Pre-chat conviction score (1–10 slider/buttons) |
| `PostConvictionModal` | Post-chat conviction + CDS calculation |
| `PhaseIndicator` | Shows current NEPQ phase in chat UI |
| `BotSwitcher` | Dropdown to select Sally/Hank/Ivy |
| `AuthModal` | Login/register forms |
| `ExperimentSurveyModal` | Experiment pre-survey (name, email, conviction) |
| `Header` | Navigation header |

---

## Frontend API Client (lib/api.ts)

### Types

```typescript
type BotArm =
  | "sally_nepq"
  | "hank_hypes"
  | "ivy_informs"
  | "sally_hank_close"
  | "sally_ivy_bridge"
  | "sally_empathy_plus"
  | "sally_direct"
  | "hank_structured"

interface MessageResponse {
  id: string
  role: "user" | "assistant"
  content: string
  timestamp: number
  phase: string
}

interface CreateSessionResponse {
  session_id: string
  current_phase: string
  pre_conviction: number
  assigned_arm: string
  bot_display_name: string
  greeting: MessageResponse
  visitor_id?: string
}
```

### Key Functions

| Function | Description |
|----------|-------------|
| `getOrCreateVisitorId()` | Persistent visitor identity from localStorage |
| `createSession(score, botArm, experimentMode?, name?, email?, platform?, platformParticipantId?)` | Create session |
| `sendMessage(sessionId, content)` | Send message, get response |
| `endSession(sessionId)` | Explicitly end session |
| `endSessionBeacon(sessionId)` | HTTP keepalive ping on page unload |
| `register(email, password, displayName?, phone?)` | Create account |
| `login(email, password)` | Authenticate & get JWT |
| `identifyByNamePhone(fullName, phone)` | Non-auth identification |
| `getAuthToken()` / `setAuthToken()` / `clearAuth()` / `isAuthenticated()` | Auth token management |

---

## Tests

### Python Tests (backend/tests/)

| File | Coverage |
|------|----------|
| `smoke_test.py` | Full end-to-end conversation flow (5–10 turns) |
| `test_bot_switch.py` | All 8 arms execute correctly |
| `test_control_bots.py` | Hank/Ivy single-prompt execution |
| `test_hybrid_arms.py` | Hybrid arm persona overrides |
| `test_hybrid_integration.sh` | Full bash integration test (multiple flows) |
| `test_auth.py` | Registration, login, JWT tokens |
| `test_sms_integration.py` | SMS webhook, state machine, follow-ups |
| `test_memory_phase_*.py` | Memory extraction & retrieval for returning visitors |
| `test_report_generator.py` | PDF report generation |
| `test_relationship_memory.py` | Cross-session memory coherence |

### Manual Testing

- `test_conversations.sh` — Bash script for interactive conversation testing

---

## Environment Variables

```bash
DATABASE_URL=postgresql://...          # Neon PostgreSQL connection
ANTHROPIC_API_KEY=sk-ant-...           # Claude API key (Layer 3 + ControlBots)
GEMINI_API_KEY=AIzaSy...               # Google Gemini API key (Layer 1)
STRIPE_PAYMENT_LINK=https://...        # Stripe checkout link
STRIPE_SECRET_KEY=sk_test_...          # Stripe secret
STRIPE_PUBLISHABLE_KEY=pk_test_...     # Stripe public key
GOOGLE_SHEETS_WEBHOOK_URL=https://...  # Google Apps Script webhook
TIDYCAL_PATH=m4gek07/free-workshop     # TidyCal booking link path
TWILIO_ACCOUNT_SID=ACxxx               # Twilio account (SMS)
TWILIO_AUTH_TOKEN=xxx                  # Twilio auth token
VITE_API_URL=http://localhost:8000     # Frontend API endpoint
SKIP_SCHEMA_CHECK=true                 # Skip DB schema validation on startup
INVITATION_URL=https://100x.inc/...    # Custom invitation URL override
```

---

## Deployment

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI on Uvicorn |
| Frontend | Vite + React, deployed on Vercel |
| Database | PostgreSQL (Neon) |
| LLM (Layer 1) | Google Gemini Flash |
| LLM (Layer 3 + bots) | Anthropic Claude Sonnet |
| SMS | Twilio |
| Payments | Stripe |
| Analytics export | Google Sheets webhook |

---

## Quick Start

**Backend**:
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export $(cat ../.env | xargs)
uvicorn app.main:app --reload --port 8000
```

**Frontend**:
```bash
cd frontend
npm install
npm run dev
```

**Run Tests**:
```bash
cd backend
pytest tests/smoke_test.py -v
bash tests/test_hybrid_integration.sh
```

---

## Key Design Decisions

1. **Layer 2 is Pure Python** — No LLM in decision logic = predictable, auditable, debuggable phase transitions
2. **Exit Criteria Checklists** — Deterministic phase transitions instead of confidence scores
3. **Criteria Latch** — Once met, criteria stay met; prevents Layer 1 flip-flopping
4. **Fast Path** — Trivial messages (hi, yes, no) skip Layer 1 (Gemini) for lower latency
5. **Uniform Response Shape** — All bots (Sally, Hank, Ivy, hybrids) return the same dict from `route_message()` so `main.py` handles uniformly
6. **Playbook Injection** — Situation detection overlays on default decision; instructions are injected into Layer 3's prompt
7. **Visitor Identity** — Deterministic: phone hash for SMS, localStorage UUID for web; enables memory continuity
8. **Criteria Guidance** — Missing criteria are communicated to Layer 3 as guidance, not hard constraints
9. **Emotional Depth Gate** — Soft fallback prevents trapping prospect in CONSEQUENCE; hard ceiling at 4 turns
10. **Memory for Early Phases** — Returning visitors in CONNECTION/SITUATION can skip minimum turns when prior facts are known
