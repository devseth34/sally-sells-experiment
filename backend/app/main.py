"""
Sally Sells — FastAPI Application

Three-layer architecture: Comprehension -> Decision -> Response pipeline.
Persists prospect profile and thought logs per session.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session as DBSessionType
from sqlalchemy import func
import uuid
import time
import json
import csv
import io
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import os
import stripe
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
    PostConvictionRequest,
    PostConvictionResponse,
)
from .agent import SallyEngine
from .sheets_logger import fire_sheets_log
from .quality_scorer import score_conversation
import threading

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
    t0 = time.monotonic()
    init_db()
    ms = (time.monotonic() - t0) * 1000
    logger.info(f"on_startup: init_db completed in {ms:.0f}ms")


@app.get("/")
def root():
    return {"status": "ok", "service": "Sally Sells API", "version": "2.0.0", "engine": "three-layer-nepq"}


# --- Sheets Logging Helper ---

def _serialize_for_sheets(db_session, db, extra_user_msg: dict | None = None) -> tuple[dict, list[dict]]:
    """Serialize session + messages into plain dicts for the sheets logger thread."""
    try:
        profile = json.loads(db_session.prospect_profile or "{}")
    except json.JSONDecodeError:
        profile = {}

    session_data = {
        "id": db_session.id,
        "status": db_session.status,
        "current_phase": db_session.current_phase,
        "pre_conviction": db_session.pre_conviction,
        "post_conviction": db_session.post_conviction,
        "cds_score": db_session.cds_score,
        "message_count": db_session.message_count,
        "turn_number": db_session.turn_number,
        "start_time": db_session.start_time,
        "end_time": db_session.end_time,
        "escalation_sent": db_session.escalation_sent,
        "prospect_profile": profile,
    }

    all_msgs = (
        db.query(DBMessage)
        .filter(DBMessage.session_id == db_session.id)
        .order_by(DBMessage.timestamp)
        .all()
    )
    messages_data = [
        {"role": m.role, "content": m.content, "phase": m.phase, "timestamp": m.timestamp}
        for m in all_msgs
    ]
    if extra_user_msg:
        messages_data.append(extra_user_msg)

    return session_data, messages_data


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
            consecutive_no_new_info=getattr(db_session, 'consecutive_no_new_info', 0) or 0,
            turns_in_current_phase=getattr(db_session, 'turns_in_current_phase', 0) or 0,
            deepest_emotional_depth=getattr(db_session, 'deepest_emotional_depth', 'surface') or 'surface',
            objection_diffusion_step=getattr(db_session, 'objection_diffusion_step', 0) or 0,
            ownership_substep=getattr(db_session, 'ownership_substep', 0) or 0,
        )
    except Exception as e:
        logger.error(f"[Session {session_id}] Engine error: {e}")
        result = {
            "response_text": "How has that been playing out for you day-to-day?",
            "new_phase": current_phase.value,
            "new_profile_json": db_session.prospect_profile or "{}",
            "thought_log_json": json.dumps({"error": str(e)}),
            "phase_changed": False,
            "session_ended": False,
            "retry_count": db_session.retry_count + 1,
            "consecutive_no_new_info": getattr(db_session, 'consecutive_no_new_info', 0) or 0,
            "turns_in_current_phase": getattr(db_session, 'turns_in_current_phase', 0) or 0,
            "deepest_emotional_depth": getattr(db_session, 'deepest_emotional_depth', 'surface') or 'surface',
            "objection_diffusion_step": getattr(db_session, 'objection_diffusion_step', 0) or 0,
            "ownership_substep": getattr(db_session, 'ownership_substep', 0) or 0,
        }

    # Update session state
    new_phase = NepqPhase(result["new_phase"])
    db_session.current_phase = new_phase.value
    db_session.retry_count = result["retry_count"]
    db_session.prospect_profile = result["new_profile_json"]
    # Track all state counters
    if hasattr(db_session, 'consecutive_no_new_info'):
        db_session.consecutive_no_new_info = result.get("consecutive_no_new_info", 0)
    if hasattr(db_session, 'turns_in_current_phase'):
        db_session.turns_in_current_phase = result.get("turns_in_current_phase", 0)
    if hasattr(db_session, 'deepest_emotional_depth'):
        db_session.deepest_emotional_depth = result.get("deepest_emotional_depth", "surface")
    if hasattr(db_session, 'objection_diffusion_step'):
        db_session.objection_diffusion_step = result.get("objection_diffusion_step", 0)
    if hasattr(db_session, 'ownership_substep'):
        db_session.ownership_substep = result.get("ownership_substep", 0)

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

        # Google Sheets: log completed session
        try:
            _sd, _md = _serialize_for_sheets(
                db_session, db,
                extra_user_msg={"role": "user", "content": request.content, "phase": current_phase.value, "timestamp": now},
            )
            fire_sheets_log("session", _sd, _md)
        except Exception as e:
            logger.error(f"[Session {session_id}] Sheets log (completed) error: {e}")

        # Async quality scoring (fire-and-forget via daemon thread)
        try:
            # Snapshot data for the scorer thread (avoid DB session sharing across threads)
            all_msgs_for_scoring = [
                {"role": m.role, "content": m.content, "phase": m.phase}
                for m in messages
            ]
            # Add the current user message (not yet in the DB query result)
            all_msgs_for_scoring.append({"role": "user", "content": request.content, "phase": current_phase.value})
            # Add Sally's response (use result dict since response_text variable is defined later)
            all_msgs_for_scoring.append({"role": "assistant", "content": result["response_text"], "phase": new_phase.value})

            thought_logs_for_scoring = list(existing_logs)  # already parsed above
            scoring_session_id = session_id

            def _run_quality_scoring():
                try:
                    quality_result = score_conversation(all_msgs_for_scoring, thought_logs_for_scoring)
                    logger.info(f"[Session {scoring_session_id}] Quality score: "
                                f"mirror={quality_result.mirroring_score}, "
                                f"energy={quality_result.energy_matching_score}, "
                                f"structure={quality_result.structure_score}, "
                                f"arc={quality_result.emotional_arc_score}, "
                                f"overall={quality_result.overall_score}")
                    # Store result in DB
                    from .database import SessionLocal
                    scoring_db = SessionLocal()
                    try:
                        s = scoring_db.query(DBSession).filter(DBSession.id == scoring_session_id).first()
                        if s:
                            # Store quality score as JSON in a field (we'll add it to thought_logs for now)
                            try:
                                logs = json.loads(s.thought_logs or "[]")
                            except json.JSONDecodeError:
                                logs = []
                            logs.append({"quality_score": quality_result.model_dump()})
                            s.thought_logs = json.dumps(logs)
                            scoring_db.commit()
                    finally:
                        scoring_db.close()
                except Exception as e:
                    logger.error(f"[Session {scoring_session_id}] Quality scoring failed: {e}")

            t = threading.Thread(target=_run_quality_scoring, daemon=True)
            t.start()
        except Exception as e:
            logger.error(f"[Session {session_id}] Quality scoring thread launch failed: {e}")

    # Gmail escalation: trigger when entering OWNERSHIP (first time only)
    if new_phase == NepqPhase.OWNERSHIP and previous_phase != NepqPhase.OWNERSHIP and not db_session.escalation_sent:
        try:
            profile_for_email = json.loads(db_session.prospect_profile or "{}")
            all_msgs = (
                db.query(DBMessage)
                .filter(DBMessage.session_id == session_id)
                .order_by(DBMessage.timestamp)
                .all()
            )
            transcript_lines = []
            for m in all_msgs:
                role_label = "Sally" if m.role == "assistant" else "Prospect"
                transcript_lines.append(f"[{m.phase}] {role_label}: {m.content}")
            transcript_lines.append(f"[{current_phase.value}] Prospect: {request.content}")
            transcript_text = "\n".join(transcript_lines)

            sent = _send_escalation_email(session_id, profile_for_email, transcript_text)
            if sent:
                db_session.escalation_sent = time.time()

            # Google Sheets: log hot lead
            _sd, _md = _serialize_for_sheets(
                db_session, db,
                extra_user_msg={"role": "user", "content": request.content, "phase": current_phase.value, "timestamp": now},
            )
            fire_sheets_log("hot_lead", _sd, _md)
        except Exception as e:
            logger.error(f"[Session {session_id}] Escalation trigger error: {e}")

    # Replace [PAYMENT_LINK] placeholder with real Stripe checkout URL if present
    response_text = result["response_text"]
    if "[PAYMENT_LINK]" in response_text:
        try:
            stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
            if stripe.api_key:
                price_id = _get_or_create_stripe_price()
                profile_for_checkout = json.loads(db_session.prospect_profile or "{}")
                metadata = {
                    "sally_session_id": session_id,
                    "prospect_name": profile_for_checkout.get("name", ""),
                    "prospect_company": profile_for_checkout.get("company", ""),
                    "prospect_role": profile_for_checkout.get("role", ""),
                }
                prospect_email = profile_for_checkout.get("email")
                frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
                checkout_params = {
                    "mode": "payment",
                    "line_items": [{"price": price_id, "quantity": 1}],
                    "success_url": f"{frontend_url}/booking/{session_id}?payment=success&checkout_session_id={{CHECKOUT_SESSION_ID}}",
                    "cancel_url": f"{frontend_url}/booking/{session_id}?payment=cancelled",
                    "metadata": metadata,
                }
                if prospect_email:
                    checkout_params["customer_email"] = prospect_email
                checkout_session = stripe.checkout.Session.create(**checkout_params)
                response_text = response_text.replace("[PAYMENT_LINK]", checkout_session.url)
        except Exception as e:
            logger.error(f"[Session {session_id}] Failed to create checkout for inline link: {e}")
            response_text = response_text.replace("[PAYMENT_LINK]", os.getenv("STRIPE_PAYMENT_LINK", ""))

    # Save assistant message
    assistant_msg_id = str(uuid.uuid4())
    assistant_msg = DBMessage(
        id=assistant_msg_id,
        session_id=session_id,
        role="assistant",
        content=response_text,
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
            content=response_text,
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
            post_conviction=s.post_conviction,
            cds_score=s.cds_score,
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
    avg_cds = db.query(func.avg(DBSession.cds_score)).filter(DBSession.cds_score.isnot(None)).scalar()
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
        average_cds=round(avg_cds, 1) if avg_cds else None,
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

        # Google Sheets: log abandoned session
        try:
            _sd, _md = _serialize_for_sheets(db_session, db)
            fire_sheets_log("session", _sd, _md)
        except Exception as e:
            logger.error(f"[Session {session_id}] Sheets log (abandoned) error: {e}")

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


# --- Quality Scoring (on-demand) ---

@app.post("/api/sessions/{session_id}/quality-score")
def run_quality_score(session_id: str, db: DBSessionType = Depends(get_db)):
    """Run or re-run quality scoring for a completed session."""
    db_session = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not db_session:
        raise HTTPException(status_code=404, detail="Session not found")
    if db_session.status not in ("completed", "abandoned"):
        raise HTTPException(status_code=400, detail="Session must be completed or abandoned to score")

    # Get messages
    all_messages = (
        db.query(DBMessage)
        .filter(DBMessage.session_id == session_id)
        .order_by(DBMessage.timestamp)
        .all()
    )
    messages_data = [
        {"role": m.role, "content": m.content, "phase": m.phase}
        for m in all_messages
    ]

    # Get thought logs
    try:
        thought_logs = json.loads(db_session.thought_logs or "[]")
    except json.JSONDecodeError:
        thought_logs = []

    # Run scoring
    quality_result = score_conversation(messages_data, thought_logs)

    # Store result
    try:
        logs = json.loads(db_session.thought_logs or "[]")
    except json.JSONDecodeError:
        logs = []

    # Remove any previous quality_score entries
    logs = [log for log in logs if not (isinstance(log, dict) and "quality_score" in log)]
    logs.append({"quality_score": quality_result.model_dump()})
    db_session.thought_logs = json.dumps(logs)
    db.commit()

    return quality_result.model_dump()


# --- Config (Stripe + TidyCal) ---

@app.get("/api/config")
def get_config():
    """Return client-safe config (Stripe keys + TidyCal path)."""
    return {
        "stripe_payment_link": os.getenv("STRIPE_PAYMENT_LINK", ""),
        "stripe_publishable_key": os.getenv("STRIPE_PUBLISHABLE_KEY", ""),
        "tidycal_path": os.getenv("TIDYCAL_PATH", ""),
    }


# --- Stripe Checkout ---

# Lazy-init: create Stripe product/price on first checkout
_stripe_price_id: str | None = None


def _get_or_create_stripe_price() -> str:
    """Get or create the $10,000 Discovery Workshop price in Stripe."""
    global _stripe_price_id
    if _stripe_price_id:
        return _stripe_price_id

    stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
    if not stripe.api_key:
        raise RuntimeError("STRIPE_SECRET_KEY not set")

    # Search for existing product by name
    products = stripe.Product.search(query='name~"100x AI Discovery Workshop"', limit=1)
    if products.data:
        product = products.data[0]
        # Get the default price or first active price
        prices = stripe.Price.list(product=product.id, active=True, limit=1)
        if prices.data:
            _stripe_price_id = prices.data[0].id
            logger.info(f"Stripe: using existing price {_stripe_price_id}")
            return _stripe_price_id

    # Create product + price
    product = stripe.Product.create(
        name="100x AI Discovery Workshop",
        description="Nik Shah, CEO of 100x, comes onsite to build a customized AI plan helping you save $5M annually.",
    )
    price = stripe.Price.create(
        product=product.id,
        unit_amount=1000000,  # $10,000 in cents
        currency="usd",
    )
    _stripe_price_id = price.id
    logger.info(f"Stripe: created product {product.id} with price {price.id}")
    return _stripe_price_id


@app.post("/api/checkout")
def create_checkout_session(
    session_id: str | None = None,
    db: DBSessionType = Depends(get_db),
):
    """Create a Stripe Checkout Session for the $10,000 Discovery Workshop."""
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="Stripe not configured")

    price_id = _get_or_create_stripe_price()

    # Build metadata from the Sally session if available
    metadata = {}
    prospect_email = None
    if session_id:
        db_session = db.query(DBSession).filter(DBSession.id == session_id).first()
        if db_session:
            try:
                profile = json.loads(db_session.prospect_profile or "{}")
                metadata = {
                    "sally_session_id": session_id,
                    "prospect_name": profile.get("name", ""),
                    "prospect_company": profile.get("company", ""),
                    "prospect_role": profile.get("role", ""),
                }
                prospect_email = profile.get("email")
            except json.JSONDecodeError:
                metadata = {"sally_session_id": session_id}

    # Determine success/cancel URLs
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")

    checkout_params = {
        "mode": "payment",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": f"{frontend_url}/booking/{session_id or 'direct'}?payment=success&checkout_session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{frontend_url}/booking/{session_id or 'direct'}?payment=cancelled",
        "metadata": metadata,
    }

    if prospect_email:
        checkout_params["customer_email"] = prospect_email

    checkout_session = stripe.checkout.Session.create(**checkout_params)

    return {
        "checkout_url": checkout_session.url,
        "session_id": checkout_session.id,
    }


@app.get("/api/checkout/verify/{checkout_session_id}")
def verify_payment(checkout_session_id: str):
    """Verify a Stripe Checkout Session payment status."""
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="Stripe not configured")

    try:
        session = stripe.checkout.Session.retrieve(checkout_session_id)
    except stripe.InvalidRequestError:
        raise HTTPException(status_code=404, detail="Checkout session not found")

    metadata = dict(session.metadata) if session.metadata else {}
    customer_email = session.customer_details.email if session.customer_details else None

    # Log conversion to Google Sheets when payment is confirmed
    if session.payment_status == "paid":
        try:
            fire_sheets_log("conversion", {
                "sally_session_id": metadata.get("sally_session_id", ""),
                "checkout_session_id": checkout_session_id,
                "payment_status": "paid",
                "amount": f"${session.amount_total / 100:,.0f}" if session.amount_total else "",
                "currency": (session.currency or "").upper(),
                "customer_email": customer_email or "",
                "prospect_name": metadata.get("prospect_name", ""),
                "prospect_company": metadata.get("prospect_company", ""),
                "prospect_role": metadata.get("prospect_role", ""),
            })
        except Exception as e:
            logger.error(f"Sheets conversion log error: {e}")

    return {
        "payment_status": session.payment_status,
        "status": session.status,
        "customer_email": customer_email,
        "amount_total": session.amount_total,
        "currency": session.currency,
        "metadata": metadata,
    }


# --- Post-Conviction + CDS Score ---

@app.post("/api/sessions/{session_id}/post-conviction", response_model=PostConvictionResponse)
def submit_post_conviction(session_id: str, request: PostConvictionRequest, db: DBSessionType = Depends(get_db)):
    """Submit post-chat conviction score and compute CDS (Conviction Delta Score)."""
    db_session = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not db_session:
        raise HTTPException(status_code=404, detail="Session not found")

    db_session.post_conviction = request.post_conviction
    pre = db_session.pre_conviction or 0
    cds = request.post_conviction - pre
    db_session.cds_score = cds
    db.commit()

    return PostConvictionResponse(
        session_id=session_id,
        pre_conviction=db_session.pre_conviction,
        post_conviction=request.post_conviction,
        cds_score=cds,
    )


# --- CSV Export ---

@app.get("/api/export/csv")
def export_csv(db: DBSessionType = Depends(get_db)):
    """Export all sessions + transcripts as a CSV for research analysis."""
    sessions = db.query(DBSession).order_by(DBSession.start_time.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "session_id", "status", "final_phase", "pre_conviction", "post_conviction",
        "cds_score", "message_count", "turn_number", "start_time", "end_time",
        "duration_seconds", "prospect_name", "prospect_role", "prospect_company",
        "objections_encountered", "transcript",
    ])

    for s in sessions:
        # Parse profile for prospect info
        try:
            profile = json.loads(s.prospect_profile or "{}")
        except json.JSONDecodeError:
            profile = {}

        # Build transcript
        messages = (
            db.query(DBMessage)
            .filter(DBMessage.session_id == s.id)
            .order_by(DBMessage.timestamp)
            .all()
        )
        transcript_lines = []
        for m in messages:
            role_label = "Sally" if m.role == "assistant" else "Prospect"
            transcript_lines.append(f"[{m.phase}] {role_label}: {m.content}")
        transcript = "\n".join(transcript_lines)

        duration = None
        if s.end_time and s.start_time:
            duration = round(s.end_time - s.start_time)

        writer.writerow([
            s.id,
            s.status,
            s.current_phase,
            s.pre_conviction,
            s.post_conviction,
            s.cds_score,
            s.message_count,
            s.turn_number,
            s.start_time,
            s.end_time,
            duration,
            profile.get("name", ""),
            profile.get("role", ""),
            profile.get("company", ""),
            "; ".join(profile.get("objections_encountered", [])),
            transcript,
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sally_sells_export.csv"},
    )


# --- Gmail Escalation ---

def _send_escalation_email(session_id: str, profile: dict, transcript: str) -> bool:
    """Send escalation email with full transcript when prospect reaches OWNERSHIP."""
    gmail_user = os.getenv("GMAIL_USER")
    gmail_app_password = os.getenv("GMAIL_APP_PASSWORD")
    escalation_to = os.getenv("ESCALATION_EMAIL")

    if not all([gmail_user, gmail_app_password, escalation_to]):
        logger.warning(f"[Session {session_id}] Gmail escalation skipped — missing GMAIL_USER, GMAIL_APP_PASSWORD, or ESCALATION_EMAIL in .env")
        return False

    prospect_name = profile.get("name", "Unknown")
    prospect_company = profile.get("company", "Unknown")
    prospect_role = profile.get("role", "Unknown")

    subject = f"Sally Sells Escalation — {prospect_name} ({prospect_company})"

    body = f"""QUALIFIED LEAD — OWNERSHIP PHASE REACHED

Prospect: {prospect_name}
Role: {prospect_role}
Company: {prospect_company}
Session ID: {session_id}

Pain Points: {', '.join(profile.get('pain_points', ['N/A']))}
Objections: {', '.join(profile.get('objections_encountered', ['None']))}

--- FULL TRANSCRIPT ---

{transcript}
"""

    msg = MIMEMultipart()
    msg["From"] = gmail_user
    msg["To"] = escalation_to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_app_password)
            server.sendmail(gmail_user, escalation_to, msg.as_string())
        logger.info(f"[Session {session_id}] Escalation email sent to {escalation_to}")
        return True
    except Exception as e:
        logger.error(f"[Session {session_id}] Escalation email failed: {e}")
        return False
