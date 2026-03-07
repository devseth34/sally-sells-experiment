# Sally Sells — Technical Documentation

## Overview

Sally Sells is an agentic AI sales state machine that uses a three-layer NEPQ (Neuro-Emotional Persuasion Questions) pipeline to conduct sales conversations. It includes three bots for A/B/C testing: **Sally** (NEPQ engine), **Hank** (aggressive sales), and **Ivy** (neutral information).

The system supports **persistent memory** — returning visitors get personalized greetings, pre-populated profiles, and context from prior conversations injected into all AI prompts. **Three-tier user authentication** enables cross-device memory persistence via email/password accounts, soft identification via name+phone, and anonymous localStorage UUIDs as fallback.

---

## Architecture

```
Frontend (React + Vite)          Backend (FastAPI + SQLAlchemy)
──────────────────────          ─────────────────────────────
ChatPage.tsx                     main.py (API routes + auth endpoints)
  ├── api.ts (HTTP client)         ├── auth.py (JWT auth, registration, login)
  ├── AuthModal.tsx (auth UI)      ├── bot_router.py (routes to correct bot)
  ├── JWT token (localStorage)     ├── agent.py (Sally's NEPQ orchestrator)
  ├── Visitor ID (localStorage)    │   ├── layers/comprehension.py (Layer 1: Gemini)
  └── Resume UI flow               │   ├── layers/decision.py (Layer 2: Python logic)
                                    │   └── layers/response.py (Layer 3: Claude)
                                    ├── bots/base.py (Hank/Ivy base class)
                                    │   ├── bots/hank.py (aggressive sales)
                                    │   └── bots/ivy.py (neutral info)
                                    ├── memory.py (extraction, storage, loading)
                                    ├── database.py (SQLAlchemy models + migrations)
                                    ├── quality_scorer.py (post-session scoring)
                                    └── sheets_logger.py (Google Sheets webhook)
```

### Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python, FastAPI, SQLAlchemy |
| Frontend | React, TypeScript, Vite, Tailwind CSS |
| Primary DB | PostgreSQL (Neon) |
| Sally Layer 1 (Comprehension) | Gemini 2.0 Flash |
| Sally Layer 3 (Response) | Claude Sonnet |
| Hank/Ivy | Claude Sonnet (single-prompt) |
| Memory Extraction | Gemini 2.0 Flash |
| Memory Greeting (Sally) | Claude Sonnet |
| Authentication | JWT (python-jose), bcrypt password hashing |
| Logging | Google Sheets (Apps Script webhook) |
| Payments | Stripe Checkout Sessions |
| Scheduling | TidyCal |
| Email Escalation | Gmail SMTP |
| Hosting | Railway (backend), Vercel (frontend) |

---

## Three-Layer NEPQ Engine (Sally)

Sally processes each conversation turn through three layers:

### Layer 1 — Comprehension (`layers/comprehension.py`)
- **Model:** Gemini 2.0 Flash
- **Purpose:** Analyze the user's message — detect intent, emotional tone, objections, extract profile updates, evaluate exit criteria for the current phase
- **Input:** Current phase, user message, conversation history, prospect profile, memory context
- **Output:** `ComprehensionOutput` — structured JSON with intent, emotional cues, profile updates, exit criteria evaluation

### Layer 2 — Decision (`layers/decision.py`)
- **Model:** None (pure Python logic)
- **Purpose:** Decide the next action based on Layer 1 output — advance phase, stay, probe deeper, handle objection, or end session
- **Input:** Comprehension output, profile, phase counters, conversation state
- **Output:** `DecisionOutput` — action (STAY/ADVANCE/PROBE/END), target phase, reasoning

### Layer 3 — Response (`layers/response.py`)
- **Model:** Claude Sonnet
- **Purpose:** Generate Sally's natural language reply based on the decision, emotional context, and conversation history
- **Input:** Decision output, conversation history, profile, emotional context, memory context
- **Output:** Response text string

### NEPQ Phases
```
CONNECTION → SITUATION → PROBLEM_AWARENESS → SOLUTION_AWARENESS → OWNERSHIP → COMMITMENT → TERMINATED
```

