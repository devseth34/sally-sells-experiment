# Project Changelog — Last 4 Weeks

**Period:** March 8, 2026 – April 4, 2026  
**Total Commits:** 25  

---

## Week 1: March 8 – March 8

### Saturday, March 8 — Persistent Memory & Authentication Foundation

**Commit `9e7ec31`** — *Added persistent memory and authentication features*

- **New file: `backend/app/memory.py`** — Full persistent memory system (530 lines) for storing and retrieving conversation context across sessions
- **New file: `backend/app/auth.py`** — Authentication module (219 lines) for user identity and session management
- **New file: `backend/app/database.py`** — Database layer (89 lines) with SQLAlchemy models and session storage
- **New file: `frontend/src/components/chat/AuthModal.tsx`** — Frontend authentication modal (238 lines) for user login/signup
- **New file: `TECHNICAL_DOCS.md`** — Technical documentation (531 lines)
- **Updated `backend/app/main.py`** — Major expansion (+560 lines) adding API endpoints for memory, auth, and session management
- **Updated `backend/app/schemas.py`** — New Pydantic schemas for auth and memory payloads
- **Updated `backend/app/layers/comprehension.py`**, **`decision.py`**, **`response.py`** — Integrated memory context into all three processing layers
- **Updated `backend/app/bot_router.py`** and **`backend/app/bots/base.py`** — Wired memory into bot routing
- **Updated `backend/app/playbooks.py`** — Added memory-aware playbook entries
- **Updated `frontend/src/lib/api.ts`** — Added API calls for auth and memory endpoints (+179 lines)
- **Updated `frontend/src/pages/ChatPage.tsx`** — Integrated auth flow and memory into chat UI
- **Updated `backend/requirements.txt`** — Added 2 new dependencies
- **New tests:**
  - `backend/tests/test_auth.py` (374 lines)
  - `backend/tests/test_memory_phase_a.py` (224 lines)
  - `backend/tests/test_memory_phase_b.py` (212 lines)
  - `backend/tests/test_memory_phase_c.py` (484 lines)
  - `backend/tests/test_relationship_memory.py` (708 lines)

> **Total: +4,611 lines across 23 files**

---

**Commit `64eccaa`** — *Improved Hank and Ivy's memory management and response generation*

- **Overhauled `backend/app/bots/hank.py`** — Enhanced Hank's response generation with better contextual awareness (+130 lines reworked)
- **Overhauled `backend/app/bots/ivy.py`** — Enhanced Ivy's response generation with improved memory utilization (+130 lines reworked)
- **Updated `backend/app/bots/base.py`** — Extended base bot class with improved memory integration (+108 lines)
- **Updated `backend/app/memory.py`** — Expanded memory module with additional retrieval methods (+93 lines)
- **Updated `backend/app/main.py`** — Extended API layer with new memory-related endpoints (+302 lines)
- **Updated `TECHNICAL_GUIDE.md`** — Documented memory architecture changes
- **Updated `frontend/src/pages/ChatPage.tsx`** — Minor UI adjustments for memory display
- **New test: `backend/tests/test_hank_ivy_enhanced.py`** (238 lines) — Tests for enhanced Hank & Ivy behavior
- **Expanded `backend/tests/test_relationship_memory.py`** (+740 lines) — Comprehensive relationship memory testing

> **Total: +1,654 lines across 10 files**

---

## Week 2: March 15 – March 21

### Saturday, March 15 — Twilio SMS Integration, Follow-Up Sequencing & Bot Switching

**Commit `9011463`** — *Added Twilio integration and Experiment Survey Modal*

- **New file: `backend/app/sms.py`** — Full Twilio SMS integration module (512 lines) for sending/receiving SMS messages
- **New file: `frontend/src/components/chat/ExperimentSurveyModal.tsx`** — Survey modal component (52 lines) displayed to experiment participants after conversation
- **New file: `frontend/src/pages/ExperimentPage.tsx`** — Dedicated experiment page (224 lines) for research participants
- **New file: `RECENT_UPDATES.md`** — Documentation of recent changes (251 lines)
- **Updated `backend/app/database.py`** — Added new table for storing survey results
- **Updated `backend/app/main.py`** — New API endpoints for survey submission (+92 lines)
- **Updated `backend/app/schemas.py`** — New schema for survey results
- **Updated `backend/requirements.txt`** — Added `python-multipart` dependency
- **Updated `frontend/src/App.tsx`** — Integrated new ExperimentSurveyModal component
- **Updated `frontend/src/components/chat/MessageBubble.tsx`** — Adjusted message rendering for experiment mode
- **Updated `frontend/src/lib/api.ts`** — New API endpoint for survey submission (+46 lines)

