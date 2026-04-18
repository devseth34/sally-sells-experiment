"""Cost cap + concurrency guardrails for voice calls.

Meta ads can overdeliver; provider rate limits (Deepgram, Cartesia,
ElevenLabs, Claude) can silently drop calls. This module refuses new
calls when guardrails trip and logs the refusal for operator alerting.

Env vars (Addendum §B13):
    MAX_CONCURRENT_CALLS=3      # Raise to 5 after 20 stable calls.
    DAILY_SPEND_CAP_USD=25      # Refuse new calls when exceeded.
    HOURLY_CALL_CAP=15          # Burst protection.

Per-provider rate-limit wrappers:
    ElevenLabs Flash v2.5: cap 10 req/s (docs: 40 req/s tier)
    Cartesia Sonic 2:      cap 20 req/s (docs: 100 req/s)
    Deepgram streaming:    verify connection cap per account tier
    Claude Sonnet:         budget for 3 concurrent streams

Daily email @ 23:00 IST to Dev with: calls today, cost today, cost WTD,
any rate-limit errors.

TODO (Day 2+):
    - class CostGuard:
        - def can_accept_call() -> tuple[bool, str]  # (ok, reason)
        - def record_call_start(session_id)
        - def record_call_end(session_id, cost_usd)
        - def current_concurrent() -> int
        - def spend_today_usd() -> float
    - async rate limiters (asyncio.Semaphore) per provider SDK.
    - Nightly report job (`backend/app/main.py` already has other
      scheduled jobs — wire this in at the same level).
    - Hook Meta campaign daily cap (₹2,500/day) as an ad platform
      setting, not in code, but log when the spend-cap trips here so
      ops can correlate.
"""