Each phase has defined exit criteria (in `phase_definitions.py`) that Layer 1 evaluates. Layer 2 advances the phase when criteria are met.

### Control Bots (Hank & Ivy)
- Single-prompt Claude calls via `bots/base.py`
- No phase gates, no structured sequencing
- Hank: aggressive sales (ROI framing, urgency, social proof, never gives up)
- Ivy: neutral information (pros/cons, risks, alternatives, never persuades)

---

## Persistent Memory System

### How It Works

```
Session Ends → Gemini extracts facts → Stored in DB
                                            ↓
New Session → Load facts → Seed profile + Personalized greeting
                                            ↓
Each Turn → Load facts → Format as prompt block → Inject into Layer 1 + Layer 3
```

### Components

#### Visitor Identity (`frontend/src/lib/api.ts`)
- `getOrCreateVisitorId()` — creates a UUID stored in `localStorage` under key `sally_visitor_id`
- Sent with every `POST /api/sessions` request
- Persists across page refreshes and browser closes

#### Session Resumption (`main.py`)
- `GET /api/visitors/{visitor_id}/active-session` — finds active or recently-abandoned sessions (within 24h)
- Abandoned sessions are reactivated on resume
- Completed sessions are NOT resumable
- Frontend shows "Continue Conversation" / "Start New" buttons when a resumable session exists

#### Memory Extraction (`memory.py: extract_memory_from_session`)
- Triggered asynchronously (daemon thread) when a session ends (completed or abandoned)
- Uses Gemini 2.0 Flash to extract structured JSON:
  - `identity` — name, role, company, industry
  - `situation` — team size, tools mentioned, workflow description
  - `pain_points` — list of specific pain points
  - `desired_state` — what they want to achieve
  - `objection_history` — objections raised during conversation
  - `emotional_signals` — notable emotional moments
  - `session_summary` — 2-3 sentence natural language summary
  - `conversation_outcome` — completed_paid, abandoned_early, hard_no, etc.

#### Memory Storage (`memory.py: store_memory`)
- **Facts** stored in `memory_facts` table — individual key-value pairs with categories
- **Summaries** stored in `session_summaries` table — per-session natural language summaries
- **Fact superseding** — newer facts for the same visitor + category + key deactivate older ones (`is_active = 0`)
- Thread-safe: uses `_get_session_local()` for independent DB session in daemon threads

#### Memory Loading (`memory.py: load_visitor_memory`)
- Loads all active facts organized by category
- Loads last 3 session summaries (most recent first)
- Returns structured dict with `has_memory: true/false`

#### Memory Formatting (`memory.py: format_memory_for_prompt`)
- Converts loaded memory into natural language block for prompt injection
- Includes identity, situation, pain points, objections, emotional signals, session summaries
- Ends with instruction: "Use this context naturally. Do NOT recite this information back robotically."

#### Memory Injection Points

| Location | How Memory Is Used |
|----------|-------------------|
| `main.py: create_session` | Loads memory → seeds prospect profile → generates personalized greeting |
| `main.py: send_message` | Loads memory → formats as prompt block → passes `memory_context` to `route_message()` |
| `layers/comprehension.py` | Memory block injected between profile and conversation sections. Instruction: treat memory facts as ALREADY KNOWN for exit criteria evaluation. |
| `layers/response.py` | Memory block injected before "WHAT WE KNOW" section. Instructions: reference naturally, don't recite robotically, never say "I remember from last time." |
| `bots/base.py` | Memory appended to system prompt for Hank/Ivy |

#### Personalized Greetings (`main.py: _generate_memory_greeting`)

| Bot | Greeting Method |
|-----|----------------|
| Sally | Claude API call with visitor context → generates 2-3 sentence warm greeting |
| Hank | Template: "Hey {name}! Great to see you back! ..." |
| Ivy | Template: "Hi {name}, welcome back. ..." |
| Fallback (Sally API failure) | Template: "Hey {name}! Welcome back — great to see you again." |

#### Privacy (`DELETE /api/visitors/{visitor_id}/memory`)
- Deletes all facts and summaries for a visitor
- Frontend `clearVisitorMemory()` also removes `localStorage` visitor ID
- Next visit creates a completely fresh identity

---

## User Authentication

### Three-Tier Identification

