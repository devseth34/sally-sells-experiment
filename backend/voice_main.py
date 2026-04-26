"""Voice API process — runs separately from the frozen chat backend.

The chat backend (backend/app/main.py) is frozen and cannot be modified.
This is a sibling FastAPI app that owns all voice-specific endpoints:
  POST /voice/token      — mint LiveKit JWT for browser callers
  POST /voice/persist    — called by voice agent at session end
  GET  /voice/sessions   — session list for the voice tab
  GET  /voice/sessions/{call_id}  — session detail
  GET  /voice/analytics  — per-arm rollup

Run locally (port 8001, separate terminal from the chat backend):
    source venv/bin/activate
    python -m backend.voice_main          # from repo root
    # OR
    cd backend && python voice_main.py    # from backend/

Production: deploy as a separate Railway service rooted at backend/.
The Procfile-style start command is in backend/railway-voice.toml.
"""

import logging
import os

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Support both run-from-repo-root (`python -m backend.voice_main`) and
# run-from-backend (`python voice_main.py`, which is what Railway does
# when the service root is `backend/`). Try both import paths.
try:
    from backend.voice_persistence_api import router, voice_init_db
except ImportError:  # cwd is backend/, so backend.* doesn't resolve
    from voice_persistence_api import router, voice_init_db  # type: ignore

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Sally Voice API", version="1.0.0")

# CORS: in production, set FRONTEND_URL to your Vercel domain to lock this
# down. In dev, falls back to a permissive list including the Vite default.
_frontend_url = os.environ.get("FRONTEND_URL", "").rstrip("/")
_allow_origins = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
]
if _frontend_url and _frontend_url not in _allow_origins:
    _allow_origins.append(_frontend_url)
# Vercel preview deployments use *-vercel.app subdomains. Allow regex match
# alongside the exact list — Vercel previews are fine for testing.
_allow_origin_regex = r"^https://.*\.vercel\.app$"

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_origin_regex=_allow_origin_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
def root() -> dict:
    """Healthcheck endpoint for Railway."""
    return {"service": "sally-voice-api", "status": "ok"}


@app.on_event("startup")
async def _startup() -> None:
    voice_init_db()


if __name__ == "__main__":
    port = int(os.environ.get("VOICE_PORT", "8001"))
    # Use module:app form so uvicorn can reload-track. We try both module
    # paths because the running script's location varies.
    module_path = "backend.voice_main:app"
    try:
        import backend.voice_main  # noqa: F401
    except ImportError:
        module_path = "voice_main:app"
    uvicorn.run(module_path, host="0.0.0.0", port=port, reload=False)