> **Total: +1,200 lines across 11 files**

---

**Commit `03f9c2a`** — *Added follow-up sequencing and survey modal*

- **New file: `backend/app/followup.py`** — Follow-up sequencing engine (421 lines) to manage timed follow-up messages after initial conversation
- **Updated `backend/app/database.py`** — Added follow-up tracking tables (+8 lines)
- **Updated `backend/app/main.py`** — New endpoints for follow-up scheduling (+16 lines)
- **Updated `backend/app/sms.py`** — Refactored SMS module for follow-up support (84 lines changed)
- **Updated `backend/requirements.txt`** — Dependency adjustment

> **Total: +491 lines across 5 files**

---

**Commit `e7ba2d9`** — *Added bot switching to follow-up and comprehensive tests*

- **New file: `frontend/src/components/chat/BotSwitcher.tsx`** — Bot switcher UI component (49 lines) for switching between Sally, Hank, and Ivy mid-conversation
- **New file: `backend/tests/test_bot_switch.py`** — Bot switching test suite (684 lines)
- **New file: `backend/tests/test_sms_integration.py`** — SMS integration test suite (552 lines)
- **New file: `backend/tests/BOT_SWITCH_TEST_REPORT.md`** — Bot switch testing report (83 lines)
- **New file: `backend/tests/SMS_TEST_REPORT.md`** — SMS testing report (60 lines)
- **Updated `backend/app/main.py`** — Bot switching API endpoints (+184 lines)
- **Updated `backend/app/sms.py`** — SMS bot switching support (+153 lines)
- **Updated `frontend/src/lib/api.ts`** — Bot switch API calls (+21 lines)
- **Updated `frontend/src/pages/ChatPage.tsx`** — Integrated BotSwitcher component (+74 lines)
- **Updated `frontend/src/pages/ExperimentPage.tsx`** — Experiment page bot switching support (+84 lines)

> **Total: +1,938 lines across 10 files**

---

### Tuesday, March 18 — Latency Fixes & Twilio Bug Fixes

**Commit `1a87097`** — *Fixed latency and other issues*

- **Updated `backend/app/agent.py`** — Optimized agent processing for lower latency (+75 lines)
- **Updated `backend/app/layers/comprehension.py`** — Layer 1 latency tweaks
- **Updated `backend/app/layers/response.py`** — Response generation optimization (+11 lines)
- **Updated `backend/app/main.py`** — API-level latency improvements (+39 lines)
- **Updated `backend/app/sms.py`** — SMS latency reduction (+47 lines)

> **Total: +154 lines across 5 files**

---

**Commit `d715958`** — *Fixed Twilio issue*

- **Overhauled `backend/app/sms.py`** — Major Twilio SMS refactor (357 insertions, 215 deletions) fixing message delivery, webhook handling, and connection reliability

> **Total: +357 / -215 lines in 1 file**

---

**Commit `bf4d234`** — *Minor SMS fixes — message formatting and error handling*

- **Updated `backend/app/followup.py`** — Enhanced follow-up message formatting and error handling (+15 lines)
- **Updated `backend/app/main.py`** — Additional error handling for SMS endpoints (+21 lines)

> **Total: +36 lines across 2 files**

---

### Wednesday, March 19 — Dashboard & History Pages

**Commit `3d2367d`** — *Added robust dashboard and history*

- **Overhauled `frontend/src/pages/DashboardPage.tsx`** — Full dashboard rebuild with session analytics, charts, and metrics (+176 lines)
- **Overhauled `frontend/src/pages/HistoryPage.tsx`** — Complete history page with filterable conversation history (+215 lines reworked)
- **Updated `backend/app/main.py`** — New API endpoints for dashboard data and history queries (+164 lines)
- **Updated `backend/app/schemas.py`** — New schemas for dashboard analytics (+5 lines)
- **Updated `frontend/src/lib/api.ts`** — Dashboard and history API integration (+68 lines)
- **Updated `frontend/package.json`** — Added new charting dependency
- **Updated `frontend/package-lock.json`** — Lock file updated (+402 lines)

> **Total: +965 lines across 8 files**

---

