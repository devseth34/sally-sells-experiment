# Recent Updates — Memory Deployment (Short-term & Long-term)

Date: 2026-03-13

Summary
-------
This document describes the recent changes for session memory now deployed in the codebase: both short-term, in-session memory and long-term persistent memory extraction/storage. It explains where memory is produced and consumed, database changes and migrations, how to run and test the pipeline locally, and common troubleshooting steps.

Highlights
----------
- Short-term memory: `sessions.prospect_profile` (JSON) is seeded and updated during the conversation (Sally only). This acts as in-session structured memory used by the three-layer engine.
- Long-term memory: structured facts and session summaries are extracted after session completion and persisted in `memory_facts` and `session_summaries` tables (`DBMemoryFact`, `DBSessionSummary`).
- Memory extraction uses Google Gemini (`gemini-2.0-flash`) with a strict extraction prompt. Extraction is async and runs after session end in a background thread.
- Memory is read at session creation and message processing to produce personalized greetings and to inject relationship context into Layer 3 prompts.

Files & Key Functions
---------------------
- `backend/app/memory.py`
  - `extract_memory_from_session(session_id, visitor_id, transcript, profile_json, outcome, final_phase, bot_arm)`
    - Calls Gemini to extract structured JSON facts and a session summary.
  - `store_memory(db_session_maker, session_id, visitor_id, extraction, user_id=None, bot_arm="unknown")`
    - Writes facts into `memory_facts` (deactivates superseded facts) and adds a `session_summaries` record.
  - `load_visitor_memory(db, visitor_id, user_id=None)` → returns a rich dict ready for use by the engine.
  - `format_memory_for_prompt(memory)` → formats loaded memory as human-sounding text for prompt injection.
  - `load_recent_conversation_context(db, visitor_id, user_id=None)` → formatted last conversation transcript for greeting fallback.

- `backend/app/database.py`
  - New schema objects: `DBMemoryFact`, `DBSessionSummary`.
  - `init_db()` applies migrations to add `visitor_id`, `assigned_arm`, `user_id` columns to sessions and adds indexes. Migration logic is implemented to be safe for production.

- `backend/app/main.py`
  - On session creation: `load_visitor_memory()` and `load_recent_conversation_context()` are used to seed `sessions.prospect_profile` and to generate personalized greetings via `format_memory_for_prompt()`.
  - After session ends: `extract_memory_from_session()` and `store_memory()` are invoked in a background thread (daemon) to produce and persist long-term memory.
  - When a visitor signs up or logs in, `merge_visitor_memory_to_user()` links existing visitor facts and summaries to the new `user_id`.

Where short-term vs long-term memory lives
-----------------------------------------
- Short-term (session-scoped):
  - `sessions.prospect_profile` (Text column) — JSON-serialized `ProspectProfile` that the Sally engine updates each turn.
  - `sessions.thought_logs` — per-turn Sally internal logs (diagnostics), also used by quality scoring.

- Long-term (persistent):
  - `memory_facts` table (`DBMemoryFact`): individual facts, categorized (identity, situation, pain_point, relationship, emotional_peak, strategy, etc.). Facts have `is_active` flags and `user_id`/`visitor_id` linking.
  - `session_summaries` table (`DBSessionSummary`): per-session human-readable summaries, outcome, final phase, key pain points and key objections.

Data flow (end-to-end)
----------------------
1. Conversation runs (user ↔ bot). Sally updates `db_session.prospect_profile` each turn using Layer 1 output.
2. When the session is completed or abandoned and if `visitor_id` or `user_id` exists, `main.py` launches a thread:
   - Snapshot the transcript + profile and call `extract_memory_from_session()`.
   - `extract_memory_from_session()` formats the transcript and runs Gemini to return a strict JSON extraction.
   - `store_memory()` writes facts to `memory_facts` (deactivating same-key old facts) and inserts a `session_summaries` row.