The system supports three tiers of user identification, each providing increasingly persistent memory:

| Tier | Method | Memory Scope | Cross-Device |
|------|--------|-------------|--------------|
| **Tier 1** | Email + password (JWT) | All sessions linked to account | Yes |
| **Tier 2** | Name + phone (soft match) | Creates lightweight user record | Partial (same name+phone) |
| **Tier 3** | Anonymous `localStorage` UUID | Single browser only | No |

### Backend Auth Module (`auth.py`)

| Function | Purpose |
|----------|---------|
| `hash_password(password)` | Bcrypt hash via `bcrypt` library |
| `verify_password(plain, hashed)` | Bcrypt verify |
| `create_token(user_id, email)` | JWT with 30-day expiry (`HS256`) |
| `decode_token(token)` | Decode + validate JWT, raises `HTTPException(401)` |
| `get_optional_user(authorization, db)` | FastAPI dependency — returns `DBUser` or `None` (never blocks) |
| `get_required_user(authorization, db)` | FastAPI dependency — returns `DBUser` or raises 401 |
| `register_user(db, email, password, ...)` | Create account, raises 409 on duplicate email |
| `login_user(db, email, password)` | Authenticate, raises 401 on failure |
| `merge_visitor_memory_to_user(db, visitor_id, user_id)` | Bulk UPDATE linking anonymous visitor data to authenticated user |
| `find_user_by_name_and_phone(db, name, phone)` | Normalized phone matching + case-insensitive name |

### Auth Flow

```
Anonymous User (Tier 3)
  └── Has visitor_id in localStorage
       ↓
Signs up or logs in (Tier 1)
  └── POST /api/auth/register  or  POST /api/auth/login
       ├── Creates/validates account
       ├── merge_visitor_memory_to_user() — links all prior sessions, facts, summaries
       ├── Returns JWT token
       └── Frontend stores token in localStorage (sally_auth_token)
            ↓
Subsequent Sessions
  └── Authorization: Bearer <token> sent with all API requests
       ├── create_session: user_id stored on session, memory loaded by user_id OR visitor_id
       ├── send_message: memory loaded by user_id OR visitor_id
       └── active-session: searches by user_id OR visitor_id
```

### Memory Merge on Authentication

When a user registers or logs in and passes their `visitor_id`, `merge_visitor_memory_to_user()` performs bulk UPDATEs:
- `sessions` — sets `user_id` on all sessions where `visitor_id` matches and `user_id IS NULL`
- `memory_facts` — same pattern
- `session_summaries` — same pattern

This ensures all prior anonymous activity is permanently linked to the account.

### OR-Based Memory Loading

After authentication, memory queries use `OR` conditions to load data from both the `visitor_id` and `user_id`:
- `memory.py: load_visitor_memory(db, visitor_id, user_id=...)` — queries facts/summaries where `visitor_id = X OR user_id = Y`
- `main.py: get_active_session` — searches for resumable sessions using `or_(*identity_conditions)`

This enables cross-device memory: logging in from a new browser immediately loads all prior conversation context.

### Frontend Auth (`api.ts` + `AuthModal.tsx`)

**Token management** in `api.ts`:
- `getAuthToken()` / `setAuthToken()` — read/write `sally_auth_token` in `localStorage`
- `clearAuth()` — removes token and user info from `localStorage`
- `isAuthenticated()` / `getSavedUserInfo()` — check auth state
- `authHeaders()` — returns `{ "Content-Type": "application/json", "Authorization": "Bearer <token>" }` if logged in

**AuthModal** (`components/chat/AuthModal.tsx`):
- Multi-mode modal: `choice` → `login` | `register` | `identify`
- Handles form validation, error display, loading states
- On success: stores token + user info in `localStorage`, calls `onComplete()`
- Skip option for anonymous usage

**ChatPage integration** (`pages/ChatPage.tsx`):
- Landing screen shows "Sign in for persistent memory →" link (unauthenticated) or green dot + signed-in name + sign out button (authenticated)
- Auth modal triggered from landing screen
- Auth state refreshes on modal completion

### Name + Phone Identification (Tier 2)