### Thursday, March 20 — Major Reframe: Mortgage AI Academy, Invitation Links, Admin Dashboard & CDS Gating

**Commit `25729cf`** — *Add invitation link CTA, admin dashboard, SMS bug fixes, and circuit breaker fix*

- **New file: `backend/app/invitation.py`** — Invitation URL utility (37 lines) with UTM tracking parameters
- **New file: `frontend/src/pages/AdminPage.tsx`** — Admin dashboard (full build) with Recharts integration: CDS bar charts, session funnel, phase distribution, and recent sessions table
- Added `[INVITATION_LINK]` placeholder support for all three bots (Sally, Hank, Ivy)
- Track `invitation_link_sent` + `invitation_link_sent_at` on sessions table with DB migrations
- Added `GET /api/admin/analytics` endpoint with per-arm CDS stats, Go/Iterate/Kill status, funnel metrics, and recent sessions
- **Bug fix:** Circuit breaker was blocking Sally's self-introduction when user asks identity questions
- **Bug fix:** SMS sessions not setting `visitor_id` (now deterministic from phone number)
- **Bug fix:** Bot switch not carrying conversation context to Sally (`_switch_context` injection)
- Generate contextual Sally greeting on switch instead of hardcoded fallback
- Added post-conviction question to final (3rd) SMS follow-up for CDS capture
- **Performance:** Reduced Layer 1 `max_output_tokens` from 1500 to 800 for SMS latency improvement
- **Performance:** Added trivial message fast-path to skip Layer 1 for greetings/simple replies
- Files changed: `bot_router.py`, `bots/base.py`, `bots/hank.py`, `bots/ivy.py`, `database.py`, `followup.py`, `invitation.py`, `layers/response.py`, `main.py`, `schemas.py`, `sms.py`, `AdminPage.tsx`, `api.ts`, `ChatPage.tsx`

> **Total: Large multi-file commit across 14+ files**

---

**Commit `1d91570`** — *Make [INVITATION_LINK] the primary CTA across all three bots*

- **Updated `backend/app/bots/hank.py`** — Hank's CLOSING section now uses `[INVITATION_LINK]` as primary CTA
- **Updated `backend/app/bots/ivy.py`** — Ivy's PHASE 3 now uses `[INVITATION_LINK]` as primary CTA
- **Updated `backend/app/layers/response.py`** — Sally's COMMITMENT phase updated; payment/free workshop links now only used when prospect explicitly requests them

> **Total: +32 / -29 lines across 3 files**

---

**Commit `a84eb7f`** — *Reframe all bots from workshop sales to mortgage AI Academy*

- **Major rewrite across 13 files** shifting from selling a $10K workshop to helping mortgage professionals explore AI through the 100x AI Academy invitation page
- Single CTA: `[INVITATION_LINK]` only (free form, no paywall)
- Removed all Stripe/TidyCal/payment references from prompts
- Removed email/phone collection prompts (landing page handles it)
- Reframed all conversations for mortgage industry AI adoption
- **Sally-specific:** Simplified COMMITMENT phase, removed ~100 lines of contact collection branching, updated OWNERSHIP to present "opportunity" not "offer", updated circuit breaker, playbooks, and phase definitions
- Renamed `price_stated` → `opportunity_presented` criterion
- Updated SMS pre/post survey questions for mortgage framing
- Files changed: `agent.py`, `bots/base.py`, `bots/hank.py`, `bots/ivy.py`, `followup.py`, `invitation.py`, `layers/comprehension.py`, `layers/decision.py`, `layers/response.py`, `main.py`, `phase_definitions.py`, `playbooks.py`, `sms.py`

> **Total: +268 / -461 lines across 13 files**

---

**Commit `8bd65ac`** — *Rename price_stated variable to opp_presented in agent.py*

- Follow-up fix: renamed local variable `price_stated` to match the updated dict key `opportunity_presented`

> **Total: +2 / -2 lines in 1 file**

---

**Commit `ab3e8e7`** — *Render invitation link as purple button in chat*

- **Updated `frontend/src/components/chat/MessageBubble.tsx`** — Added 100x.inc/academy URL detection to `renderWithLinks` so the invitation link displays as a styled "Request Your Invitation" purple button instead of a raw URL

> **Total: +15 lines in 1 file**

---

**Commit `7ec3cf8`** — *Gate invitation link behind CDS rating on web and SMS*