3. On subsequent sessions or during session creation, `load_visitor_memory()` reads active facts + recent session summaries and returns a structured dict used to seed the `prospect_profile` and feed greeting/context generation.
4. `format_memory_for_prompt()` turns the structured memory into a short natural-language block that's injected into LLM prompts (Sally greeting & Layer 3 input). This function is deliberately formatted to make Sally sound like a friend who already knows the prospect.

Important implementation notes
------------------------------
- Extraction prompt: the Gemini prompt requires exact JSON output and includes an instruction to "Return ONLY the JSON. No markdown, no explanation." The code attempts to strip backticks and fences before parsing.
- Conflict resolution: when storing facts, the code deactivates any existing `DBMemoryFact` for the same visitor + category + key, and inserts the new fact with `is_active=1`.
- Facts granularization: some multi-item fields (e.g., `pain_points`, `tools_mentioned`) are stored as separate facts for easier querying and deactivation per-item.
- Cross-device linking: `store_memory()` can optionally attach `user_id` to facts/summaries. `merge_visitor_memory_to_user()` updates records from visitor->user when an anonymous visitor authenticates.
- Token budget: `load_recent_conversation_context()` limits the returned messages to the last 20 messages to keep prompts compact.

DB / Migration notes
--------------------
- `init_db()` (in `database.py`) will:
  - `create_all()` for new tables (memory_facts, session_summaries) if missing.
  - Add columns to `sessions` table if missing: `consecutive_no_new_info`, `turns_in_current_phase`, `deepest_emotional_depth`, `objection_diffusion_step`, `ownership_substep`, `assigned_arm`, `visitor_id`, `user_id`.
  - Add `user_id` column to `memory_facts` and `session_summaries` if missing.
- Production tip: set `SKIP_SCHEMA_CHECK=true` in production to skip these checks on cold start. If you change memory schema, temporarily unset this to apply migrations.

Environment variables (memory-specific)
---------------------------------------
- `GEMINI_API_KEY` — required for `extract_memory_from_session()` (Google Generative AI gemini-2.0-flash). If missing, `extract_memory_from_session()` raises a runtime error.
- `DATABASE_URL` — required for DB access.
- `ANTHROPIC_API_KEY` still required for Claude-based components (Layer 3, quality scorer, control bots), but memory extraction is Gemini.

How to run & test the memory pipeline locally
---------------------------------------------
1. Ensure venv is active and backend deps are installed (project root):

```bash
source venv/bin/activate
pip install -r backend/requirements.txt
```

2. Ensure `.env` contains at least:

```
DATABASE_URL=postgresql://...
GEMINI_API_KEY=ya29....
ANTHROPIC_API_KEY=sk-...
JWT_SECRET_KEY=...    # for auth flows if you use logged-in flows
```

3. Start the backend:

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

4. Create a session and run through a short conversation using the API (or the frontend). When you end the session (POST `/api/sessions/{id}/end`), the memory extraction thread will fire.

Example: quick manual test using `curl` (replace values):

```bash
# 1) Create session (POST /api/sessions) — send JSON body with pre_conviction
curl -s -X POST http://localhost:8000/api/sessions -H 'Content-Type: application/json' -d '{"pre_conviction":5}' | jq

# 2) Send a user message
curl -s -X POST http://localhost:8000/api/sessions/SESSION_ID/messages -H 'Content-Type: application/json' -d '{"content":"Hey, I'm Alex, we use HubSpot and are drowning in manual follow-ups."}' | jq

# 3) End the session (trigger extraction)
curl -s -X POST http://localhost:8000/api/sessions/SESSION_ID/end | jq
```

5. Check DB for new facts and summaries in `memory_facts` and `session_summaries` tables, or call the debug endpoint `GET /api/sessions/{id}` to see `prospect_profile` and `thought_logs`.

Manual/Ad-hoc extraction
------------------------
You can run extraction against existing transcripts to debug the Gemini prompt locally in a Python REPL in the project venv:

```bash
source venv/bin/activate
python -c "from app.memory import extract_memory_from_session; import json; print(json.dumps(extract_memory_from_session('sess123','visitor123',[{'role':'user','content':'I am Alex, I run sales at a 12-person fintech.'}], '{}','completed','COMMITMENT'), indent=2))"
```

