# Deployment Guide — Voice Tab (Phases 1 + 2)

This guide takes you from a working local setup to a fully deployed
voice tab. Three services need to be deployed: **chat backend** (Railway,
already live), **voice API** (Railway, NEW), **voice agent** (Fly.io,
needs entrypoint update). The **frontend** (Vercel) just needs an env var.

---

## Prerequisites

- GitHub repo `devseth34/sally-sells-experiment` connected to:
  - **Railway** for the chat backend (existing)
  - **Vercel** for the frontend (existing)
- A Fly.io account with `flyctl` installed locally
- Neon PostgreSQL DB URL (in your `.env` already as `DATABASE_URL`)
- LiveKit Cloud project — your existing keys in `.env` work

---

## 1) Voice API → new Railway service

The voice API (`backend/voice_main.py`) runs as a **separate** Railway
service from the chat backend. They share the same Postgres but the
processes are independent.

### Steps

1. In Railway dashboard, **create a new service** in the same project as
   the chat backend.
2. Connect it to the same GitHub repo.
3. Service settings:
   - **Root directory:** `backend`
   - **Config file:** `railway-voice.toml`
   - **Branch:** `main`
4. Set these env vars (Variables tab):

   | Name | Value |
   |---|---|
   | `DATABASE_URL` | Same Neon URL as the chat service |
   | `LIVEKIT_URL` | `wss://sally-sells-580wrkyt.livekit.cloud` |
   | `LIVEKIT_API_KEY` | (from your `.env`) |
   | `LIVEKIT_API_SECRET` | (from your `.env`) |
   | `VOICE_PERSIST_TOKEN` | Run `python -c "import secrets; print(secrets.token_hex(32))"` |
   | `FRONTEND_URL` | `https://<your-vercel-domain>` (locks CORS) |
   | `SKIP_SCHEMA_CHECK` | leave **unset** on first deploy so voice tables get created |

5. Deploy. Railway picks up `railway-voice.toml` and runs
   `uvicorn voice_main:app --host 0.0.0.0 --port $PORT`.

6. **Verify:** Hit `https://<voice-api-url>/` — should return
   `{"service": "sally-voice-api", "status": "ok"}`. Then hit
   `https://<voice-api-url>/voice/sessions` — should return `[]` on
   first deploy.

7. After first successful deploy, set `SKIP_SCHEMA_CHECK=true` on this
   service to speed up cold starts.

8. **Save the public URL** of this service — you'll need it in steps 2
   and 3.

---

## 2) Voice agent → update Fly.io deploy

The voice agent on Fly.io currently runs the Day 2A hello-world
(`voice_agent.agent`). It needs to switch to `backend.voice_agent.sally`
and get the new env vars.

### Steps

1. From the **repo root**, set the new secrets:

   ```bash
   fly secrets set \
     VOICE_PERSIST_URL="https://<voice-api-railway-url>/voice/persist" \
     VOICE_PERSIST_TOKEN="<the-same-token-as-step-1>" \
     --config backend/voice_agent/fly.toml
   ```

2. Verify all required secrets are set (each on its own line):

   ```bash
   fly secrets list --config backend/voice_agent/fly.toml
   ```

   Required (set with `fly secrets set`):
   - `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`
   - `DEEPGRAM_API_KEY`, `CARTESIA_API_KEY`, `ELEVENLABS_API_KEY`
   - `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`
   - `DATABASE_URL` (Neon URL — engine_adapter reads sessions through frozen `app/database.py`)
   - `VOICE_PERSIST_URL`, `VOICE_PERSIST_TOKEN`

3. Deploy from **repo root** (build context is `.`, Dockerfile is at `backend/voice_agent/Dockerfile`):

   ```bash
   fly deploy \
     --config backend/voice_agent/fly.toml \
     --dockerfile backend/voice_agent/Dockerfile \
     .
   ```

4. Watch logs to confirm `backend.voice_agent.sally` starts cleanly:

   ```bash
   fly logs --config backend/voice_agent/fly.toml
   ```

   You should see `Sally connected` once a LiveKit room dispatch arrives.
   The worker waits for room dispatches; it doesn't do anything until a
   browser hits the token endpoint and joins.

---

## 3) Frontend → set env var on Vercel

The frontend's voice tab calls the voice API URL via `VITE_VOICE_API_URL`.

### Steps

1. Vercel dashboard → your project → **Settings → Environment Variables**
2. Add: `VITE_VOICE_API_URL` = `https://<voice-api-railway-url>` (no
   trailing slash, no `/voice` suffix — the client appends `/voice/...`).
3. Redeploy from the Vercel dashboard (or push to GitHub to trigger).

---

## 4) Smoke test the deployed voice tab

1. Open `https://<your-vercel-domain>/voice`
2. The Voice nav link should be highlighted, the arm picker should appear,
   and the "Talk to Sally" button should be visible.
3. Optionally pick `sally_emotive` from the arm dropdown.
4. Click **Talk to Sally**. Browser asks for mic permission → grant it.
5. Speak — within ~700ms Sally should respond.
6. The reasoning panel on the right should populate **live** with each
   turn as Sally finishes speaking (Phase 2 data channel).
7. End the call.
8. Click **View transcript & reasoning** → should load the post-hoc view
   with all turns from the database.
9. Navigate to `/voice/sessions` → your session should appear at the top.
10. Navigate to `/voice/analytics` → arm rollup should reflect your call.

### Verify DB writes (optional)

```sql
SELECT call_id, arm, n_turns, deepest_phase
FROM voice_sessions
ORDER BY started_at DESC
LIMIT 3;
```

---

## Push to GitHub

After the three deploys above are configured, pushing to GitHub triggers:

- Railway redeploys both services (chat + voice API) automatically
- Vercel redeploys the frontend automatically
- Fly.io does **not** auto-deploy — re-run `fly deploy ...` whenever the
  voice agent code changes

Suggested commit:
```
git add -A
git commit -m "Voice tab Phases 1+2 — deploy ready

- New Railway service: backend/voice_main.py + railway-voice.toml
- Fly.io entrypoint: backend.voice_agent.sally (was voice_agent.agent)
- Frontend: /voice tab + live reasoning panel + post-hoc viewer
- DB: voice_sessions + voice_turns tables (auto-create on first boot)
- 162 tests pass, npm build clean
"
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `/voice/token` returns 500 | Missing LiveKit env vars on voice API service | Set `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `LIVEKIT_URL` in Railway |
| `/voice/persist` returns 401 | Token mismatch | Make sure `VOICE_PERSIST_TOKEN` is the **exact same** string in Fly.io and Railway voice API |
| Voice agent says "Sally connected" but never speaks | Missing GEMINI/ANTHROPIC keys | `fly secrets list` and confirm both are set |
| Frontend can't reach voice API | CORS or wrong URL | Set `FRONTEND_URL` env var on the voice API service to your Vercel domain |
| `voice_sessions` table doesn't exist | First deploy didn't run schema | Unset `SKIP_SCHEMA_CHECK` on voice API, redeploy, then re-set to `true` |
| Browser refresh during call | Expected — live panel resets, post-hoc still works | After call ends, navigate to `/voice/sessions/{call_id}` for full record |
