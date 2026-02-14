"""
Sally Sells — FastAPI Application

Three-layer architecture: Comprehension -> Decision -> Response pipeline.
Persists prospect profile and thought logs per session.
"""

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session as DBSessionType
from sqlalchemy import func
import uuid
import time
import json
import logging

import os
from .database import get_db, DBSession, DBMessage, init_db
from .schemas import (
    NepqPhase,
    CreateSessionRequest,
    CreateSessionResponse,
    SendMessageRequest,
    SendMessageResponse,
    MessageResponse,
    SessionDetailResponse,
    SessionListItem,
    MetricsResponse,
)
from .agent import SallyEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sally.api")

app = FastAPI(title="Sally Sells API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/")
def root():
    return {"status": "ok", "service": "Sally Sells API", "version": "2.0.0", "engine": "three-layer-nepq"}


# --- Session Management ---

@app.post("/api/sessions", response_model=CreateSessionResponse)
def create_session(request: CreateSessionRequest, db: DBSessionType = Depends(get_db)):
    session_id = str(uuid.uuid4())[:8].upper()
    now = time.time()

    db_session = DBSession(
        id=session_id,
        status="active",
        current_phase=NepqPhase.CONNECTION.value,
        pre_conviction=request.pre_conviction,
        start_time=now,
        message_count=1,
        retry_count=0,
        turn_number=0,
        prospect_profile="{}",
        thought_logs="[]",
    )
    db.add(db_session)

    greeting_text = SallyEngine.get_greeting()
    greeting_id = str(uuid.uuid4())
    greeting_msg = DBMessage(
        id=greeting_id,
        session_id=session_id,
        role="assistant",
        content=greeting_text,
        timestamp=now,
        phase=NepqPhase.CONNECTION.value,
    )
    db.add(greeting_msg)
    db.commit()

    return CreateSessionResponse(
        session_id=session_id,
        current_phase=NepqPhase.CONNECTION.value,
        pre_conviction=request.pre_conviction,
        greeting=MessageResponse(
            id=greeting_id,
            role="assistant",
            content=greeting_text,
            timestamp=now,
            phase=NepqPhase.CONNECTION.value,
        ),
    )


# --- Message Processing (The Core Loop) ---

@app.post("/api/sessions/{session_id}/messages", response_model=SendMessageResponse)
def send_message(session_id: str, request: SendMessageRequest, db: DBSessionType = Depends(get_db)):
    db_session = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not db_session:
        raise HTTPException(status_code=404, detail="Session not found")
    if db_session.status != "active":
        raise HTTPException(status_code=400, detail="Session is no longer active")

    now = time.time()
    current_phase = NepqPhase(db_session.current_phase)
    previous_phase = current_phase

    # Save user message
    user_msg_id = str(uuid.uuid4())
    user_msg = DBMessage(
        id=user_msg_id,
        session_id=session_id,
        role="user",
        content=request.content,
        timestamp=now,
        phase=current_phase.value,
    )
    db.add(user_msg)
    db_session.message_count += 1
    db_session.turn_number += 1

    # Build conversation history from DB
    messages = (
        db.query(DBMessage)
        .filter(DBMessage.session_id == session_id)
        .order_by(DBMessage.timestamp)
        .all()
    )
    conversation_history = [
        {"role": m.role, "content": m.content}
        for m in messages
    ]
    conversation_history.append({"role": "user", "content": request.content})

    # Run the Three-Layer Engine
    logger.info(f"[Session {session_id}] Processing turn {db_session.turn_number} in {current_phase.value}")

    try:
        result = SallyEngine.process_turn(
            current_phase=current_phase,
            user_message=request.content,
            conversation_history=conversation_history,
            profile_json=db_session.prospect_profile or "{}",
            retry_count=db_session.retry_count,
            turn_number=db_session.turn_number,
            conversation_start_time=db_session.start_time,
        )
    except Exception as e:
        logger.error(f"[Session {session_id}] Engine error: {e}")
        result = {
            "response_text": "I appreciate you sharing that. Could you tell me a bit more?",
            "new_phase": current_phase.value,
            "new_profile_json": db_session.prospect_profile or "{}",
            "thought_log_json": json.dumps({"error": str(e)}),
            "phase_changed": False,
            "session_ended": False,
            "retry_count": db_session.retry_count + 1,
        }

    # Update session state
    new_phase = NepqPhase(result["new_phase"])
    db_session.current_phase = new_phase.value
    db_session.retry_count = result["retry_count"]
    db_session.prospect_profile = result["new_profile_json"]

    # Append thought log
    try:
        existing_logs = json.loads(db_session.thought_logs or "[]")
    except json.JSONDecodeError:
        existing_logs = []
    try:
        new_log = json.loads(result["thought_log_json"])
        existing_logs.append(new_log)
    except json.JSONDecodeError:
        existing_logs.append({"error": "Failed to parse thought log"})
    db_session.thought_logs = json.dumps(existing_logs)

    # Check session end
    if result["session_ended"]:
        db_session.status = "completed"
        db_session.end_time = time.time()

    # Save assistant message
    assistant_msg_id = str(uuid.uuid4())
    assistant_msg = DBMessage(
        id=assistant_msg_id,
        session_id=session_id,
        role="assistant",
        content=result["response_text"],
        timestamp=time.time(),
        phase=new_phase.value,
    )
    db.add(assistant_msg)
    db_session.message_count += 1
    db.commit()

    logger.info(f"[Session {session_id}] Turn complete: {previous_phase.value} -> {new_phase.value} "
                f"(changed={result['phase_changed']}, ended={result['session_ended']})")

    return SendMessageResponse(
        user_message=MessageResponse(
            id=user_msg_id,
            role="user",
            content=request.content,
            timestamp=now,
            phase=previous_phase.value,
        ),
        assistant_message=MessageResponse(
            id=assistant_msg_id,
            role="assistant",
            content=result["response_text"],
            timestamp=assistant_msg.timestamp,
            phase=new_phase.value,
        ),
        current_phase=new_phase.value,
        previous_phase=previous_phase.value,
        phase_changed=result["phase_changed"],
        session_ended=result["session_ended"],
    )