(Construct a transcript list matching the expected input format.)

Troubleshooting & common failure modes
-------------------------------------
- Gemini errors or empty response:
  - Check `GEMINI_API_KEY` is set and valid.
  - The extraction code strips triple-backtick fences and tries to JSON-parse the model output — if the model returns explanatory text or markdown, parsing will fail and the extraction returns `{}`.
  - Recommendation: inspect raw `response.text` by temporarily adding debug logging inside `extract_memory_from_session()`.

- JSON parse errors from the model output:
  - The extraction prompt asks for strict JSON. If parsing fails frequently, lower `max_output_tokens` or make the prompt even more explicit (or run a local test to see exact model output and then adapt the parser to relax certain common wrappers).

- Conflicting facts or outdated info:
  - `store_memory()` supersedes earlier facts by deactivating previous `DBMemoryFact` rows with the same `category`+`fact_key` for the same visitor. Multi-item facts (pain points) are stored as separate keys so individual items can be updated independently.

- Missing visitor identifier:
  - If the conversation didn't set `visitor_id` (visitor tracking cookie) or the user did not authenticate, long-term memory cannot link to the visitor. Consider instrumenting the frontend to always include a `visitor_id` when creating a session.

- DB schema/migration problems:
  - If you added memory tables but `init_db()` isn't running (because `SKIP_SCHEMA_CHECK=true`), run the one-off migration locally: `python -c "from app.database import init_db; init_db()"` with `SKIP_SCHEMA_CHECK` unset.

Integration points to watch
---------------------------
- Greeting generation: `main.py::_generate_memory_greeting()` calls `format_memory_for_prompt()` and may call Claude to produce a relationship-aware greeting. Verify that memory formatting content is suitable for the Claude prompts (short and human sounding).
- Session creation: `create_session()` tries to fallback to prior session's `prospect_profile` and `load_recent_conversation_context()` when structured memory isn't yet available. This addresses the race condition between session end memory extraction and a new session starting.
- Merge on auth: `auth.merge_visitor_memory_to_user()` updates `sessions`, `memory_facts`, and `session_summaries` rows when a visitor becomes a registered `user_id`.

Recommended next improvements
-----------------------------
- Add a small logging addition in `extract_memory_from_session()` to persist the raw model output when parse fails (store into a `memory_extraction_raw` table or attach to `session_summaries` as a debug field). This speeds debugging when the model returns non-JSON wrappers.
- Implement a light validation layer that checks extracted JSON fields for obvious inconsistencies before writing (e.g., extremely long `name` fields or numerics in string fields).
- Add a background job/retry queue for memory extraction so that if Gemini fails transiently (rate limits), you can retry later instead of dropping the extraction.
- Expose a debug endpoint to re-run extraction for a given session id (this already exists as the ad-hoc `POST /api/sessions/{id}/quality-score` pattern — a similar endpoint for re-extraction would be useful).

Files changed / new
-------------------
- `backend/app/memory.py` — new/expanded extraction, store, load, format utilities (core of long-term memory).
- `backend/app/database.py` — new tables `memory_facts`, `session_summaries`, migration additions for `visitor_id`, `user_id`, `assigned_arm`, and other session fields.
- `backend/app/main.py` — integration points: seeds memory on session creation, triggers extraction & store on session end, uses `load_recent_conversation_context()` for greeting fallback, and merges memory on register/login.

If you want I can also:
- Add a short section to `TECHNICAL_GUIDE.md` summarizing these updates in place (so the canonical guide contains the memory section), or
- Add a small `scripts/` helper to re-run extraction for a session id and write raw model outputs into a debug table for analysis.

Would you like me to add an extraction re-run endpoint / script, or to update `TECHNICAL_GUIDE.md` with a memory section now? If yes, tell me which and I will implement it next.

Recent dependency & auth fixes
------------------------------
Since initial deployment we made a couple of small but important fixes to dependencies and auth that affect running the backend and memory flows:

- `bcrypt` is required by `backend/app/auth.py` for password hashing. If you see `ModuleNotFoundError: No module named 'bcrypt'`, install it in the venv:

