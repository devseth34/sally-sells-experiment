"""Voice persistence API: token minting + session/turn persistence.

Two logical sections:
  1. Token endpoint — mints a LiveKit JWT for the browser so the frontend
     can join a room without the LiveKit API secret being exposed client-side.
  2. Persist endpoint — called by the voice agent (Fly.io) at session end
     to write the full session + per-turn metrics to the same PostgreSQL DB
     that the chat product uses. Uses a separate SQLAlchemy Base from the
     frozen app/database.py — new tables only.

Also exposes read-only query endpoints for the voice tab's sessions list,
session detail, and analytics pages.

Mounted on voice_main.py (a standalone FastAPI process, port 8001).
The frozen backend/app/main.py is never touched.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import (
    Column,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    func,
    inspect,
    text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker

# Load .env from repo root. voice_main.py sets override=True at import time
# so this second call is fine — it's idempotent if the vars are already set.
_REPO_ROOT = os.path.join(os.path.dirname(os.path.dirname(__file__)))
load_dotenv(os.path.join(_REPO_ROOT, ".env"), override=True)

log = logging.getLogger("sally.voice-api")

# ---------------------------------------------------------------------------
# Database — separate Base from the frozen app/database.py
# ---------------------------------------------------------------------------

DATABASE_URL = os.getenv("DATABASE_URL")

_engine = None
_SessionLocal = None
VoiceBase = declarative_base()


def _get_engine():
    global _engine
    if _engine is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL not set")
        _engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=3, max_overflow=5)
    return _engine


def _get_session_local():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_get_engine())
    return _SessionLocal


def get_db():
    db = _get_session_local()()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------

class DBVoiceSession(VoiceBase):
    __tablename__ = "voice_sessions"
    id = Column(String, primary_key=True)
    call_id = Column(String, unique=True, index=True, nullable=False)
    arm = Column(String, index=True, nullable=False)
    personality = Column(String, nullable=False)
    forced = Column(Integer, default=0)          # 0/1 (SQLite-compat)
    started_at = Column(Float, nullable=False)
    ended_at = Column(Float, nullable=True)
    duration_s = Column(Float, nullable=True)
    deepest_phase = Column(String, nullable=True)
    ended_at_phase = Column(String, nullable=True)
    session_ended = Column(Integer, default=0)   # 0/1
    n_turns = Column(Integer, default=0)
    created_at = Column(Float, nullable=False)


class DBVoiceTurn(VoiceBase):
    __tablename__ = "voice_turns"
    id = Column(String, primary_key=True)
    session_id = Column(String, index=True, nullable=False)
    turn_index = Column(Integer, nullable=False)
    phase = Column(String, nullable=False)
    phase_changed = Column(Integer, default=0)
    user_text = Column(Text, nullable=False)
    sally_text = Column(Text, nullable=False)
    asr_ms = Column(Float, nullable=True)
    engine_dispatch_ms = Column(Float, nullable=True)
    engine_ms = Column(Float, nullable=True)
    tts_first_frame_ms = Column(Float, nullable=True)
    user_latency_ms = Column(Float, nullable=True)
    utterance_duration_ms = Column(Float, nullable=True)
    l1_model = Column(String, nullable=True)
    user_emotion = Column(String, nullable=True)
    tts_tier = Column(String, nullable=True)
    audio_tags_used = Column(Text, nullable=True)   # JSON string
    expression_decorated = Column(Integer, default=0)
    tag_director_used = Column(Integer, default=0)
    tag_director_latency_ms = Column(Float, nullable=True)
    tag_director_fallback = Column(String, nullable=True)
    thought_log = Column(Text, nullable=True)        # JSON string
    timestamp = Column(Float, nullable=False)
    ended = Column(Integer, default=0)


def voice_init_db() -> None:
    """Create voice tables if they don't exist. Safe to call on every startup."""
    eng = _get_engine()
    VoiceBase.metadata.create_all(bind=eng)
    insp = inspect(eng)

    # Additive column migrations for voice_turns (in case schema evolves)
    with eng.connect() as conn:
        if "voice_turns" in insp.get_table_names():
            existing = {c["name"] for c in insp.get_columns("voice_turns")}
            additive = {
                "ended": "ALTER TABLE voice_turns ADD COLUMN ended INTEGER DEFAULT 0",
            }
            for col, sql in additive.items():
                if col not in existing:
                    conn.execute(text(sql))
            conn.commit()

    log.info("voice_init_db: tables ready")