- **Web:** Clicking the invitation button now triggers a CDS rating modal (1-10 scale) before opening the link
- **SMS:** New `rating_before_link` state strips the invitation URL from the bot message, asks for a 1-10 rating, then sends CDS + invitation link
- **Database:** Added `pending_invitation_url` column to store gated URLs
- Files changed: `database.py`, `sms.py`, `MessageBubble.tsx`, `PostConvictionModal.tsx`, `ChatPage.tsx`

> **Total: +176 / -257 lines across 5 files**

---

**Commit `72e9fd9`** — *Fix: add hidePhase prop to MessageBubble*

- Added `hidePhase` prop to `MessageBubble` component used by `ExperimentPage` to hide phase indicators from experiment participants

> **Total: +13 / -10 lines in 1 file**

---

**Commit `e5c31cf`** — *Update pre-chat survey question to match mortgage AI framing*

- **Updated `frontend/src/components/chat/ConvictionModal.tsx`** — Changed pre-chat survey question from $10K investment framing to mortgage AI interest framing

> **Total: +2 / -2 lines in 1 file**

---

**Commit `3a59c85`** — *Add name/email collection, fix CDS question mismatch, add CSV download to admin*

- **Pre-survey now collects participant name and email** before starting the conversation
- **Fixed CDS calculation accuracy:** Aligned pre and post survey questions (both now ask about mortgage AI interest instead of pre asking about $10K investment)
- **Admin dashboard:** Now shows name/email in sessions table and has a CSV download button
- **CSV export** includes participant info, arm, channel, and invitation link status
- Files changed: `database.py`, `main.py`, `schemas.py`, `ExperimentSurveyModal.tsx`, `api.ts`, `AdminPage.tsx`, `ExperimentPage.tsx`

> **Total: +92 / -15 lines across 7 files**

---

### Friday–Saturday, March 21 — Prolific/MTurk Integration & SPA Routing

**Commit `c66801a`** — *Add Prolific/MTurk completion code flow and platform tracking*

- Participants arriving via `?platform=prolific&pid=XXXXX` (or `mturk`) now have their platform and participant ID stored on the session
- After the CDS rating modal, a completion code screen shows the session ID as a copyable code for participants to paste back into Prolific/MTurk
- CSV export and admin dashboard updated with platform fields
- Files changed: `database.py`, `main.py`, `schemas.py`, `api.ts`, `ExperimentPage.tsx`

> **Total: +69 lines across 5 files**

---

**Commit `538a9b2`** — *Add vercel.json rewrite for SPA client-side routing*

- **New file: `frontend/vercel.json`** — Rewrites all paths to `index.html` so React Router handles client-side routing (fixes 404 on direct navigation to `/experiment`)

> **Total: +5 lines in 1 file**

---

**Commit `bc0763a`** — *Fix experiment page: gate invitation link behind CDS rating modal*

- The experiment page was using a direct `<a>` tag for the invitation button, bypassing the rating flow
- Now passes `onInvitationClick` handler to `MessageBubble` so clicking the button triggers the post-conviction modal first

> **Total: +13 lines in 1 file**

---

## Week 3: March 29 — Prolific Improvements, Report Generation & Smoke Tests

### Saturday, March 29

**Commit `001392f`** — *Improvements based on Prolific output*

- **Balanced arm allocation:** Replaced random bot assignment with balanced allocation (assigns to the arm with fewest experiment sessions)
- **Auto-timeout:** Sessions auto-end after 48 hours of inactivity (status set to `abandoned`)
- **Improved conversation transcripts:** Bot name now correctly appears in transcripts instead of always "Sally"
- **Claude API message formatting fix:** Fixed leading assistant messages causing API errors — leading assistant messages are now folded into the system prompt as prior context
- **Added synthetic user turn safety net** when messages array is empty or starts with wrong role
- **Added message deduplication:** Consecutive same-role messages are merged to prevent Claude API errors
- **Enhanced end-detection for control bots:** Added explicit exit phrase detection (`goodbye`, `bye`, `done`, `quit`, `exit`, etc.) in addition to safety cap
- **Improved error logging** with `exc_info=True` and message payload details
- **New test: `backend/tests/test_control_bots.py`** (139 lines) — Tests for control bot behavior
- Files changed: `RECENT_UPDATES.md`, `bots/base.py`, `bots/hank.py`, `main.py`, `test_control_bots.py`, `api.ts`, `ExperimentPage.tsx`

> **Total: +440 lines across 7 files**

---

