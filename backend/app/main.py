from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session as DBSessionType
from sqlalchemy import func
import uuid
import time

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

app = FastAPI(title="Sally Sells API", version="1.0.0")

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
    return {"status": "ok", "service": "Sally Sells API"}


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
        messages_in_current_phase=0,
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
            id=greeting_id, role="assistant", content=greeting_text,
            timestamp=now, phase=NepqPhase.CONNECTION.value,
        ),
    )


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

    user_msg_id = str(uuid.uuid4())
    user_msg = DBMessage(
        id=user_msg_id, session_id=session_id, role="user",
        content=request.content, timestamp=now, phase=current_phase.value,
    )
    db.add(user_msg)

    db_session.messages_in_current_phase += 1
    db_session.message_count += 1

    phase_changed = False
    if SallyEngine.should_transition(current_phase, db_session.messages_in_current_phase):
        next_phase = SallyEngine.get_next_phase(current_phase)
        if next_phase != current_phase:
            db_session.current_phase = next_phase.value
            db_session.messages_in_current_phase = 0
            current_phase = next_phase
            phase_changed = True

    session_ended = current_phase == NepqPhase.TERMINATED
    if session_ended:
        db_session.status = "completed"
        db_session.end_time = now

    response_text = SallyEngine.generate_response(current_phase, request.content)
    assistant_msg_id = str(uuid.uuid4())
    assistant_msg = DBMessage(
        id=assistant_msg_id, session_id=session_id, role="assistant",
        content=response_text, timestamp=time.time(), phase=current_phase.value,
    )
    db.add(assistant_msg)
    db_session.message_count += 1
    db.commit()

    return SendMessageResponse(
        user_message=MessageResponse(
            id=user_msg_id, role="user", content=request.content,
            timestamp=now, phase=previous_phase.value,
        ),
        assistant_message=MessageResponse(
            id=assistant_msg_id, role="assistant", content=response_text,
            timestamp=assistant_msg.timestamp, phase=current_phase.value,
        ),
        current_phase=current_phase.value,
        previous_phase=previous_phase.value,
        phase_changed=phase_changed,
        session_ended=session_ended,
    )


@app.get("/api/sessions/{session_id}", response_model=SessionDetailResponse)
def get_session(session_id: str, db: DBSessionType = Depends(get_db)):
    db_session = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not db_session:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = db.query(DBMessage).filter(DBMessage.session_id == session_id).order_by(DBMessage.timestamp).all()
    return SessionDetailResponse(
        id=db_session.id, status=db_session.status, current_phase=db_session.current_phase,
        pre_conviction=db_session.pre_conviction, post_conviction=db_session.post_conviction,
        start_time=db_session.start_time, end_time=db_session.end_time,
        messages=[MessageResponse(id=m.id, role=m.role, content=m.content, timestamp=m.timestamp, phase=m.phase) for m in messages],
    )


@app.get("/api/sessions", response_model=list[SessionListItem])
def list_sessions(db: DBSessionType = Depends(get_db)):
    sessions = db.query(DBSession).order_by(DBSession.start_time.desc()).all()
    return [
        SessionListItem(
            id=s.id, status=s.status, current_phase=s.current_phase,
            pre_conviction=s.pre_conviction, message_count=s.message_count,
            start_time=s.start_time, end_time=s.end_time,
        )
        for s in sessions
    ]


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
        count = db.query(DBSession).filter(DBSession.status == "abandoned", DBSession.current_phase == phase.value).count()
        if count > 0:
            failure_modes.append({"phase": phase.value, "count": count})

    return MetricsResponse(
        total_sessions=total, active_sessions=active, completed_sessions=completed,
        abandoned_sessions=abandoned, average_pre_conviction=round(avg_conviction, 1) if avg_conviction else None,
        conversion_rate=round(conversion_rate, 1), phase_distribution=phase_dist, failure_modes=failure_modes,
    )


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