# ---------------------------------------------------------------------------
# Rate limiter (in-memory, per-process — acceptable for Phase 1)
# ---------------------------------------------------------------------------

@dataclass
class _Bucket:
    count: int
    reset_at: float

_ip_buckets: dict[str, _Bucket] = {}
_RATE_LIMIT = 10
_WINDOW_S = 3600.0


def _rate_ok(ip: str) -> bool:
    now = time.time()
    bucket = _ip_buckets.get(ip)
    if bucket is None or bucket.reset_at < now:
        _ip_buckets[ip] = _Bucket(count=1, reset_at=now + _WINDOW_S)
        return True
    if bucket.count >= _RATE_LIMIT:
        return False
    bucket.count += 1
    return True


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter()

_VALID_ARMS = frozenset(
    ["sally_warm", "sally_confident", "sally_direct", "sally_emotive"]
)

# ---------------------------------------------------------------------------
# Phase 1A — Token endpoint
# ---------------------------------------------------------------------------

class TokenRequest(BaseModel):
    forcedPersonality: Optional[str] = None


class TokenResponse(BaseModel):
    token: str
    url: str
    roomName: str
    callId: str


@router.post("/voice/token", response_model=TokenResponse)
async def mint_token(body: TokenRequest, request: Request) -> TokenResponse:
    """Mint a short-lived LiveKit JWT for the browser caller.

    The browser cannot hold LIVEKIT_API_SECRET, so this endpoint mints
    the credential server-side and returns a single-use token.
    """
    ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or request.headers.get("x-real-ip", "")
        or "unknown"
    )
    if not _rate_ok(ip):
        raise HTTPException(status_code=429, detail="rate_limit_exceeded")

    api_key = os.environ.get("LIVEKIT_API_KEY")
    api_secret = os.environ.get("LIVEKIT_API_SECRET")
    lk_url = os.environ.get("LIVEKIT_URL")
    if not api_key or not api_secret or not lk_url:
        raise HTTPException(
            status_code=500,
            detail="LIVEKIT_API_KEY / LIVEKIT_API_SECRET / LIVEKIT_URL not configured",
        )

    forced = body.forcedPersonality if body.forcedPersonality in _VALID_ARMS else None
    call_id = str(uuid.uuid4())
    room_name = f"voice-{call_id}"
    participant_identity = f"user-{uuid.uuid4()}"

    metadata = json.dumps(
        {
            "forcedPersonality": forced,
            "callId": call_id,
            "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    )

    try:
        from livekit.api import AccessToken, VideoGrants  # type: ignore
        # The livekit-api Python SDK uses a builder pattern — each
        # `with_*` call returns the AccessToken instance for chaining.
        token = (
            AccessToken(api_key, api_secret)
            .with_identity(participant_identity)
            .with_ttl(timedelta(seconds=1800))
            .with_metadata(metadata)
            .with_grants(
                VideoGrants(
                    room_join=True,
                    room=room_name,
                    can_publish=True,
                    can_subscribe=True,
                    can_publish_data=True,  # used by Phase 2 live thought-log
                )
            )
            .to_jwt()
        )
    except Exception as exc:
        log.exception("Failed to mint LiveKit token")
        raise HTTPException(status_code=500, detail=f"token_mint_failed: {exc}") from exc

    return TokenResponse(token=token, url=lk_url, roomName=room_name, callId=call_id)


# ---------------------------------------------------------------------------
# Phase 1C — Persist endpoint (called by voice agent at session end)
# ---------------------------------------------------------------------------

class TurnPayload(BaseModel):
    turn_index: int
    phase: str
    phase_changed: bool = False
    user_text: str
    sally_text: str
    asr_ms: Optional[float] = None
    engine_dispatch_ms: Optional[float] = None
    engine_ms: Optional[float] = None
    tts_first_frame_ms: Optional[float] = None
    user_latency_ms: Optional[float] = None
    utterance_duration_ms: Optional[float] = None
    l1_model: Optional[str] = None
    user_emotion: Optional[str] = None
    tts_tier: Optional[str] = None
    audio_tags_used: Optional[list] = None
    expression_decorated: bool = False
    tag_director_used: bool = False
    tag_director_latency_ms: Optional[float] = None
    tag_director_fallback: Optional[str] = None
    thought_log: Optional[dict] = None
    timestamp: float
    ended: bool = False


class SessionPayload(BaseModel):
    call_id: str
    arm: str
    personality: str
    forced: bool
    started_at: float
    ended_at: Optional[float] = None
    duration_s: Optional[float] = None
    deepest_phase: Optional[str] = None
    ended_at_phase: Optional[str] = None
    session_ended: bool = False
    n_turns: int
    turns: list[TurnPayload]


@router.post("/voice/persist")
async def persist_session(
    payload: SessionPayload,
    x_voice_agent_token: str = Header(default=""),
    db: Session = Depends(get_db),
) -> dict:
    """Insert a completed voice session + all its turns into the DB.

    Called by backend/voice_agent/persistence.py at call teardown.
    Authenticated via a shared secret (VOICE_PERSIST_TOKEN) so the
    public internet cannot write arbitrary rows.
    """
    expected = os.environ.get("VOICE_PERSIST_TOKEN", "")
    if not expected or x_voice_agent_token != expected:
        raise HTTPException(status_code=401, detail="invalid token")

    now = time.time()
    session_row_id = str(uuid.uuid4())

    # Upsert on call_id so retries from the disk-fallback path don't duplicate.
    existing = db.query(DBVoiceSession).filter_by(call_id=payload.call_id).first()
    if existing is None:
        session_row = DBVoiceSession(
            id=session_row_id,
            call_id=payload.call_id,
            arm=payload.arm,
            personality=payload.personality,
            forced=int(payload.forced),
            started_at=payload.started_at,
            ended_at=payload.ended_at,
            duration_s=payload.duration_s,
            deepest_phase=payload.deepest_phase,
            ended_at_phase=payload.ended_at_phase,
            session_ended=int(payload.session_ended),
            n_turns=payload.n_turns,
            created_at=now,
        )
        db.add(session_row)
        db.flush()
    else:
        session_row_id = existing.id
        # Update mutable fields in case this is a retry with fresher data.
        existing.ended_at = payload.ended_at
        existing.duration_s = payload.duration_s
        existing.deepest_phase = payload.deepest_phase
        existing.ended_at_phase = payload.ended_at_phase
        existing.session_ended = int(payload.session_ended)
        existing.n_turns = payload.n_turns
        db.flush()

    for turn in payload.turns:
        existing_turn = (
            db.query(DBVoiceTurn)
            .filter_by(session_id=session_row_id, turn_index=turn.turn_index)
            .first()
        )
        if existing_turn is not None:
            continue  # idempotent — don't re-insert duplicate turns

        tags_json = json.dumps(turn.audio_tags_used) if turn.audio_tags_used is not None else None
        thought_json = json.dumps(turn.thought_log) if turn.thought_log is not None else None

        db.add(
            DBVoiceTurn(
                id=str(uuid.uuid4()),
                session_id=session_row_id,
                turn_index=turn.turn_index,
                phase=turn.phase,
                phase_changed=int(turn.phase_changed),
                user_text=turn.user_text,
                sally_text=turn.sally_text,
                asr_ms=turn.asr_ms,
                engine_dispatch_ms=turn.engine_dispatch_ms,
                engine_ms=turn.engine_ms,
                tts_first_frame_ms=turn.tts_first_frame_ms,
                user_latency_ms=turn.user_latency_ms,
                utterance_duration_ms=turn.utterance_duration_ms,
                l1_model=turn.l1_model,
                user_emotion=turn.user_emotion,
                tts_tier=turn.tts_tier,
                audio_tags_used=tags_json,
                expression_decorated=int(turn.expression_decorated),
                tag_director_used=int(turn.tag_director_used),
                tag_director_latency_ms=turn.tag_director_latency_ms,
                tag_director_fallback=turn.tag_director_fallback,
                thought_log=thought_json,
                timestamp=turn.timestamp,
                ended=int(turn.ended),
            )
        )

    db.commit()
    log.info("Persisted session %s with %d turns", payload.call_id, payload.n_turns)
    return {"ok": True, "call_id": payload.call_id}


# ---------------------------------------------------------------------------
# Phase 1F — Sessions list + detail read endpoints
# ---------------------------------------------------------------------------

@router.get("/voice/sessions")
def list_sessions(
    arm: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> list[dict]:
    """List voice sessions, newest first. Optionally filter by arm."""
    q = db.query(DBVoiceSession).order_by(DBVoiceSession.started_at.desc())
    if arm:
        q = q.filter(DBVoiceSession.arm == arm)
    rows = q.limit(limit).all()
    return [
        {
            "call_id": r.call_id,
            "arm": r.arm,
            "personality": r.personality,
            "forced": bool(r.forced),
            "started_at": r.started_at,
            "ended_at": r.ended_at,
            "duration_s": r.duration_s,
            "deepest_phase": r.deepest_phase,
            "ended_at_phase": r.ended_at_phase,
            "session_ended": bool(r.session_ended),
            "n_turns": r.n_turns,
        }
        for r in rows
    ]


@router.get("/voice/sessions/{call_id}")
def get_session(call_id: str, db: Session = Depends(get_db)) -> dict:
    """Full session detail with per-turn rows."""
    sess = db.query(DBVoiceSession).filter_by(call_id=call_id).first()
    if sess is None:
        raise HTTPException(status_code=404, detail="session not found")
    turns = (
        db.query(DBVoiceTurn)
        .filter_by(session_id=sess.id)
        .order_by(DBVoiceTurn.turn_index)
        .all()
    )
    return {
        "call_id": sess.call_id,
        "arm": sess.arm,
        "personality": sess.personality,
        "forced": bool(sess.forced),
        "started_at": sess.started_at,
        "ended_at": sess.ended_at,
        "duration_s": sess.duration_s,
        "deepest_phase": sess.deepest_phase,
        "ended_at_phase": sess.ended_at_phase,
        "session_ended": bool(sess.session_ended),
        "n_turns": sess.n_turns,
        "turns": [_serialize_turn(t) for t in turns],
    }


def _serialize_turn(t: DBVoiceTurn) -> dict:
    return {
        "turn_index": t.turn_index,
        "phase": t.phase,
        "phase_changed": bool(t.phase_changed),
        "user_text": t.user_text,
        "sally_text": t.sally_text,
        "asr_ms": t.asr_ms,
        "engine_dispatch_ms": t.engine_dispatch_ms,
        "engine_ms": t.engine_ms,
        "tts_first_frame_ms": t.tts_first_frame_ms,
        "user_latency_ms": t.user_latency_ms,
        "utterance_duration_ms": t.utterance_duration_ms,
        "l1_model": t.l1_model,
        "user_emotion": t.user_emotion,
        "tts_tier": t.tts_tier,
        "audio_tags_used": json.loads(t.audio_tags_used) if t.audio_tags_used else None,
        "expression_decorated": bool(t.expression_decorated),
        "tag_director_used": bool(t.tag_director_used),
        "tag_director_latency_ms": t.tag_director_latency_ms,
        "tag_director_fallback": t.tag_director_fallback,
        "thought_log": json.loads(t.thought_log) if t.thought_log else None,
        "timestamp": t.timestamp,
        "ended": bool(t.ended),
    }


# ---------------------------------------------------------------------------
# Phase 1G — Analytics endpoint
# ---------------------------------------------------------------------------

@router.get("/voice/analytics")
def get_analytics(
    arm: Optional[str] = None,
    db: Session = Depends(get_db),
) -> dict:
    """Per-arm rollup: session counts, avg turns, latency distributions.

    Percentile calculations done in Python (portable across Postgres/SQLite).
    Top audio tags computed by unnesting the JSON arrays in voice_turns.
    """
    sess_q = db.query(DBVoiceSession)
    if arm:
        sess_q = sess_q.filter(DBVoiceSession.arm == arm)
    sessions = sess_q.all()

    # Group sessions by arm
    arms: dict[str, list[DBVoiceSession]] = {}
    for s in sessions:
        arms.setdefault(s.arm, []).append(s)

    per_arm: dict[str, Any] = {}
    for arm_key, arm_sessions in arms.items():
        session_ids = [s.id for s in arm_sessions]
        turns = (
            db.query(DBVoiceTurn).filter(DBVoiceTurn.session_id.in_(session_ids)).all()
            if session_ids
            else []
        )

        def p50(vals: list[float]) -> Optional[float]:
            if not vals:
                return None
            s_vals = sorted(vals)
            mid = len(s_vals) // 2
            return s_vals[mid] if len(s_vals) % 2 else (s_vals[mid - 1] + s_vals[mid]) / 2

        def p95(vals: list[float]) -> Optional[float]:
            if not vals:
                return None
            idx = max(0, int(len(vals) * 0.95) - 1)
            return sorted(vals)[idx]

        ulat = [t.user_latency_ms for t in turns if t.user_latency_ms is not None]
        eng = [t.engine_ms for t in turns if t.engine_ms is not None]
        tts = [t.tts_first_frame_ms for t in turns if t.tts_first_frame_ms is not None]

        phase_dist: dict[str, int] = {}
        for s in arm_sessions:
            if s.deepest_phase:
                phase_dist[s.deepest_phase] = phase_dist.get(s.deepest_phase, 0) + 1

        tier_counts: dict[str, int] = {}
        for t in turns:
            tier = t.tts_tier or "fast"
            tier_counts[tier] = tier_counts.get(tier, 0) + 1

        tag_counts: dict[str, int] = {}
        for t in turns:
            if t.audio_tags_used:
                try:
                    tags = json.loads(t.audio_tags_used)
                    for tag in tags:
                        tag_counts[tag] = tag_counts.get(tag, 0) + 1
                except (json.JSONDecodeError, TypeError):
                    pass

        top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        director_turns = [t for t in turns if t.tag_director_used]
        director_fallback = [t for t in turns if t.tag_director_fallback is not None]
        dir_lat = [t.tag_director_latency_ms for t in director_turns if t.tag_director_latency_ms is not None]

        per_arm[arm_key] = {
            "total_sessions": len(arm_sessions),
            "avg_turns": (sum(s.n_turns for s in arm_sessions) / len(arm_sessions)) if arm_sessions else 0,
            "deepest_phase_distribution": phase_dist,
            "latency": {
                "user_latency_p50_ms": p50(ulat),
                "user_latency_p95_ms": p95(ulat),
                "engine_p50_ms": p50(eng),
                "engine_p95_ms": p95(eng),
                "tts_first_frame_p50_ms": p50(tts),
                "tts_first_frame_p95_ms": p95(tts),
            },
            "tts_tier_counts": tier_counts,
            "top_audio_tags": [{"tag": t, "count": c} for t, c in top_tags],
            "tag_director": {
                "used_count": len(director_turns),
                "fallback_count": len(director_fallback),
                "fallback_rate": (
                    len(director_fallback) / (len(director_turns) + len(director_fallback))
                    if director_turns or director_fallback
                    else 0.0
                ),
                "latency_p50_ms": p50(dir_lat),
            },
        }

    return {"arms": per_arm, "total_sessions": len(sessions)}