**Commit `e362c84`** — *Smoke test before deployment and quick fixes*

- **New file: `backend/tests/smoke_test.py`** — Comprehensive pre-deployment smoke test suite (354 lines) covering critical API paths and functionality

> **Total: +354 lines in 1 file**

---

**Commit `53a0883`** — *Improved report generation and added new report generator module*

- **New file: `backend/app/report_generator.py`** — Full report generation module (477 lines) for generating experiment reports with CDS analysis, per-arm breakdowns, and session statistics
- **Updated `backend/app/main.py`** — Major API expansion for report generation endpoints (+220 lines)
- **Updated `backend/app/bot_router.py`** — Bot router enhancements
- **Updated `backend/app/bots/base.py`** — Bot base class additions
- **Updated `backend/app/invitation.py`** — Invitation management improvements
- **Updated `frontend/src/lib/api.ts`** — Report generation API integration (+42 lines)
- **Updated `frontend/src/pages/AdminPage.tsx`** — Admin page report generation UI (+120 lines)
- **Updated `frontend/src/pages/ChatPage.tsx`** — Minor chat page adjustments
- **Updated `frontend/src/pages/ExperimentPage.tsx`** — Minor experiment page adjustments
- **Added `backend/requirements.txt`** — New dependency for report generation

> **Total: +859 lines across 10 files**

---

**Commit `c564f80`** — *Report generation refinements and tests*

- **Updated `backend/app/report_generator.py`** — Refined report generation logic (+28 / -11 lines)
- **New file: `backend/tests/test_report_generator.py`** — Report generator test suite (151 lines)

> **Total: +168 lines across 2 files**

---

## Week 4: April 3 – April 4 — Hybrid Arms, Persona Configuration & Legitimacy Scoring

### Thursday, April 3

**Commit `03a5eb7`** — *Added persona configuration and hybrid arms*

- **New file: `backend/app/persona_config.py`** — Persona configuration module (220 lines) defining hybrid bot arms with NEPQ phase-to-persona prompt overrides:
  - **Arm 4: Sally > Hank Close** — Sally's empathetic NEPQ through CONSEQUENCE, then direct urgency-driven closing for OWNERSHIP + COMMITMENT
  - **Arm 5: Sally > Ivy Bridge** — Sally through CONSEQUENCE, then Ivy's educational/informational style for OWNERSHIP + COMMITMENT
  - **Arm 6: Sally Empathy+** — Amplified empathetic persona throughout all phases
  - **Arm 7: Sally Direct** — More assertive, direct sales style throughout
  - **Arm 8: Hank Structured** — Hank's style running through Sally's 3-layer engine with structured phases
  - Defined `SALLY_ENGINE_ARMS` frozenset for routing decisions
- **New file: `backend/tests/test_hybrid_arms.py`** (228 lines) — Hybrid arms unit tests
- **New file: `backend/tests/test_hybrid_integration.sh`** (792 lines) — Comprehensive hybrid integration test script
- **Updated `backend/app/agent.py`** — Agent routing for hybrid arms
- **Updated `backend/app/bot_router.py`** — Extended bot router with hybrid arm support (+22 lines)
- **Updated `backend/app/followup.py`** — Follow-up logic for hybrid arms
- **Updated `backend/app/layers/response.py`** — Layer 3 persona override injection
- **Updated `backend/app/main.py`** — Hybrid arm session creation and routing (+63 lines)
- **Updated `backend/app/memory.py`** — Memory adjustments for hybrid arms
- **Updated `backend/app/models.py`** — New model field for hybrid arm tracking
- **Updated `backend/app/report_generator.py`** — Report generation for hybrid arms
- **Updated `backend/app/schemas.py`** — New schemas for hybrid arm data (+5 lines)
- **Updated `backend/app/sms.py`** — SMS support for hybrid arms
- **Frontend updates:**
  - `BotSwitcher.tsx` — Added hybrid arm options
  - `ConvictionModal.tsx` — Updated for hybrid arms (+25 lines)
  - `api.ts` — Hybrid arm API integration
  - `AdminPage.tsx` — Hybrid arm analytics display (+15 lines)
  - `ChatPage.tsx` — Hybrid arm selection
  - `DashboardPage.tsx` — Hybrid arm dashboard metrics (+5 lines)
  - `ExperimentPage.tsx` — Hybrid arm experiment flow (-81 lines refactored, +81 lines)
  - `HistoryPage.tsx` — Hybrid arm history display (+15 lines)