`POST /api/auth/identify` provides a lightweight identification path:
- If an existing user matches (case-insensitive name + normalized phone): returns `identified: true` with their `user_id` and merges visitor memory
- If no match: creates a lightweight user record (placeholder email, empty password hash) and returns `identified: false`
- Phone normalization strips `+`, `-`, `(`, `)`, spaces before comparing

---

## Database Schema

### Tables

#### `users`
Registered user accounts for persistent cross-device memory.

| Column | Type | Description |
|--------|------|-------------|
| `id` | String PK | UUID |
| `email` | String (unique, indexed) | Stored lowercase, trimmed |
| `password_hash` | String | Bcrypt hash (empty string for Tier 2 lightweight users) |
| `display_name` | String (nullable) | User's full name |
| `phone` | String (nullable, indexed) | Phone number for Tier 2 matching |
| `created_at` | Float | Unix timestamp |
| `last_login_at` | Float (nullable) | Unix timestamp of last login |
| `is_active` | Integer | 1 = active, 0 = deactivated (Integer for SQLite compat) |

#### `sessions`
Core session tracking. Key columns:

| Column | Type | Description |
|--------|------|-------------|
| `id` | String PK | 8-char uppercase UUID |
| `status` | String | active, completed, abandoned |
| `current_phase` | String | Current NEPQ phase or "CONVERSATION" |
| `assigned_arm` | String | sally_nepq, hank_hypes, ivy_informs |
| `visitor_id` | String (nullable, indexed) | Persistent visitor UUID |
| `user_id` | String (nullable, indexed) | Authenticated user FK (set on auth or merge) |
| `pre_conviction` | Integer | Pre-chat conviction score (1-10) |
| `post_conviction` | Integer | Post-chat conviction score |
| `cds_score` | Float | Conviction Delta Score |
| `prospect_profile` | Text (JSON) | Extracted prospect details |
| `thought_logs` | Text (JSON) | Sally's internal reasoning per turn |
| `message_count` | Integer | Total messages in session |
| `turn_number` | Integer | Current turn count |
| `start_time` / `end_time` | Float | Unix timestamps |
| `escalation_sent` | Float | Timestamp of escalation email |

Phase-tracking columns: `consecutive_no_new_info`, `turns_in_current_phase`, `deepest_emotional_depth`, `objection_diffusion_step`, `ownership_substep`

#### `messages`
| Column | Type | Description |
|--------|------|-------------|
| `id` | String PK | UUID |
| `session_id` | String (indexed) | FK to sessions |
| `role` | String | "user" or "assistant" |
| `content` | String | Message text |
| `timestamp` | Float | Unix timestamp |
| `phase` | String | Phase when message was sent |

#### `memory_facts`
| Column | Type | Description |
|--------|------|-------------|
| `id` | String PK | UUID |
| `visitor_id` | String (indexed) | Visitor UUID |
| `user_id` | String (nullable, indexed) | Authenticated user FK |
| `source_session_id` | String | Session that produced this fact |
| `category` | String | identity, situation, pain_point, objection_history, emotional_signal |
| `fact_key` | String | e.g., "name", "role", "pain_0" |
| `fact_value` | Text | The extracted value |
| `confidence` | Float | 1.0 default |
| `is_active` | Integer | 1 = active, 0 = superseded |
| `created_at` / `updated_at` | Float | Unix timestamps |

#### `session_summaries`
| Column | Type | Description |
|--------|------|-------------|
| `id` | String PK | UUID |
| `visitor_id` | String (indexed) | Visitor UUID |
| `user_id` | String (nullable, indexed) | Authenticated user FK |
| `session_id` | String | Source session |
| `summary_text` | Text | Natural language summary |
| `outcome` | String | completed, abandoned, hard_no, etc. |
| `final_phase` | String | Phase when session ended |
| `key_pain_points` | Text (JSON) | Array of pain points |
| `key_objections` | Text (JSON) | Array of objections |
| `created_at` | Float | Unix timestamp |

### Migrations
Handled in `database.py: init_db()`. New columns are added via `ALTER TABLE` with existence checks. New tables are created via `Base.metadata.create_all()`. Set `SKIP_SCHEMA_CHECK=true` in production to skip on every startup; unset temporarily when deploying schema changes.

