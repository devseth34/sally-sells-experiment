# Sally Sells - Technical Guide

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Tech Stack](#tech-stack)
4. [Project Structure](#project-structure)
5. [Three-Layer Engine](#three-layer-engine)
6. [NEPQ Phase Sequence](#nepq-phase-sequence)
7. [Database Schema](#database-schema)
8. [API Reference](#api-reference)
9. [Prospect Profile Model](#prospect-profile-model)
10. [Situation Playbooks](#situation-playbooks)
11. [Quality Scoring](#quality-scoring)
12. [Circuit Breaker](#circuit-breaker)
13. [External Integrations](#external-integrations)
14. [Frontend Architecture](#frontend-architecture)
15. [Data Flow](#data-flow)
16. [State Machines](#state-machines)
17. [Edge Cases & Safety Mechanisms](#edge-cases--safety-mechanisms)
18. [Environment Variables](#environment-variables)
19. [Deployment](#deployment)
20. [Debugging & Testing](#debugging--testing)
21. [Common Modifications](#common-modifications)

---

## Overview

Sally Sells is an AI-powered NEPQ (Neuro-Emotional Persuasion Questioning) sales agent that sells 100x's $10,000 AI Discovery Workshop. The system guides prospects through a 7-phase structured conversation designed to achieve authentic sales engagement and measure "Conviction Delta Score" (CDS) — the change in conviction from pre to post-conversation.

**Product being sold:** CEO Nik Shah comes onsite for a full-day Discovery Workshop where he builds a customized AI transformation roadmap identifying $5M+ in annual savings opportunities.

**Target audience:** C-suite executives at companies with 50+ employees in real estate, financial services, and professional services.

**Free alternative:** Online AI Discovery Workshop (booked via TidyCal) offered when the prospect declines the paid option.

---

## Architecture

Sally uses a **three-layer pipeline** architecture where each layer has a distinct responsibility:

```
User Message
     |
     v
+------------------+     +------------------+     +------------------+
|  LAYER 1:        |     |  LAYER 2:        |     |  LAYER 3:        |
|  Comprehension   | --> |  Decision        | --> |  Response        |
|  (The Analyst)   |     |  (The Manager)   |     |  (The Speaker)   |
|                  |     |                  |     |                  |
|  Gemini Flash    |     |  Pure Python     |     |  Claude Sonnet   |
|  Analyzes input  |     |  No LLM calls    |     |  Generates reply |
+------------------+     +------------------+     +------------------+
                                                          |
                                                          v
                                                   Circuit Breaker
                                                          |
                                                          v
                                                   Sally's Response
```

The **critical design decision**: Layer 2 is pure deterministic Python code with zero LLM calls, making conversation flow predictable, debuggable, and auditable.

The orchestrator (`SallyEngine` in `backend/app/agent.py`) wires all three layers together and maintains session state.

---

## Tech Stack

### Backend
| Component | Technology |
|-----------|-----------|
| Web Framework | FastAPI + Uvicorn |
| Language | Python 3.9+ |
| Database | PostgreSQL (Neon serverless) |
| ORM | SQLAlchemy |
| Layer 1 (Comprehension) | Google Gemini 2.0 Flash |
| Layer 3 (Response) | Anthropic Claude Sonnet 4 |
| Payments | Stripe |
| Email | Gmail SMTP |
| Logging | Google Sheets (webhook) |
| Validation | Pydantic |

### Frontend
| Component | Technology |
|-----------|-----------|
| Framework | React 19 |
| Language | TypeScript |
| Build Tool | Vite |
| Styling | Tailwind CSS |
| Routing | React Router v7 |
| Icons | Lucide React |
| Utilities | clsx, tailwind-merge, date-fns |

### Dependencies

**Backend** (`backend/requirements.txt`):
```
fastapi
uvicorn[standard]
sqlalchemy
psycopg2-binary
pydantic
anthropic
stripe
python-dotenv
google-auth
google-generativeai
requests
eval-type-backport
```

**Frontend** (`frontend/package.json`):
```
react ^19.2.0
react-dom ^19.2.0
react-router-dom ^7.13.0
clsx ^2.1.1
tailwind-merge ^3.4.0
lucide-react ^0.563.0
date-fns ^4.1.0
```

---

## Project Structure

```
sally-sells-experiment/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI app, all routes, startup logic
│   │   ├── agent.py             # SallyEngine orchestrator (process_turn)
│   │   ├── database.py          # SQLAlchemy models, DB init, migrations
│   │   ├── models.py            # Pydantic models (Profile, ThoughtLog, enums)
│   │   ├── schemas.py           # API request/response schemas (NepqPhase enum)
│   │   ├── phase_definitions.py # Phase configs, exit criteria, response lengths
│   │   ├── playbooks.py         # 9 situation playbook templates
│   │   ├── quality_scorer.py    # Post-conversation quality scoring
│   │   ├── sheets_logger.py     # Google Sheets webhook logger
│   │   └── layers/
│   │       ├── __init__.py
│   │       ├── comprehension.py # Layer 1: Gemini-powered message analysis
│   │       ├── decision.py      # Layer 2: Pure Python decision logic
│   │       └── response.py      # Layer 3: Claude-powered response generation
│   ├── fact_sheet.txt           # Product knowledge (ground truth for Sally)
│   ├── requirements.txt
│   ├── railway.toml             # Railway deployment config
│   └── test_brain.py            # Integration tests
├── frontend/
│   ├── src/
│   │   ├── App.tsx              # Routes definition
│   │   ├── main.tsx             # React entry point
│   │   ├── index.css            # Global styles + Tailwind
│   │   ├── pages/
│   │   │   ├── ChatPage.tsx     # Main conversation interface
│   │   │   ├── DashboardPage.tsx # Real-time metrics dashboard
│   │   │   ├── HistoryPage.tsx  # Session history browser
│   │   │   └── BookingPage.tsx  # Post-conversation booking/payment
│   │   ├── components/
│   │   │   ├── chat/            # ChatInput, MessageBubble, ConvictionModal, etc.
│   │   │   ├── layout/          # Header, navigation
│   │   │   └── ui/              # Card, Badge, Button, Input primitives
│   │   ├── lib/
│   │   │   ├── api.ts           # Fully typed fetch-based API client
│   │   │   └── utils.ts         # Utility functions
│   │   └── constants/
│   │       └── index.ts         # Phase labels, colors, helpers
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   └── tailwind.config.js
└── experiment_manifest.txt
```

---

## Three-Layer Engine

### Layer 1: Comprehension (The Analyst)

**File:** `backend/app/layers/comprehension.py`
**LLM:** Google Gemini 2.0 Flash (temperature 0.1, max 1500 output tokens)
**Purpose:** Analyze the user's message and produce a structured `ComprehensionOutput`.

Layer 1 performs two jobs:
- **Factual analysis** — extract intent, objections, profile data, and evaluate exit criteria
- **Emotional intelligence** — extract exact phrases worth mirroring, emotional signals, energy level

**Output fields:**

| Field | Type | Description |
|-------|------|-------------|
| `user_intent` | Enum | DIRECT_ANSWER, DEFLECTION, QUESTION, OBJECTION, SMALL_TALK, AGREEMENT, PUSHBACK, CONFUSION |
| `emotional_tone` | str | engaged, skeptical, frustrated, defensive, excited, neutral, warm, guarded |
| `emotional_intensity` | str | low, medium, high |
| `objection_type` | Enum | PRICE, TIMING, AUTHORITY, NEED, NONE |
| `objection_detail` | str? | Specific objection text |
| `profile_updates` | dict | Key-value pairs to merge into ProspectProfile |
| `exit_evaluation` | PhaseExitEvaluation | Per-criterion boolean checklist with evidence |
| `response_richness` | str | thin (1-5 words), moderate (real sentence), rich (multi-sentence) |
| `emotional_depth` | str | surface (factual), moderate (feeling), deep (vulnerability) |
| `new_information` | bool | Does this turn add concrete facts not already in profile? |
| `prospect_exact_words` | list[str] | 2-3 memorable phrases worth mirroring |
| `emotional_cues` | list[str] | Specific emotional signals detected |
| `energy_level` | str | low/flat, neutral, warm, high/excited |
| `objection_diffusion_status` | str | not_applicable, diffused, isolated, resolved, repeated |
| `summary` | str | One-sentence summary of what happened this turn |

**Exit criteria evaluation** uses a checklist model — each phase defines named criteria, and Layer 1 evaluates each as `{met: bool, evidence: str}`. Layer 2 counts booleans deterministically, eliminating subjective confidence scores from the transition path.

**Key system prompt rules:**
- Only extract information the prospect EXPLICITLY stated — never infer
- Pain points must come from the prospect, not suggested by Sally
- Short answers CAN satisfy multiple criteria ("I'm a dev at a fintech startup" = role + company)
- "Yeah" or "ok" with no new info satisfies NOTHING new
- Confusion detection: "I don't understand" = CONFUSION, not PUSHBACK. If both detected, classify as CONFUSION
- In early phases, `objection_diffusion_status` always set to "not_applicable"

**Error handling:** On JSON parse failure from Gemini, retries once. On second failure, returns a safe default `ComprehensionOutput` with all criteria unmet.

### Layer 2: Decision (The Manager)

**File:** `backend/app/layers/decision.py`
**LLM:** None (pure Python)
**Purpose:** Decide what action to take based on Layer 1's structured output.

This is the deterministic brain. It evaluates conditions in strict priority order:

```
Priority 1:  Session time limit (30 min max)
Priority 2:  Already terminated?
Priority 3:  Objection routing (early vs late phase rules)
Priority 3b: Confusion detection → STAY + confusion_recovery playbook
Priority 4:  Gap Builder constraint (required profile fields filled?)
Priority 5:  Minimum turns check (pacing gate — does NOT increment retries)
Priority 6:  Exit criteria evaluation (all must be met to advance)
  6a: Emotional depth gate (CONSEQUENCE → OWNERSHIP)
  6b: Contact info gate (can't END without email + phone)
  6c: Gap Builder check for next phase
Priority 7:  OWNERSHIP substep enforcement (8-turn ceiling, bridge forcing)
Priority 8:  Probing trigger (thin/surface in critical phases)
Priority 9:  Repetition detection (2+ turns no new info)
Priority 10: Break Glass (retry count exceeded max)
Priority 11: Default → STAY, increment retry_count
```

**Actions:**

| Action | Description |
|--------|-------------|
| `ADVANCE` | Move to the next phase (retry_count resets to 0) |
| `STAY` | Remain in current phase |
| `PROBE` | Ask a deeper question on the same topic (retry_count += 1) |
| `REROUTE` | Jump back to an earlier phase (objection-driven, retry_count resets to 0) |
| `BREAK_GLASS` | Emergency: try a completely different angle (retry_count += 1) |
| `END` | Terminate the session |

**Objection routing rules:**
- Agreements with caveats ("yeah but...") are NOT hard objections → STAY to address naturally
- Late phases (OWNERSHIP/COMMITMENT): objections handled in-phase via NEPQ diffusion, never reroute backward
- AUTHORITY objections: always STAY (never reroute), ask who else needs to weigh in
- Early phases: PRICE→CONSEQUENCE, TIMING→PROBLEM_AWARENESS, NEED→SOLUTION_AWARENESS

**Situation detection** (`detect_situation()`) runs after `make_decision()` and overlays playbook instructions when micro-situations are detected. Priority-ordered, first match wins. Skips if decision already has a playbook or action is ADVANCE/END.

### Layer 3: Response (The Speaker)

**File:** `backend/app/layers/response.py`
**LLM:** Claude Sonnet 4 (`claude-sonnet-4-20250514`)
**Purpose:** Generate Sally's response, tightly constrained by Layer 2's decision.

Layer 3 receives:
- The decision (action, target phase, reason)
- Emotional context from Layer 1 (exact words, energy, cues)
- Strategic guidance (which exit criteria are still unmet + natural-language steering hints)
- Prospect profile (accumulated facts)
- Conversation history (last 8 messages)
- Phase-specific instructions (purpose, sentence limits)
- OWNERSHIP substep-specific instructions (commitment question → self-persuasion → bridge → price → objection handling → close)
- Playbook instructions (if applicable)
- Fact sheet (product ground truth, grounding Sally to verified facts only)

**Sally's persona** (defined in `SALLY_PERSONA` constant):
- Sharp, genuinely curious NEPQ consultant at 100x
- Sounds like a smart friend, not a salesperson
- Texts like a real person (lowercase fine, fragments fine)
- In phases 1-4: curious and neutral, like a doctor taking history
- In phase 5: can reflect emotions the prospect explicitly expressed
- In phases 6-7: warmer, earned through the journey, CONVICTION tonality

**Response pattern:** Mirror (optional, 2-5 words) → optional validation → ONE question

**Criteria-based steering:** The `CRITERIA_GUIDANCE` dict maps each unmet criterion to a natural-language instruction telling Sally what to steer toward without being robotic about it. For example, `role_shared` → "Find out what they do. Ask about their role or position."

**Hard rules enforced:**
1. ONE question per response (never stack with "and" or "like")
2. Phase-specific sentence limits (2-4 max)
3. Never mention workshop/100x/Nik Shah/price before OWNERSHIP
4. Never give advice before OWNERSHIP (only questions)
5. No hype words (~20 forbidden words)
6. No forbidden phrases (~14 phrases like "got it", "tell me more")
7. No editorializing in early phases (~25 editorial phrases blocked)
8. No em dashes or semicolons
9. Stop selling when they say yes
10. Never repeat a question
11. Vary question structure (never 2 responses in a row starting the same way)

**Prompt caching:** Ephemeral cache on the `SALLY_PERSONA` system prompt via `cache_control: {"type": "ephemeral"}`.

---

## NEPQ Phase Sequence

Seven phases in strict forward progression (except objection rerouting). Defined in `backend/app/phase_definitions.py`.

| # | Phase | Purpose | Min Turns | Max Retries | Exit Criteria |
|---|-------|---------|-----------|-------------|---------------|
| 1 | **CONNECTION** | Build rapport, learn role/company/AI interest | 2 | 3 | role_shared, company_or_industry_shared, ai_interest_stated |
| 2 | **SITUATION** | Map current operations, day-to-day workflow | 1 | 3 | workflow_described, concrete_detail_shared |
| 3 | **PROBLEM_AWARENESS** | Surface real pain in prospect's OWN words | 3 | 4 | specific_pain_articulated, pain_is_current |
| 4 | **SOLUTION_AWARENESS** | Paint desired future, create gap | 2 | 3 | desired_state_described, gap_is_clear |
| 5 | **CONSEQUENCE** | Make cost of inaction real and personal | 2 | 4 | cost_acknowledged, urgency_felt |
| 6 | **OWNERSHIP** | Present $10K offer, handle objections | 2 | 4 | commitment_question_asked, prospect_self_persuaded, price_stated, definitive_response |
| 7 | **COMMITMENT** | Collect email/phone, send link, close | 1 | 5 | positive_signal_or_hard_no, email_collected, phone_collected, link_sent |

A special `TERMINATED` phase exists as the end state when the session is over.

**Response length constraints per phase:**

| Phase | Max Sentences | Max Tokens |
|-------|---------------|-----------|
| CONNECTION | 2 | 120 |
| SITUATION | 2 | 120 |
| PROBLEM_AWARENESS | 3 | 150 |
| SOLUTION_AWARENESS | 3 | 150 |
| CONSEQUENCE | 3 | 180 |
| OWNERSHIP | 4 | 200 |
| COMMITMENT | 4 | 300 |

Each phase definition also includes:
- `purpose` — behavioral description for Layer 3
- `sally_objectives` — detailed guidance (with empathy instructions)
- `extraction_targets` — which ProspectProfile fields to fill
- `question_patterns` — example questions
- `advance_when` — "all" (all criteria must be met) or "all_or_hard_no" (COMMITMENT special case)

---

## Database Schema

PostgreSQL (Neon serverless) with SQLAlchemy ORM. Defined in `backend/app/database.py`.

### `sessions` table (`DBSession`)

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `id` | String (PK) | — | 8-char uppercase UUID, e.g. "A1B2C3D4" |
| `status` | String | "active" | "active", "completed", "abandoned" |
| `current_phase` | String | "CONNECTION" | Current NEPQ phase name |
| `pre_conviction` | Integer? | — | 1-10 pre-chat conviction score |
| `post_conviction` | Integer? | — | 1-10 post-chat conviction score |
| `cds_score` | Integer? | — | Conviction Delta Score (post - pre) |
| `start_time` | Float | — | Unix timestamp |
| `end_time` | Float? | — | Unix timestamp when session ended |
| `message_count` | Integer | 0 | Total messages in session |
| `turn_number` | Integer | 0 | Conversation turn counter |
| `retry_count` | Integer | 0 | Failed turn attempts in current phase |
| `consecutive_no_new_info` | Integer | 0 | Repetition detection counter |
| `turns_in_current_phase` | Integer | 0 | Phase-specific pacing counter |
| `deepest_emotional_depth` | String | "surface" | "surface", "moderate", "deep" |
| `objection_diffusion_step` | Integer | 0 | Objection handling state (0-3) |
| `ownership_substep` | Integer | 0 | OWNERSHIP phase microsequence (0-6) |
| `prospect_profile` | Text | "{}" | JSON-serialized ProspectProfile |
| `thought_logs` | Text | "[]" | JSON array of ThoughtLog objects |
| `escalation_sent` | String? | — | Timestamp when escalation email sent |

### `messages` table (`DBMessage`)

| Column | Type | Description |
|--------|------|-------------|
| `id` | String (PK) | UUID |
| `session_id` | String (indexed) | Foreign key to sessions |
| `role` | String | "user" or "assistant" |
| `content` | String | Message text |
| `timestamp` | Float | Unix timestamp |
| `phase` | String | Phase when message was sent |

### Migrations

Auto-applied on startup via `init_db()` unless `SKIP_SCHEMA_CHECK=true`. The migration system:
1. Runs `Base.metadata.create_all()` — creates tables if they don't exist
2. Inspects existing columns via SQLAlchemy `inspect()`
3. Adds missing columns via ALTER TABLE (safe for existing databases)
4. Logs timing for performance monitoring

Set `SKIP_SCHEMA_CHECK=true` in production to skip this on every cold start (~10s savings).

---

## API Reference

Base URL: `/api`

### Session Management

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/sessions` | Create session (requires `pre_conviction: 1-10`) |
| `POST` | `/api/sessions/{id}/messages` | Send message, get Sally's response (the core loop) |
| `GET` | `/api/sessions` | List all sessions with summary metrics |
| `GET` | `/api/sessions/{id}` | Get full session detail (messages, thought logs, profile) |
| `POST` | `/api/sessions/{id}/end` | Manually end/abandon session |

### Conviction & Scoring

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/sessions/{id}/post-conviction` | Submit post-chat conviction (1-10), compute CDS |
| `POST` | `/api/sessions/{id}/quality-score` | Run/re-run quality scoring |
| `GET` | `/api/sessions/{id}/thoughts` | Debug: view Sally's internal thought logs |

### Metrics & Export

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/metrics` | Aggregated metrics (totals, averages, phase distribution, failure modes) |
| `GET` | `/api/export/csv` | Export all sessions + transcripts as CSV download |

### Stripe Integration

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/checkout` | Create Stripe Checkout Session ($10,000 workshop) |
| `GET` | `/api/checkout/verify/{checkoutSessionId}` | Verify payment status |

### Configuration & Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/config` | Client-safe config (Stripe publishable key, TidyCal path) |
| `GET` | `/` | Root health check |

### Core Loop Detail: `POST /api/sessions/{id}/messages`

This endpoint processes a single conversation turn:

1. Validates session is active (404 if not found, 400 if not active)
2. Saves user message to DB with current phase
3. Builds full conversation history from DB
4. Calls `SallyEngine.process_turn()` with all state counters
5. Updates all session state from engine result
6. Appends thought log entry
7. If session ended: logs to Google Sheets, starts async quality scoring
8. If entering OWNERSHIP (first time): sends escalation email, logs hot lead
9. Replaces `[PAYMENT_LINK]` placeholder with real Stripe Checkout URL
10. Saves assistant message to DB
11. Returns `SendMessageResponse` with phase change and session end flags

**Error recovery:** If the engine throws, returns a safe fallback response ("How has that been playing out for you day-to-day?") and increments retry count.

---

## Prospect Profile Model

Defined in `backend/app/models.py` as `ProspectProfile` (Pydantic BaseModel). Accumulated across phases and serialized as JSON in the `sessions.prospect_profile` column.

```
CONNECTION phase:      name, role, company, industry
SITUATION phase:       current_state, team_size, tools_mentioned[]
PROBLEM_AWARENESS:     pain_points[], frustrations[]
SOLUTION_AWARENESS:    desired_state, success_metrics[]
CONSEQUENCE:           cost_of_inaction, timeline_pressure, competitive_risk
OWNERSHIP:             decision_authority, decision_timeline, budget_signals
COMMITMENT:            email, phone
Cross-phase tracking:  objections_encountered[], objections_resolved[]
```

**Update logic** (`SallyEngine.update_profile`):
- **List fields** (pain_points, frustrations, tools_mentioned, success_metrics, objections_encountered, objections_resolved): new items are appended (deduplicated)
- **Scalar fields** (name, role, company, etc.): replaced if the new value is non-null and non-empty
- Objections are tracked automatically: when Layer 1 detects a non-NONE objection, the text is added to `objections_encountered`

---

## Situation Playbooks

Defined in `backend/app/playbooks.py`. Named micro-sequences that override default Layer 2/3 behavior for specific detected situations. Each playbook has: an instruction template, `max_consecutive_uses`, and an `overrides_action` flag.

| Playbook | Trigger | Action Override | Max Uses | Strategy |
|----------|---------|----------------|----------|----------|
| `confusion_recovery` | `user_intent == CONFUSION` | Yes (STAY) | 2 | Apologize, state value prop in 1 sentence, ask yes/no |
| `bridge_with_their_words` | OWNERSHIP substep 2, self-persuasion failed | Yes (STAY) | 1 | Use prospect's exact pain/frustration/cost language to bridge |
| `resolve_and_close` | OWNERSHIP + objection isolated + agreement | No | 1 | Ask: "if we could figure out the [objection] piece..." |
| `graceful_alternative` | Late phase + same objection repeated after diffusion | Yes (STAY) | 1 | Offer free workshop positively (not as consolation) |
| `dont_oversell` | Spontaneous buy signal in CONSEQUENCE/OWNERSHIP | Yes (STAY) | 1 | Stop asking, present offer directly, state $10K, wait |
| `graceful_exit` | Hard no (high intensity PUSHBACK) in late phase | Yes (STAY) | 1 | Thank warmly, offer free resource, end. No re-selling |
| `energy_shift` | Exactly 3 consecutive thin/low-energy turns | No | 1 | Acknowledge "I'm asking a lot", share observation, easier question |
| `specific_probe` | Thin+surface in critical phase + PROBE action | No | 2 | Time-anchored lived-experience question |
| `ownership_ceiling` | 8+ turns in OWNERSHIP | Yes (STAY) | 1 | Force free workshop offer, then close |

**Template variables:** `{pain_points}`, `{frustrations}`, `{cost_of_inaction}`, `{first_pain}`, `{pain_summary}`, `{consequence}`, `{prospect_name}`, `{objection_type}`. Filled from ProspectProfile at runtime. Falls back to raw instruction on template errors.

---

## Quality Scoring

**File:** `backend/app/quality_scorer.py`

Post-conversation async evaluation that scores Sally's execution. Uses Claude Sonnet 4 to analyze the full transcript against thought logs.

**Dimensions (0-100 scale):**

| Dimension | Weight | What It Measures |
|-----------|--------|-----------------|
| Mirroring | 30% | Did Sally use the exact phrases Layer 1 flagged for mirroring? |
| Energy Matching | 20% | Did Sally's tone match the prospect's detected energy level? |
| Structure | 25% | Did Mirror → Validate → Question pattern hold per turn? |
| Emotional Arc | 25% | Coherent emotional progression across all phases? |

**`overall_score`** = weighted average of the four dimensions.

**Input:** Full transcript formatted as `[Phase] Role: Content`, plus a per-turn thought log summary (flagged phrases, emotional cues, energy, tone, response preview).

**Output:** `ConversationQualityScore` with per-dimension scores, detail text, and a list of specific recommendations for improvement.

**Execution:** Runs in a daemon thread after conversation ends (fire-and-forget). Results are appended to the session's `thought_logs` JSON as `{"quality_score": {...}}`.

**On-demand:** `POST /api/sessions/{id}/quality-score` triggers scoring for any completed or abandoned session. Previous quality_score entries are removed before adding the new one.

---

## Circuit Breaker

**File:** `backend/app/layers/response.py` — `circuit_breaker()` function

Post-generation validation that catches rule violations before responses reach the prospect. Runs on every Layer 3 output.

**Checks performed (in order):**

| # | Check | Action |
|---|-------|--------|
| 0 | Em dashes and semicolons | Replace with commas/periods |
| 1 | Multiple questions (>1 `?`) | Keep only up to first `?` |
| 1b | "And" question stacking | Strip everything after `, and ` before `?` |
| 1c | "Like" question stacking | Strip everything after `, like ` before `?` |
| 2 | Forbidden words (~20 hype words) | Return full fallback response |
| 3 | Forbidden phrases (~14 phrases) | Strip phrase, clean orphaned punctuation |
| 4 | Editorial phrases in early phases (~25) | Strip phrase, clean punctuation |
| 4b | Fragment echo opener | Strip if response starts with 3+ consecutive words from prospect's last message |
| 5 | Pitching before CONSEQUENCE | Return fallback if $10,000/workshop/nik shah/100x detected in early phases |
| 6 | Response too long | Trim to phase-specific sentence limit (relaxed to 10 for closing) |
| 7 | Safety net | If <4 meaningful words remain after all cleaning, return fallback |

**Fallback responses:**
- Default: "How has that been playing out for you day-to-day?"
- Early-phase pitch detected: "What's been the biggest challenge with that so far?"

**Mirror repetition detection** (`_detect_mirror_repetition`): Separate pre-generation check. Examines last 3 Sally/user pairs. If 2+ Sally responses started with a trigram from the preceding user message in the first 8 words, injects variation instructions into the Layer 3 prompt.

---

## External Integrations

### Anthropic Claude API
- **Model:** `claude-sonnet-4-20250514`
- **Used in:** Layer 3 (response generation), Quality Scorer
- **Client:** Lazy-initialized singleton (`_get_client()`)
- **Caching:** Ephemeral prompt caching on system prompt

### Google Gemini API
- **Model:** `gemini-2.0-flash`
- **Used in:** Layer 1 (comprehension/analysis)
- **Config:** Temperature 0.1, max 1500 output tokens
- **Safety settings:** All categories set to BLOCK_NONE
- **Error handling:** One automatic retry on JSON parse failure

### Stripe
- **Product:** "100x AI Discovery Workshop" ($10,000 = 1,000,000 cents)
- **Lazy creation:** Searches for existing product by name, creates product + price if not found
- **Checkout flow:** Creates Checkout Session → user redirected → verify payment status on return
- **Inline links:** `[PAYMENT_LINK]` placeholder in Sally's response is replaced with a dynamic Stripe Checkout URL
- **Metadata:** Session ID, prospect name/company/role attached to checkout sessions
- **Fallback:** `STRIPE_PAYMENT_LINK` env var used if dynamic Checkout Session creation fails

### Google Sheets (Webhook)
- **Mechanism:** HTTP POST to a Google Apps Script web app
- **Execution:** Fire-and-forget via non-daemon threads (`daemon=False` so threads complete even if main process exits)
- **Custom redirect handler:** `_PostRedirectHandler` preserves POST method through 301/302/303/307/308 redirects
- **Log types:**
  - `session` — completed or abandoned sessions (full profile + transcript)
  - `hot_lead` — when prospect reaches OWNERSHIP phase
  - `conversion` — when Stripe payment is confirmed
- **Cell limit:** Transcripts truncated at 49,000 chars (Google Sheets 50K cell limit)
- **Graceful degradation:** Silently skipped if `GOOGLE_SHEETS_WEBHOOK_URL` is not set

### Gmail SMTP
- **Purpose:** Escalation email when prospect first reaches OWNERSHIP phase
- **Trigger:** Exactly once per session, on first transition into OWNERSHIP
- **Content:** Subject line with prospect name/company, body with full transcript + profile + pain points + objections
- **Protocol:** SMTP_SSL on port 465 (smtp.gmail.com)
- **Graceful degradation:** Logs warning and skips if credentials not configured

### TidyCal
- **Purpose:** Calendar booking for the free online AI Discovery Workshop
- **Integration:** URL (`https://tidycal.com/{TIDYCAL_PATH}`) included verbatim in Sally's response text for free workshop prospects, embedded on BookingPage in frontend

### Fact Sheet (`backend/fact_sheet.txt`)
- **Purpose:** Ground truth for Sally — constrains her to verified product facts only
- **Loaded:** Once at module level in `response.py`, injected into every Layer 3 prompt
- **Contents:** Company info, product details, pricing, target audience, process, common objections, and things Sally must never say
- **Rule:** If the prospect asks something not covered in the fact sheet, Sally says she'll have the team follow up

---

## Frontend Architecture

### Routes (`frontend/src/App.tsx`)

| Path | Component | Purpose |
|------|-----------|---------|
| `/` | ChatPage | Main conversation interface |
| `/dashboard` | DashboardPage | Real-time metrics dashboard |
| `/history` | HistoryPage | Session history browser |
| `/booking/:sessionId` | BookingPage | Post-conversation booking/payment |

### Pages

**ChatPage** — The primary interface:
- `ConvictionModal` at start: pre-conviction 1-10 selection
- Real-time message display with `PhaseIndicator` progress bar
- Session timer in header with color warnings (amber >25min, red >28min)
- `PostConvictionModal` when session ends: post-conviction + CDS display
- Session end on tab close via `pagehide`/`beforeunload` using `navigator.sendBeacon`
- "Book & Pay" button navigates to BookingPage after session ends

**DashboardPage** — Analytics:
- Auto-refreshing metrics (every 10 seconds)
- Phase distribution visualization
- Drop-off points (failure modes) analysis

**HistoryPage** — Session browser:
- All sessions listed with filtering by status
- Session detail view: full transcript + thought logs
- CSV export button

**BookingPage** — Post-conversation:
- Paid workshop: Stripe Checkout redirect flow
- Free workshop: TidyCal embed
- Payment verification on return from Stripe (checks `checkout_session_id` query param)

### API Client (`frontend/src/lib/api.ts`)

Fully typed fetch-based client with TypeScript interfaces for all API responses.

**Key functions:**
- `createSession(preConviction)` → `CreateSessionResponse`
- `sendMessage(sessionId, content)` → `SendMessageResponse`
- `endSession(sessionId)` → void
- `endSessionBeacon(sessionId)` → void (uses `navigator.sendBeacon` for reliable tab-close handling)
- `submitPostConviction(sessionId, postConviction)` → `PostConvictionResponse`
- `createCheckoutSession(sessionId?)` → `CheckoutResponse`
- `verifyPayment(checkoutSessionId)` → `PaymentVerification`
- `getMetrics()` → `MetricsResponse`
- `listSessions()` → `SessionListItem[]`
- `getSession(sessionId)` → `SessionDetail`
- `getConfig()` → `AppConfig`
- `getExportCsvUrl()` → string

**Base URL:** `VITE_API_URL` env var (defaults to `http://localhost:8000`) + `/api`

### Phase Constants (`frontend/src/constants/index.ts`)

Maps phase enum values to display labels, colors, and short labels. Helper functions: `getPhaseLabel()`, `getPhaseColor()`, `getPhaseIndex()`.

---

## Data Flow

### Turn-by-Turn Flow (`POST /api/sessions/{sessionId}/messages`)

```
USER MESSAGE ARRIVES
  |
  v
1. SAVE TO DB (user message with current phase)
  |
  v
2. BUILD CONVERSATION HISTORY (all messages from DB, ordered by timestamp)
  |
  v
3. LAYER 1: COMPREHENSION (Gemini Flash)
   ├─ Analyzes message + last 10 messages + current profile
   └─ Returns ComprehensionOutput (intent, objection, profile_updates, exit_eval, emotions)
  |
  v
4. UPDATE PROFILE (apply Layer 1 extractions)
   ├─ List fields: append (deduplicated)
   └─ Scalar fields: replace if non-empty
  |
  v
5. TRACK STATE
   ├─ consecutive_no_new_info: increment or reset to 0
   ├─ deepest_emotional_depth: ratchet up only (surface → moderate → deep)
   ├─ objection_diffusion_step: 0-3 state machine
   ├─ ownership_substep: 0-6 state machine
   └─ turns_in_current_phase: increment
  |
  v
6. LAYER 2: DECISION (pure Python)
   ├─ 11 priority-ordered checks
   └─ Returns DecisionOutput (action, target_phase, reason, retry_count)
  |
  v
7. SITUATION DETECTION (after decision)
   ├─ Checks for playbook triggers
   └─ May override action to STAY, inject playbook name into objection_context
  |
  v
8. BUILD EMOTIONAL CONTEXT (dict for Layer 3)
   ├─ prospect_exact_words, emotional_cues, energy_level, emotional_tone
   ├─ exit_evaluation_criteria (which criteria are met/unmet)
   ├─ ownership_substep, missing_criteria, missing_info
   └─ Criteria guidance (natural-language steering for unmet criteria)
  |
  v
9. LAYER 3: RESPONSE (Claude Sonnet)
   ├─ Generates Sally's response constrained by decision + emotional context
   └─ Circuit breaker validates and cleans output
  |
  v
10. SIDE EFFECTS
    ├─ If [PAYMENT_LINK] in response: create Stripe Checkout, replace placeholder
    ├─ If session_ended: async quality scoring (daemon thread)
    ├─ If session_ended: log to Google Sheets ("session")
    ├─ If entering OWNERSHIP (first time): send escalation email
    └─ If entering OWNERSHIP (first time): log to Google Sheets ("hot_lead")
  |
  v
11. SAVE ASSISTANT MESSAGE TO DB + RETURN TO CLIENT
    └─ Response includes: user_message, assistant_message, current_phase,
       previous_phase, phase_changed, session_ended
```

### Session Initialization (`POST /api/sessions`)

```
1. Generate 8-char uppercase UUID session ID
2. Create DBSession (status=active, phase=CONNECTION, pre_conviction, empty profile)
3. Generate greeting via SallyEngine.get_greeting()
4. Create greeting DBMessage (role=assistant, phase=CONNECTION)
5. Return CreateSessionResponse (session_id, phase, pre_conviction, greeting)
```

---

## State Machines

### Emotional Depth Ratchet

Tracked in `agent.py`. **Only upgrades, never downgrades.** Persists across phase changes (the only counter that does).

```
Depth order: surface (0) → moderate (1) → deep (2)

Each turn: if comprehension.emotional_depth > deepest_emotional_depth → upgrade
```

Used as a gate for CONSEQUENCE → OWNERSHIP advancement:
- "deep" → always passes
- "moderate" + 3 turns in CONSEQUENCE → passes
- 4+ turns in CONSEQUENCE → hard fallback (always passes, prevents infinite trapping)

### Objection Diffusion Steps (OWNERSHIP/COMMITMENT)

Tracks the NEPQ objection handling protocol. Steps 0-3:

| Step | State | Meaning |
|------|-------|---------|
| 0 | No active objection | Default state |
| 1 | Objection detected, diffusing | Sally says "that's not a problem..." |
| 2 | Objection isolated | Prospect said yes to isolation question |
| 3 | Objection resolved | Prospect agreed to move forward |

**Transitions:**
- New objection in late phase: 0 → 1
- `objection_diffusion_status == "repeated"`: restart at 1
- `objection_diffusion_status == "diffused"`: maintain ≥ 1
- `objection_diffusion_status == "isolated"`: maintain ≥ 2
- `objection_diffusion_status == "resolved"`: set to 3
- `user_intent == AGREEMENT` while step > 0: hard reset to 0

**Resets to 0 on phase change.**

### Ownership Substep Machine (OWNERSHIP phase only)

6-step microsequence implementing Jeremy Miner's NEPQ close:

| From | To | Condition |
|------|----|-----------|
| 0 | 1 | First turn in OWNERSHIP (initialize) |
| 1 | 2 | Commitment question asked + prospect positive response (AGREEMENT or DIRECT_ANSWER) |
| 2 | 3 | Self-persuasion failed (thin response or CONFUSION) → bridge |
| 2 | 4 | Self-persuasion succeeded (prospect_self_persuaded criterion met) |
| 3 | 4 | Auto-advance next turn (bridge is ONE attempt only; uses `original_substep` to distinguish entry) |
| 4 | 5 | Price stated + objection raised → objection handling |
| 4 | 6 | Price stated + AGREEMENT or definitive_response → close |
| 5 | 6 | Objection resolved or AGREEMENT |

**Resets to 0 on phase change.**

### Repetition Detection

```
consecutive_no_new_info counter:
  new_information == true  → reset to 0
  new_information == false → increment by 1

Threshold ≥ 2 triggers:
  - If ≥ 50% exit criteria met → force ADVANCE
  - If < 50% criteria met → BREAK_GLASS
```

### Retry Counter

```
Incremented by: PROBE, BREAK_GLASS, default STAY
NOT incremented by: confusion routing, minimum turn enforcement
Reset to 0 by: ADVANCE, REROUTE

Thresholds:
  retry_count ≥ max_retries → Break Glass (try different angle or force advance)
  retry_count ≥ max_retries + 2 → Hard ceiling (force advance regardless)
```

### Phase Change Resets

When the phase changes, these counters reset to 0:
- `turns_in_current_phase`
- `objection_diffusion_step`
- `ownership_substep`

`deepest_emotional_depth` does NOT reset (it's a conversation-wide metric).

---

## Edge Cases & Safety Mechanisms

### State Machine Edge Cases
| Case | Handling |
|------|---------|
| Ownership substep 3 (bridge) timing | Uses `original_substep` variable to distinguish "just entered 3" from "was already in 3", preventing double-advance |
| Emotional depth persistence | Only metric that survives phase changes; never resets, never downgrades |
| Objection diffusion hard reset | User says AGREEMENT while step > 0 → immediate reset to 0 |

### Decision Layer Edge Cases
| Case | Handling |
|------|---------|
| Confusion detected | Does NOT increment retry_count (Sally's fault, not prospect's) |
| Minimum turns not reached | Does NOT increment retry_count (pacing, not failure) |
| Exit criteria met but thin response | ADVANCE wins — criteria checked BEFORE probe trigger |
| Late-phase objections | NEVER reroute backward from OWNERSHIP/COMMITMENT; always NEPQ diffusion in-phase |
| Authority objection | Always STAY (never reroute); ask who else needs to weigh in |
| Agreement + caveat objection | Treated as caveat, not hard objection → STAY to address naturally |
| Contact info gate | Can't END without email + phone after positive signal |
| CONSEQUENCE → OWNERSHIP gate | Requires emotional depth (deep, or moderate+3 turns, or 4-turn fallback) |
| Break Glass two-tier | Force advance at max_retries if ≥50% criteria; hard ceiling at max_retries+2 |

### Response Layer Edge Cases
| Case | Handling |
|------|---------|
| Empty conversation history | Returns hardcoded greeting |
| Multiple questions generated | Circuit breaker keeps only up to first `?` |
| Response too short after cleaning | Returns fallback response |
| Quote-wrapped response | Strips wrapping `"..."` before circuit breaker |
| Closing messages | Relaxed to 10-sentence limit and 300 max tokens |

### API Layer Edge Cases
| Case | Handling |
|------|---------|
| Engine processing error | Returns safe fallback response, increments retry, continues session |
| JSON parse failure (profile/thought_logs) | Treats as empty `{}` or `[]` |
| Quality scoring thread error | Logged, does not crash or affect response |
| Stripe API key missing | Falls back to `STRIPE_PAYMENT_LINK` env var for link substitution |
| Gmail config missing | Logs warning, silently skips escalation email |
| Sheets webhook not configured | Silently skips all Google Sheets logging |

---

## Environment Variables

All environment variables are loaded once in `database.py` via `load_dotenv()`. No other module should call `load_dotenv()`.

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string (Neon format) |
| `ANTHROPIC_API_KEY` | Yes | Claude API key for Layer 3 + Quality Scorer |
| `GEMINI_API_KEY` | Yes | Google Generative AI key for Layer 1 |
| `STRIPE_SECRET_KEY` | Yes | Stripe secret key for checkout sessions |
| `STRIPE_PUBLISHABLE_KEY` | Yes | Stripe publishable key (exposed to frontend via `/api/config`) |
| `STRIPE_PAYMENT_LINK` | No | Fallback pre-configured payment link URL |
| `GOOGLE_SHEETS_WEBHOOK_URL` | No | Google Apps Script webhook URL for logging |
| `TIDYCAL_PATH` | No | TidyCal calendar embed path (e.g. `m4gek07/...`) |
| `GMAIL_USER` | No | Gmail address for sending escalation emails |
| `GMAIL_APP_PASSWORD` | No | Gmail app-specific password |
| `ESCALATION_EMAIL` | No | Recipient email for hot lead escalation |
| `FRONTEND_URL` | No | Frontend origin for Stripe redirect URLs (default: `http://localhost:5173`) |
| `SKIP_SCHEMA_CHECK` | No | Set to `true` in production to skip DB migrations on startup |
| `VITE_API_URL` | No | Frontend env: backend API base URL (default: `http://localhost:8000`) |

---

## Deployment

### Backend (Railway)

Configured in `backend/railway.toml`:
```toml
[build]
builder = "nixpacks"
providers = ["python"]

[deploy]
startCommand = "uvicorn app.main:app --host 0.0.0.0 --port $PORT"
healthcheckPath = "/"
restartPolicyType = "on_failure"
restartPolicyMaxRetries = 3
```

### Production Considerations

- **Cold start:** Set `SKIP_SCHEMA_CHECK=true` to skip DB migration check (~10s savings)
- **Database:** Neon PostgreSQL (serverless, auto-scaling). Connection pool: 5 connections, 10 overflow
- **CORS:** Allows all origins (`allow_origins=["*"]`)
- **Async tasks:** Google Sheets logging and quality scoring run in background threads (non-blocking)
- **Stripe keys:** Replace test keys with live keys for production
- **Optional integrations:** Google Sheets, Gmail, TidyCal all degrade gracefully if not configured

### Running Locally

**Backend:**
```bash
cd backend
pip install -r requirements.txt
# Create .env with at minimum: DATABASE_URL, ANTHROPIC_API_KEY, GEMINI_API_KEY, STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY
uvicorn app.main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
# Optionally create .env with VITE_API_URL if backend isn't at localhost:8000
npm run dev  # starts Vite dev server on http://localhost:5173
```

---

## Debugging & Testing

### Debug Endpoints

- `GET /api/sessions/{id}/thoughts` — View Sally's complete internal monologue for a session. Each turn includes the full ComprehensionOutput, DecisionOutput, response text, and profile snapshot
- `POST /api/sessions/{id}/quality-score` — Run or re-run quality scoring on any completed/abandoned session

### Logging

All loggers use the `sally.*` namespace at INFO level by default:

| Logger | What It Logs |
|--------|-------------|
| `sally.api` | API request handling, session lifecycle |
| `sally.engine` | Orchestrator: per-turn layer results, state tracking, latency |
| `sally.comprehension` | Layer 1: Gemini calls, parse errors, retries |
| `sally.response` | Layer 3: Claude calls, circuit breaker violations |
| `sally.quality` | Quality scorer: dimension scores, errors |
| `sally.sheets` | Google Sheets webhook: dispatch, HTTP responses, errors |
| `sally.startup` | Database initialization timing, migration results |

**Per-turn latency tracking** (logged by sally.engine):
```
[Turn 5] LATENCY SUMMARY: L1=342ms | L2=0ms | L3=1205ms | Total=1548ms
```

**Per-turn state tracking** (logged by sally.engine):
```
[Turn 5] Tracking: new_info=true, consecutive_no_new_info=0, turns_in_phase=3,
         richness=moderate, depth=moderate, deepest_depth=moderate,
         diffusion_step=0, ownership_substep=0
```

### Test File

`backend/test_brain.py` — simulates conversation turns and tests phase transitions through the engine.

### Thought Logs

Every turn produces a `ThoughtLog` object stored in the session's `thought_logs` JSON array. Each contains:
- `turn_number` and `user_message`
- `comprehension` — full ComprehensionOutput (intent, objection, exit_eval, emotions, etc.)
- `decision` — full DecisionOutput (action, target_phase, reason)
- `response_phase` and `response_text`
- `profile_snapshot` — complete ProspectProfile state at that point

Quality scoring results are also appended as `{"quality_score": {...}}` entries.

This gives complete visibility into why Sally said what she said at every turn, making the system fully auditable.

---

## Common Modifications

| Change | File(s) to Modify |
|--------|-------------------|
| Add a new NEPQ phase | `backend/app/schemas.py` (NepqPhase enum), `backend/app/phase_definitions.py` (PHASE_DEFINITIONS), `backend/app/layers/decision.py` (PHASE_ORDER) |
| Change exit criteria for a phase | `backend/app/phase_definitions.py` (exit_criteria_checklist) |
| Add a new objection type | `backend/app/models.py` (ObjectionType enum), `backend/app/layers/decision.py` (OBJECTION_ROUTING) |
| Modify Sally's persona/voice | `backend/app/layers/response.py` (SALLY_PERSONA constant) |
| Change decision logic priorities | `backend/app/layers/decision.py` (make_decision function) |
| Add a situation playbook | `backend/app/playbooks.py` (PLAYBOOKS dict) + `backend/app/layers/decision.py` (detect_situation) |
| Update quality scoring weights | `backend/app/quality_scorer.py` (QUALITY_SCORER_PROMPT) |
| Modify forbidden words/phrases | `backend/app/layers/response.py` (FORBIDDEN_WORDS, FORBIDDEN_PHRASES, EDITORIAL_PHRASES) |
| Update product facts | `backend/fact_sheet.txt` |
| Change response length limits | `backend/app/phase_definitions.py` (response_length per phase) |
| Update criteria steering guidance | `backend/app/layers/response.py` (CRITERIA_GUIDANCE dict) |
| Add a new API endpoint | `backend/app/main.py` |
| Add a new frontend page | Create `frontend/src/pages/{Name}Page.tsx` + add route in `frontend/src/App.tsx` |
| Change the greeting | `backend/app/agent.py` (SallyEngine.get_greeting) |
| Modify Layer 1 analysis prompt | `backend/app/layers/comprehension.py` (COMPREHENSION_SYSTEM_PROMPT_BASE, build_comprehension_prompt) |
| Change the LLM model | `backend/app/layers/comprehension.py` (Gemini model name) or `backend/app/layers/response.py` (Claude model name) |