# --- Session Detail (with thought logs) ---

@app.get("/api/sessions/{session_id}")
def get_session(session_id: str, db: DBSessionType = Depends(get_db)):
    db_session = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not db_session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = (
        db.query(DBMessage)
        .filter(DBMessage.session_id == session_id)
        .order_by(DBMessage.timestamp)
        .all()
    )

    try:
        thought_logs = json.loads(db_session.thought_logs or "[]")
    except json.JSONDecodeError:
        thought_logs = []

    try:
        prospect_profile = json.loads(db_session.prospect_profile or "{}")
    except json.JSONDecodeError:
        prospect_profile = {}

    return {
        "id": db_session.id,
        "status": db_session.status,
        "current_phase": db_session.current_phase,
        "pre_conviction": db_session.pre_conviction,
        "post_conviction": db_session.post_conviction,
        "start_time": db_session.start_time,
        "end_time": db_session.end_time,
        "turn_number": db_session.turn_number,
        "retry_count": db_session.retry_count,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "timestamp": m.timestamp,
                "phase": m.phase,
            }
            for m in messages
        ],
        "prospect_profile": prospect_profile,
        "thought_logs": thought_logs,
    }


# --- Session List ---

@app.get("/api/sessions", response_model=list[SessionListItem])
def list_sessions(db: DBSessionType = Depends(get_db)):
    sessions = db.query(DBSession).order_by(DBSession.start_time.desc()).all()
    return [
        SessionListItem(
            id=s.id,
            status=s.status,
            current_phase=s.current_phase,
            pre_conviction=s.pre_conviction,
            message_count=s.message_count,
            start_time=s.start_time,
            end_time=s.end_time,
        )
        for s in sessions
    ]


# --- Metrics ---

@app.get("/api/metrics", response_model=MetricsResponse)
def get_metrics(db: DBSessionType = Depends(get_db)):
    total = db.query(DBSession).count()
    active = db.query(DBSession).filter(DBSession.status == "active").count()
    completed = db.query(DBSession).filter(DBSession.status == "completed").count()
    abandoned = db.query(DBSession).filter(DBSession.status == "abandoned").count()
    avg_conviction = db.query(func.avg(DBSession.pre_conviction)).scalar()
    conversion_rate = (completed / total * 100) if total > 0 else 0.0

    phase_dist = {}
    for phase in NepqPhase:
        count = db.query(DBSession).filter(DBSession.current_phase == phase.value).count()
        if count > 0:
            phase_dist[phase.value] = count

    failure_modes = []
    for phase in NepqPhase:
        count = db.query(DBSession).filter(
            DBSession.status == "abandoned",
            DBSession.current_phase == phase.value,
        ).count()
        if count > 0:
            failure_modes.append({"phase": phase.value, "count": count})

    return MetricsResponse(
        total_sessions=total,
        active_sessions=active,
        completed_sessions=completed,
        abandoned_sessions=abandoned,
        average_pre_conviction=round(avg_conviction, 1) if avg_conviction else None,
        conversion_rate=round(conversion_rate, 1),
        phase_distribution=phase_dist,
        failure_modes=failure_modes,
    )


# --- End Session ---

@app.post("/api/sessions/{session_id}/end")
def end_session(session_id: str, db: DBSessionType = Depends(get_db)):
    db_session = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not db_session:
        raise HTTPException(status_code=404, detail="Session not found")
    if db_session.status == "active":
        db_session.status = "abandoned"
        db_session.end_time = time.time()
        db.commit()
    return {"status": "ok"}


# --- Debug: View Thought Logs ---

@app.get("/api/sessions/{session_id}/thoughts")
def get_thought_logs(session_id: str, db: DBSessionType = Depends(get_db)):
    """Debug endpoint: view Sally's inner monologue for a session."""
    db_session = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not db_session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        thought_logs = json.loads(db_session.thought_logs or "[]")
    except json.JSONDecodeError:
        thought_logs = []

    try:
        profile = json.loads(db_session.prospect_profile or "{}")
    except json.JSONDecodeError:
        profile = {}

    return {
        "session_id": session_id,
        "current_phase": db_session.current_phase,
        "turn_number": db_session.turn_number,
        "retry_count": db_session.retry_count,
        "prospect_profile": profile,
        "thought_logs": thought_logs,
    }


# --- Config (Stripe + Calendly URLs) ---

@app.get("/api/config")
def get_config():
    """Return client-safe config (Stripe Payment Link + Calendly URL)."""
    return {
        "stripe_payment_link": os.getenv("STRIPE_PAYMENT_LINK", ""),
        "calendly_url": os.getenv("CALENDLY_URL", ""),
    }