Auth migration adds: `users` table, `user_id` column to `sessions`, `memory_facts`, and `session_summaries`, plus indexes on all `user_id` columns.

---

## API Endpoints

### Authentication
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/auth/register` | Register email/password account. Accepts optional `visitor_id` for memory merge. Returns JWT. |
| `POST` | `/api/auth/login` | Login with email/password. Accepts optional `visitor_id` for memory merge. Returns JWT. |
| `GET` | `/api/auth/me` | Get current user info. Requires `Authorization: Bearer <token>`. |
| `POST` | `/api/auth/identify` | Identify by name + phone (Tier 2). Creates lightweight user if no match found. |

### Session Management
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/sessions` | Create session (accepts `visitor_id`, `pre_conviction`, `selected_bot`). Optional `Authorization` header links session to user. |
| `POST` | `/api/sessions/{id}/messages` | Send message, get bot response |
| `POST` | `/api/sessions/{id}/end` | End/abandon session (triggers memory extraction) |
| `GET` | `/api/sessions/{id}` | Get session detail with messages + thought logs |
| `GET` | `/api/sessions` | List all sessions |

### Visitor & Memory
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/visitors/{id}/active-session` | Check for resumable session (active/abandoned <24h) |
| `GET` | `/api/visitors/{id}/memory` | Debug: view stored memory |
| `DELETE` | `/api/visitors/{id}/memory` | Privacy: delete all memory + summaries |

### Metrics & Export
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/metrics` | Aggregated metrics (total, active, completed, phase distribution) |
| `GET` | `/api/export/csv` | Download all sessions as CSV |
| `POST` | `/api/sessions/{id}/post-conviction` | Submit post-chat conviction score |
| `POST` | `/api/sessions/{id}/quality-score` | Run quality scoring on completed session |

### Payments & Config
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/checkout` | Create Stripe Checkout Session |
| `GET` | `/api/checkout/verify/{id}` | Verify payment status |
| `GET` | `/api/config` | Client-safe config (Stripe keys, TidyCal path) |

### Debug
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/sessions/{id}/thoughts` | View Sally's thought logs |

---

## Frontend Routes

| Route | Component | Description |
|-------|-----------|-------------|
| `/` | `ChatPage` | Main chat interface with bot selection, resume flow |
| `/dashboard` | `DashboardPage` | Metrics and session management |
| `/history` | `HistoryPage` | Session history with thought log viewer |
| `/booking/:sessionId` | `BookingPage` | Stripe payment return handler |

---

## Environment Variables

Required in `.env` at **project root** (not `backend/`):

### Core
| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string (Neon) |
| `ANTHROPIC_API_KEY` | Claude API key (Sally Layer 3, Hank, Ivy, memory greetings) |
| `GEMINI_API_KEY` | Gemini API key (Sally Layer 1, memory extraction) |
| `JWT_SECRET_KEY` | Secret key for signing JWT tokens (auth). Falls back to dev default if not set. |

### Integrations (Optional)
| Variable | Description |
|----------|-------------|
| `GOOGLE_SHEETS_WEBHOOK_URL` | Apps Script webhook for logging |
| `STRIPE_SECRET_KEY` | Stripe server-side key |
| `STRIPE_PUBLISHABLE_KEY` | Stripe client-side key |
| `STRIPE_PAYMENT_LINK` | Fallback payment link |
| `TIDYCAL_PATH` | TidyCal booking path |
| `FRONTEND_URL` | Frontend URL for Stripe redirects |
| `GMAIL_USER` | Gmail address for escalation emails |
| `GMAIL_APP_PASSWORD` | Gmail app password |
| `ESCALATION_EMAIL` | Email to receive hot lead alerts |
| `SKIP_SCHEMA_CHECK` | Set `true` to skip DB migrations on startup |

### Frontend
| Variable | Description |
|----------|-------------|
| `VITE_API_URL` | Backend API URL (defaults to `http://localhost:8000`) |

---

## Testing

```bash
cd backend
python -m pytest tests/ -v
```