```bash
source venv/bin/activate
pip install bcrypt
```

- The PyPI package named `jose` is outdated and incompatible with modern Python (causes SyntaxError in its top-level code). The codebase depends on `python-jose[cryptography]` (imported as `from jose import jwt, JWTError`). If you installed `jose` previously, uninstall it and install the supported package:

```bash
pip uninstall -y jose
pip install python-jose[cryptography]
```

- `JWT_SECRET_KEY` environment variable is now required for the authentication module (`backend/app/auth.py`) to create and decode JWTs. Add it to your `.env` used by `database.py` (the app loads `.env` on startup).

Identification, visitor→user merge, and quick tests
--------------------------------------------------
There are a few flows that interact with memory and auth you can test quickly:

- Non-auth identification (fast lookup): `POST /api/auth/identify` — attempts to match by `full_name` + `phone`. If a match is found it will merge visitor memory into the matched user via `merge_visitor_memory_to_user()` and return `identified=true` with `user_id`. If no match it creates a lightweight `DBUser` record and returns `identified=false` with a new `user_id`.

- Register/login merge behavior: When an anonymous visitor signs up or logs in and provides `visitor_id`, `register` and `login` endpoints call `merge_visitor_memory_to_user(db, visitor_id, user.id)` to attach prior visitor facts and session summaries to the new `user_id`.

Quick test commands (example):

```bash
# 1) Create an anonymous session and note the visitor_id in the create response
# 2) End the session so memory extraction runs (or simulate extraction manually)
# 3) Try identification by name/phone:
curl -X POST http://localhost:8000/api/auth/identify -H 'Content-Type: application/json' -d '{"full_name":"Alex","phone":"+1 (555) 555-5555","visitor_id":"VISITOR_ID_HERE"}' | jq

# 4) Register a new account and pass the same visitor_id to merge
curl -X POST http://localhost:8000/api/auth/register -H 'Content-Type: application/json' -d '{"email":"alex@example.com","password":"secret","display_name":"Alex","phone":"+15555555555","visitor_id":"VISITOR_ID_HERE"}' | jq
```

Notes & follow-ups
-------------------
- If you want, I can add a small helper script (`scripts/reextract_memory.py`) that:
  - accepts a `session_id`, fetches the transcript + profile from the DB, calls `extract_memory_from_session()` and prints/stores the raw model output alongside the parsed JSON. This makes iterating on the Gemini prompt quicker.
- I can also add logging to persist raw Gemini responses on parse failure (into `session_summaries` or a new `memory_extraction_raw` table) so we can debug noisy model outputs without losing context.

Let me know which follow-up you want and I'll implement it next.

Immediate runtime fix & Gemini client deprecation
------------------------------------------------
Two runtime issues observed when starting the server:

- RuntimeError: "Form data requires \"python-multipart\" to be installed." — this is raised by FastAPI when a route depends on form/multipart parsing (your `backend/app/sms.py` router triggers it at import time). Installing `python-multipart` in the project's venv fixes this immediately.

Install in your activated venv:

```bash
source venv/bin/activate
pip install -r backend/requirements.txt
```

Or install just the package:

```bash
pip install python-multipart
```

- FutureWarning: `google.generativeai` is deprecated. The repo currently imports `google.generativeai` in `backend/app/layers/comprehension.py` and `backend/app/memory.py`. The upstream package is deprecated in favor of `google.genai`.

Recommendation:

1. For now you can continue running with `google.generativeai` (it's a warning), but plan to migrate the code to `google.genai` to receive updates and avoid future breakage.
2. Migration steps (high level):
   - Replace `import google.generativeai as genai` with the `google.genai` client patterns. See the `google.genai` README for usage examples and authentication updates.
   - Update `backend/requirements.txt` when ready to use the new package (e.g., `google-genai` or the exact package name from official docs).

If you want I can prepare a PR to migrate `memory.py` and `layers/comprehension.py` to the `google.genai` client API (I recommend running the integration tests / a small manual check after migration).