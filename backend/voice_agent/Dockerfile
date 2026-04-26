# Voice agent image (Fly.io).
#
# Build context expected: REPO ROOT (../..). Set in fly.toml via
# `[build] dockerfile = "backend/voice_agent/Dockerfile"` and running
# `fly deploy --dockerfile backend/voice_agent/Dockerfile` from repo root.
# This is required because sally.py and friends use `backend.voice_agent.*`
# absolute imports — they need the repo root on PYTHONPATH.
FROM python:3.12-slim

WORKDIR /app

# System deps for audio/WebRTC libs. Keep lean.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install voice agent deps (the superset of backend deps)
COPY backend/voice_agent/requirements.txt /app/voice_requirements.txt
RUN pip install --no-cache-dir -r /app/voice_requirements.txt

# Copy the entire backend package so `backend.voice_agent.*` imports resolve
# and so backend/app/* is available for the frozen engine the runner calls
# through engine_adapter.py.
COPY backend /app/backend

# Add empty __init__.py if missing for backend/ (it's already a package via
# backend/__init__.py existence — verify locally if this fails).
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# The agent is a WebSocket client to LiveKit, not an HTTP server.
# fly.toml disables http_service.
CMD ["python", "-m", "backend.voice_agent.sally", "start"]