### Test Files
| File | Tests | Coverage |
|------|-------|----------|
| `tests/test_auth.py` | 23 | Registration, login, JWT validation, session+auth, name+phone identification, memory merge, token edge cases |
| `tests/test_memory_phase_a.py` | 11 | Visitor ID, session resumption, backward compatibility |
| `tests/test_memory_phase_b.py` | 6 | Memory extraction, storage, fact superseding, prompt formatting |
| `tests/test_memory_phase_c.py` | 20 | Prompt injection (comprehension + response), profile seeding, greetings, memory loading in send_message |
| **Total** | **60** | |

Tests use SQLite in-memory databases and mock external API calls. The `reset_db` fixture overrides `db_module.DATABASE_URL` directly to prevent the `.env` `override=True` from routing tests to production PostgreSQL.

---

## Deployment Notes

### Running Locally
```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

### Production Schema Migration
When deploying schema changes, temporarily unset `SKIP_SCHEMA_CHECK` and redeploy. The `init_db()` function will:
1. Run `Base.metadata.create_all()` — creates any new tables (e.g., `users`, `memory_facts`, `session_summaries`)
2. Run column migrations — adds any new columns to existing tables (e.g., `user_id` on `sessions`, `memory_facts`, `session_summaries`)
3. Create indexes (including `user_id` indexes on all three tables)

After migration completes, re-enable `SKIP_SCHEMA_CHECK=true` for fast cold starts.

### Key `.env` Path Gotcha
The `.env` file lives at the **project root**, not in `backend/`. Different files need different directory traversal depths:
- `database.py` (in `app/`): `dirname` x3
- `layers/comprehension.py`, `layers/response.py` (in `app/layers/`): `parent` x4
- `sheets_logger.py` (in `app/`): `parent` x3
- `memory.py` (in `app/`): uses `os.getenv()` — `.env` loaded by `database.py` at import time

---

## File Index

### Backend (`backend/app/`)
| File | Purpose |
|------|---------|
| `main.py` | FastAPI app, all API routes (incl. auth endpoints), memory-aware session creation, greeting generation, profile seeding |
| `auth.py` | JWT authentication, password hashing (bcrypt), registration, login, memory merge, name+phone identification |
| `agent.py` | `SallyEngine` — orchestrates three-layer pipeline |
| `bot_router.py` | Routes messages to Sally/Hank/Ivy based on session arm |
| `database.py` | SQLAlchemy models (incl. DBUser), schema migrations, DB connection management |
| `schemas.py` | Pydantic request/response models (incl. auth schemas) |
| `models.py` | Internal data models (ComprehensionOutput, DecisionOutput, ProspectProfile, etc.) |
| `memory.py` | Memory extraction (Gemini), storage, loading, prompt formatting |
| `layers/comprehension.py` | Layer 1: Gemini-powered message analysis |
| `layers/decision.py` | Layer 2: Python logic for phase transitions |
| `layers/response.py` | Layer 3: Claude-powered response generation |
| `bots/base.py` | Base class for control bots (single-prompt Claude) |
| `bots/hank.py` | Hank — aggressive sales bot |
| `bots/ivy.py` | Ivy — neutral information bot |
| `phase_definitions.py` | NEPQ phase definitions and exit criteria |
| `playbooks.py` | Situation-specific response playbooks |
| `quality_scorer.py` | Post-session conversation quality scoring |
| `sheets_logger.py` | Google Sheets webhook logger |

### Frontend (`frontend/src/`)
| File | Purpose |
|------|---------|
| `lib/api.ts` | HTTP client, visitor identity, JWT token management, auth functions, session resumption, memory clear |
| `pages/ChatPage.tsx` | Main chat UI with bot selection, resume flow, and auth integration |
| `components/chat/AuthModal.tsx` | Multi-mode auth modal (login/register/identify) |
| `pages/DashboardPage.tsx` | Metrics dashboard |
| `pages/HistoryPage.tsx` | Session history viewer |
| `pages/BookingPage.tsx` | Stripe payment return handler |

### Tests (`backend/tests/`)
| File | Purpose |
|------|---------|
| `test_auth.py` | Registration, login, JWT, session+auth, name+phone ID, memory merge |
| `test_memory_phase_a.py` | Session resumption, visitor identity |
| `test_memory_phase_b.py` | Memory extraction and storage |
| `test_memory_phase_c.py` | Memory injection into prompts |
