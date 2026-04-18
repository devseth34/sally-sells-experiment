FROM python:3.11-slim

WORKDIR /app

# System deps for audio/WebRTC libs. Keep lean — we don't need ffmpeg
# unless LiveKit's egress pipeline demands it locally, which it doesn't
# for a SIP/WebRTC-only agent.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The agent is a WebSocket client to LiveKit, not an HTTP server.
# No EXPOSE needed. fly.toml disables the HTTP service.
CMD ["python", "-m", "voice_agent.agent"]