> **Total: +1,430 lines across 22 files**

---

### Friday, April 4

**Commit `d15123b`** — *Improved agent behavior, persona configuration, and enhanced testing for hybrid arms*

- **New file: `backend/app/legitimacy_scorer.py`** — Session Legitimacy Score (SLS) module (204 lines):
  - Scores sessions 0-100 based on raw message data (no LLM calls)
  - Signals: total user words (0-35 pts), substantive message ratio (0-25 pts), longest single message (0-20 pts), topic relevance (0-15 pts), duplicate content flag (auto-zero)
  - Tiers: Verified (70-100), Marginal (40-69), Suspect (0-39)
  - Mortgage/business keyword detection for topic relevance
  - Off-topic signal detection (Prolific/MTurk gaming phrases)
  - Duplicate session detection via content hashing
- **Updated `backend/app/database.py`** — New columns for legitimacy scoring (+8 lines)
- **Updated `backend/app/layers/comprehension.py`** — Layer 1 adjustment
- **Updated `backend/app/layers/decision.py`** — Layer 2 adjustment
- **Updated `backend/app/main.py`** — Legitimacy scoring API integration, legitimacy computation on session end (+66 lines)
- **Updated `backend/app/phase_definitions.py`** — Phase definition refinements
- **Updated `backend/app/schemas.py`** — Legitimacy score schemas (+3 lines)
- **Updated `backend/app/sms.py`** — SMS legitimacy scoring integration (+14 lines)
- **Frontend updates:**
  - `MessageBubble.tsx` — Display adjustments (+10 lines)
  - `api.ts` — Legitimacy score API calls (+3 lines)
  - `AdminPage.tsx` — Legitimacy score display in admin dashboard (+45 lines)
  - `ExperimentPage.tsx` — Minor experiment page updates (+3 lines)

> **Total: +365 lines across 12 files**

---

## Summary of Major Features Added (4 Weeks)

| Feature | Week | Key Files |
|---------|------|-----------|
| **Persistent Memory System** | Week 1 | `memory.py`, `database.py`, all layers |
| **Authentication System** | Week 1 | `auth.py`, `AuthModal.tsx` |
| **Hank & Ivy Memory Enhancement** | Week 1 | `bots/hank.py`, `bots/ivy.py`, `bots/base.py` |
| **Twilio SMS Integration** | Week 2 | `sms.py`, `followup.py` |
| **Follow-Up Sequencing** | Week 2 | `followup.py` |
| **Bot Switching (mid-conversation)** | Week 2 | `BotSwitcher.tsx`, `main.py`, `sms.py` |
| **Experiment Survey Modal** | Week 2 | `ExperimentSurveyModal.tsx`, `ExperimentPage.tsx` |
| **Dashboard & History Pages** | Week 2 | `DashboardPage.tsx`, `HistoryPage.tsx` |
| **Invitation Link CTA System** | Week 2 | `invitation.py`, all bots |
| **Mortgage AI Academy Reframe** | Week 2 | 13 files — full bot rewrite |
| **CDS Rating Gating** | Week 2 | `PostConvictionModal.tsx`, `sms.py` |
| **Admin Dashboard with Recharts** | Week 2 | `AdminPage.tsx` |
| **Prolific/MTurk Integration** | Week 2 | `ExperimentPage.tsx`, `database.py` |
| **SPA Client-Side Routing** | Week 2 | `vercel.json` |
| **Name/Email Collection** | Week 2 | `ExperimentSurveyModal.tsx`, `database.py` |
| **CSV Export** | Week 2 | `AdminPage.tsx`, `main.py` |
| **Balanced Arm Allocation** | Week 3 | `main.py` |
| **Session Auto-Timeout (48h)** | Week 3 | `main.py` |
| **Claude API Message Formatting Fix** | Week 3 | `bots/base.py` |
| **Report Generation Module** | Week 3 | `report_generator.py` |
| **Pre-Deployment Smoke Tests** | Week 3 | `smoke_test.py` |
| **Hybrid Arms (5 new arms)** | Week 4 | `persona_config.py`, 22 files |
| **Session Legitimacy Scorer** | Week 4 | `legitimacy_scorer.py` |

### Cumulative Stats
- **~15,000+ lines added** across the 4 weeks
- **13 new backend modules/files** created
- **5 new frontend components/pages** created
- **10 new test files** created
- **8 new experiment arms** supported (3 original + 5 hybrid)
