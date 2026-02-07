from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict
import uuid

from .schemas import (
    Session,
    NepqPhase,
    SessionStatus,
    CreateSessionRequest,
    CreateSessionResponse,
    SendMessageRequest,
    SendMessageResponse,
    SessionResponse,
    ChatMessage,
)
from .agent import SallyEngine


app = FastAPI(
    title="Sally Sells API",
    description="NEPQ Sales Agent Backend",
    version="1.0.0"
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session storage (replace with database later)
sessions: Dict[str, Session] = {}
engines: Dict[str, SallyEngine] = {}


@app.get("/")
def root():
    return {"status": "ok", "service": "Sally Sells API"}


@app.post("/api/sessions", response_model=CreateSessionResponse)
def create_session(request: CreateSessionRequest = None):
    """Create a new chat session"""
    session_id = str(uuid.uuid4())[:8].upper()
    
    session = Session(
        id=session_id,
        pre_conviction=request.pre_conviction if request else None
    )
    
    engine = SallyEngine(session)
    greeting = engine.get_greeting()
    
    # Add greeting as first message
    greeting_msg = ChatMessage(
        role="assistant",
        content=greeting,
        phase=session.current_phase
    )
    session.messages.append(greeting_msg)
    
    # Store session and engine
    sessions[session_id] = session
    engines[session_id] = engine
    
    return CreateSessionResponse(
        session_id=session_id,
        current_phase=session.current_phase,
        greeting=greeting
    )


@app.post("/api/sessions/{session_id}/messages", response_model=SendMessageResponse)
def send_message(session_id: str, request: SendMessageRequest):
    """Send a message in a session"""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    engine = engines[session_id]
    
    if session.status != SessionStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Session is not active")
    
    # Process the message
    response_text, phase_changed, session_ended = engine.process_message(request.content)
    
    # Get the assistant's message (last one added)
    assistant_message = session.messages[-1]
    
    return SendMessageResponse(
        message=assistant_message,
        current_phase=session.current_phase,
        phase_changed=phase_changed,
        session_ended=session_ended
    )


@app.get("/api/sessions/{session_id}", response_model=SessionResponse)
def get_session(session_id: str):
    """Get session details"""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    return SessionResponse(
        id=session.id,
        status=session.status,
        current_phase=session.current_phase,
        messages=session.messages,
        start_time=session.start_time,
        end_time=session.end_time
    )


@app.get("/api/sessions")
def list_sessions():
    """List all sessions"""
    return {
        "sessions": [
            {
                "id": s.id,
                "status": s.status,
                "current_phase": s.current_phase,
                "message_count": len(s.messages),
                "start_time": s.start_time,
            }
            for s in sessions.values()
        ]
    }


@app.delete("/api/sessions/{session_id}")
def end_session(session_id: str):
    """End a session"""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    
    session = sessions[session_id]
    session.status = SessionStatus.ABANDONED
    
    return {"status": "ended", "session_id": session_id}


# Dashboard metrics endpoint
@app.get("/api/metrics")
def get_metrics():
    """Get dashboard metrics"""
    all_sessions = list(sessions.values())
    completed = [s for s in all_sessions if s.status == SessionStatus.COMPLETED]
    active = [s for s in all_sessions if s.status == SessionStatus.ACTIVE]
    
    # Calculate failure modes (sessions that didn't reach COMMITMENT)
    failure_modes = {}
    for s in all_sessions:
        if s.status != SessionStatus.COMPLETED or s.current_phase != NepqPhase.TERMINATED:
            phase = s.current_phase.value
            failure_modes[phase] = failure_modes.get(phase, 0) + 1
    
    return {
        "total_sessions": len(all_sessions),
        "active_sessions": len(active),
        "completed_sessions": len(completed),
        "conversion_rate": len(completed) / len(all_sessions) * 100 if all_sessions else 0,
        "failure_modes": [
            {"phase": phase, "count": count}
            for phase, count in failure_modes.items()
        ]
    }