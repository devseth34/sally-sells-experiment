"""
Sally Sells — Twilio SMS Integration

Handles inbound SMS via Twilio webhook. Routes conversations through
the same bot engine as web chat, with a text-based pre/post survey flow.

SMS State Machine:
- pre_survey: waiting for conviction score (1-10)
- active: conversation in progress
- post_survey: waiting for post-conviction score (1-10)
- done: conversation complete
"""

import logging
import random
import time
import uuid
import json
import re

from fastapi import APIRouter, Form, Depends, Response
from sqlalchemy.orm import Session as DBSessionType

from app.database import get_db, DBSession, DBMessage, _get_session_local
from app.schemas import NepqPhase, BotArm
from app.bot_router import route_message, get_greeting as bot_get_greeting
from app.memory import (
    extract_memory_from_session, store_memory,
    load_visitor_memory, format_memory_for_prompt,
)
import threading

logger = logging.getLogger("sally.sms")

router = APIRouter()


# --- TwiML Helpers ---

def twiml_reply(message: str) -> Response:
    """Return a TwiML response with one or more <Message> elements."""
    segments = _split_sms(message)
    messages_xml = "".join(f"<Message>{_escape_xml(s)}</Message>" for s in segments)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><Response>{messages_xml}</Response>'
    return Response(content=xml, media_type="application/xml")


def _split_sms(text: str, max_len: int = 1500) -> list[str]:
    """Split a long message into SMS-friendly segments."""
    if len(text) <= max_len:
        return [text]

    segments = []
    while text:
        if len(text) <= max_len:
            segments.append(text)
            break
        # Find a good break point (sentence end or space)
        break_at = text.rfind('. ', 0, max_len)
        if break_at == -1:
            break_at = text.rfind(' ', 0, max_len)
        if break_at == -1:
            break_at = max_len
        else:
            break_at += 1  # Include the space/period
        segments.append(text[:break_at].strip())
        text = text[break_at:].strip()

    return segments


def _escape_xml(text: str) -> str:
    """Escape XML special characters in message text."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


# --- Session Lookup by Phone ---

def _find_active_sms_session(db: DBSessionType, phone: str) -> DBSession | None:
    """Find the most recent non-done SMS session for this phone number."""
    return (
        db.query(DBSession)
        .filter(
            DBSession.phone_number == phone,
            DBSession.channel == "sms",
            DBSession.sms_state.in_(["pre_survey", "active", "post_survey"]),
        )
        .order_by(DBSession.start_time.desc())
        .first()
    )


# --- Survey Messages ---

PRE_SURVEY_MSG = (
    "Hey! Welcome to 100x. Before we chat, quick question:\n\n"
    "On a scale of 1-10, how likely are you to invest in a $10,000 AI program "
    "for your business today?\n\n"
    "Reply with a number from 1 to 10."
)

POST_SURVEY_MSG = (
    "One last question — after our chat, how likely are you NOW to invest in a "
    "$10,000 AI program for your business?\n\n"
    "Reply with a number from 1 to 10."
)


def _parse_number(text: str) -> int | None:
    """Try to parse a 1-10 number from the message."""
    text = text.strip()
    # Direct number
    if text.isdigit() and 1 <= int(text) <= 10:
        return int(text)
    # Number at start of message
    match = re.match(r'^(\d{1,2})\b', text)
    if match:
        n = int(match.group(1))
        if 1 <= n <= 10:
            return n
    return None


# --- Timeout Handling ---

TIMEOUT_SECONDS = 86400  # 24 hours


def _check_and_handle_timeout(db: DBSessionType, session: DBSession) -> bool:
    """
    If session has been inactive for >24 hours, mark it abandoned.
    Returns True if session was timed out.
    """
    if session.sms_state == "active":
        last_activity = session.start_time
        # Check last message timestamp
        last_msg = (
            db.query(DBMessage)
            .filter(DBMessage.session_id == session.id)
            .order_by(DBMessage.timestamp.desc())
            .first()
        )
        if last_msg:
            last_activity = last_msg.timestamp

        if time.time() - last_activity > TIMEOUT_SECONDS:
            session.status = "abandoned"
            session.end_time = time.time()
            session.sms_state = "done"
            db.commit()
            logger.info(f"[SMS] Session {session.id} timed out after 24h inactivity")
            return True

    return False


# --- The Webhook ---

@router.post("/api/sms/webhook")
async def sms_webhook(
    From: str = Form(...),
    Body: str = Form(...),
    To: str = Form(default=""),
    db: DBSessionType = Depends(get_db),
):
    """
    Twilio webhook for inbound SMS.

    Routes SMS through the same bot engine as web chat.
    Manages a text-based state machine for pre/post surveys.
    """
    phone = From.strip()
    message = Body.strip()

    logger.info(f"[SMS] Incoming from {phone}: '{message[:100]}'")

    # --- Check for opt-out ---
    if message.upper() in ("STOP", "END", "QUIT", "CANCEL"):
        session = _find_active_sms_session(db, phone)
        if session:
            session.status = "abandoned"
            session.end_time = time.time()
            session.sms_state = "done"
            db.commit()
            logger.info(f"[SMS] Session {session.id} ended by opt-out")
        return twiml_reply("Got it, conversation ended. Text anytime to start a new one.")

    # --- Find existing session ---
    session = _find_active_sms_session(db, phone)

    # --- Check for session timeout ---
    if session and _check_and_handle_timeout(db, session):
        session = None  # Force new session creation

    # --- Check for "NEW" restart ---
    if message.upper() == "NEW":
        if session:
            session.status = "abandoned"
            session.end_time = time.time()
            session.sms_state = "done"
            db.commit()
        session = None  # Force new session creation below

    # --- No active session: create one ---
    if session is None:
        session_id = str(uuid.uuid4())[:8].upper()
        now = time.time()

        session = DBSession(
            id=session_id,
            status="active",
            current_phase="CONVERSATION",  # Will be updated after arm assignment
            phone_number=phone,
            channel="sms",
            sms_state="pre_survey",
            experiment_mode="true",  # SMS sessions are always experiment mode
            start_time=now,
            message_count=0,
            retry_count=0,
            turn_number=0,
            prospect_profile="{}",
            thought_logs="[]",
        )
        db.add(session)
        db.commit()

        logger.info(f"[SMS] New session {session_id} for {phone}")
        return twiml_reply(PRE_SURVEY_MSG)

    # --- State: pre_survey ---
    if session.sms_state == "pre_survey":
        score = _parse_number(message)
        if score is None:
            return twiml_reply(
                "Please reply with a number from 1 to 10.\n\n"
                "1 = not at all likely, 10 = extremely likely"
            )

        # Store pre-conviction and randomly assign arm
        arm = random.choice([BotArm.SALLY_NEPQ, BotArm.HANK_HYPES, BotArm.IVY_INFORMS])
        initial_phase = NepqPhase.CONNECTION.value if arm == BotArm.SALLY_NEPQ else "CONVERSATION"

        session.pre_conviction = score
        session.assigned_arm = arm.value
        session.current_phase = initial_phase
        session.sms_state = "active"

        # Get the bot's greeting
        greeting = bot_get_greeting(arm)

        # Save greeting as a message
        greeting_msg = DBMessage(
            id=str(uuid.uuid4()),
            session_id=session.id,
            role="assistant",
            content=greeting,
            timestamp=time.time(),
            phase=initial_phase,
        )
        db.add(greeting_msg)
        session.message_count += 1
        db.commit()

        logger.info(f"[SMS] Session {session.id} assigned to {arm.value}, pre_conviction={score}")
        return twiml_reply(f"Thanks! Score recorded.\n\n{greeting}")

    # --- State: active ---
    if session.sms_state == "active":
        return _handle_active_message(session, message, db)

    # --- State: post_survey ---
    if session.sms_state == "post_survey":
        score = _parse_number(message)
        if score is None:
            return twiml_reply(
                "Please reply with a number from 1 to 10 for your post-chat score."
            )

        session.post_conviction = score
        pre = session.pre_conviction or 0
        session.cds_score = score - pre
        session.sms_state = "done"
        db.commit()

        cds = session.cds_score
        cds_str = f"+{cds}" if cds > 0 else str(cds)
        logger.info(f"[SMS] Session {session.id} CDS={cds_str} (pre={pre}, post={score})")

        return twiml_reply(
            f"Thanks for participating! Your conviction shifted by {cds_str}.\n\n"
            "Text NEW anytime to start a fresh conversation."
        )

    # --- State: done ---
    if session.sms_state == "done":
        return twiml_reply(
            "This conversation has ended. Text NEW to start a fresh one."
        )

    # --- Fallback ---
    return twiml_reply("Something went wrong. Text NEW to start over.")


# --- Active Message Processing ---

def _handle_active_message(session: DBSession, message: str, db: DBSessionType) -> Response:
    """
    Process a message during an active SMS conversation.
    Reuses the same bot routing logic as the web chat endpoint.
    """
    now = time.time()
    session_id = session.id
    arm = BotArm(session.assigned_arm) if session.assigned_arm else BotArm.SALLY_NEPQ
    is_sally = arm == BotArm.SALLY_NEPQ

    current_phase_str = session.current_phase
    current_phase = NepqPhase(current_phase_str) if current_phase_str in [p.value for p in NepqPhase] else None

    # Load memory context
    memory_block = ""
    if session.visitor_id or getattr(session, 'user_id', None):
        try:
            visitor_memory = load_visitor_memory(
                db, session.visitor_id or "", user_id=getattr(session, 'user_id', None)
            )
            memory_block = format_memory_for_prompt(visitor_memory)
        except Exception as e:
            logger.error(f"[SMS:{session_id}] Memory load failed: {e}")
            db.rollback()
            session = db.query(DBSession).filter(DBSession.id == session_id).first()

    # Save user message
    user_msg = DBMessage(
        id=str(uuid.uuid4()),
        session_id=session_id,
        role="user",
        content=message,
        timestamp=now,
        phase=current_phase.value if current_phase else current_phase_str,
    )
    db.add(user_msg)
    session.message_count += 1
    session.turn_number += 1

    # Build conversation history
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
    conversation_history.append({"role": "user", "content": message})

    # Route through bot engine
    logger.info(f"[SMS:{session_id}] Turn {session.turn_number} in {current_phase_str} (arm={arm.value})")

    try:
        result = route_message(
            arm=arm,
            user_message=message,
            conversation_history=conversation_history,
            memory_context=memory_block,
            current_phase=current_phase or NepqPhase.CONNECTION,
            profile_json=session.prospect_profile or "{}",
            retry_count=session.retry_count,
            turn_number=session.turn_number,
            conversation_start_time=session.start_time,
            consecutive_no_new_info=getattr(session, 'consecutive_no_new_info', 0) or 0,
            turns_in_current_phase=getattr(session, 'turns_in_current_phase', 0) or 0,
            deepest_emotional_depth=getattr(session, 'deepest_emotional_depth', 'surface') or 'surface',
            objection_diffusion_step=getattr(session, 'objection_diffusion_step', 0) or 0,
            ownership_substep=getattr(session, 'ownership_substep', 0) or 0,
        )
    except Exception as e:
        logger.error(f"[SMS:{session_id}] Engine error: {e}")
        result = {
            "response_text": "Could you tell me more about that?",
            "new_phase": current_phase_str,
            "new_profile_json": session.prospect_profile or "{}",
            "thought_log_json": "{}",
            "phase_changed": False,
            "session_ended": False,
            "retry_count": session.retry_count + 1,
            "consecutive_no_new_info": 0,
            "turns_in_current_phase": 0,
            "deepest_emotional_depth": "surface",
            "objection_diffusion_step": 0,
            "ownership_substep": 0,
        }

    # Update session state
    new_phase_str = result["new_phase"]
    session.current_phase = new_phase_str

    if is_sally:
        session.retry_count = result["retry_count"]
        session.prospect_profile = result["new_profile_json"]
        if hasattr(session, 'consecutive_no_new_info'):
            session.consecutive_no_new_info = result.get("consecutive_no_new_info", 0)
        if hasattr(session, 'turns_in_current_phase'):
            session.turns_in_current_phase = result.get("turns_in_current_phase", 0)
        if hasattr(session, 'deepest_emotional_depth'):
            session.deepest_emotional_depth = result.get("deepest_emotional_depth", "surface")
        if hasattr(session, 'objection_diffusion_step'):
            session.objection_diffusion_step = result.get("objection_diffusion_step", 0)
        if hasattr(session, 'ownership_substep'):
            session.ownership_substep = result.get("ownership_substep", 0)

        # Thought logs
        try:
            existing_logs = json.loads(session.thought_logs or "[]")
            new_log = json.loads(result["thought_log_json"])
            existing_logs.append(new_log)
            session.thought_logs = json.dumps(existing_logs)
        except (json.JSONDecodeError, Exception):
            pass

    # Get the response text
    response_text = result["response_text"]

    # Strip payment link placeholders (don't work well in SMS)
    if "[PAYMENT_LINK]" in response_text:
        response_text = response_text.replace("[PAYMENT_LINK]", "[link will be sent separately]")

    # Check session end
    if result["session_ended"]:
        session.status = "completed"
        session.end_time = time.time()
        session.sms_state = "post_survey"

        # Save bot response
        bot_msg = DBMessage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role="assistant",
            content=response_text,
            timestamp=time.time(),
            phase=new_phase_str,
        )
        db.add(bot_msg)
        session.message_count += 1
        db.commit()

        # Trigger memory extraction in background
        _trigger_memory_extraction(session, messages, message, result, new_phase_str)

        # Send final bot message + post survey
        return twiml_reply(f"{response_text}\n\n---\n\n{POST_SURVEY_MSG}")

    # Save bot response
    bot_msg = DBMessage(
        id=str(uuid.uuid4()),
        session_id=session_id,
        role="assistant",
        content=response_text,
        timestamp=time.time(),
        phase=new_phase_str,
    )
    db.add(bot_msg)
    session.message_count += 1
    db.commit()

    return twiml_reply(response_text)


def _trigger_memory_extraction(session, messages, user_message, result, new_phase_str):
    """Fire-and-forget memory extraction after session ends."""
    if not (session.visitor_id or getattr(session, 'user_id', None)):
        return

    try:
        mem_sid = session.id
        mem_vid = session.visitor_id or ""
        mem_uid = getattr(session, 'user_id', None)
        mem_arm = session.assigned_arm or "unknown"
        mem_profile = session.prospect_profile or "{}"
        mem_transcript = [
            {"role": m.role, "content": m.content, "phase": m.phase}
            for m in messages
        ]
        mem_transcript.append({"role": "user", "content": user_message, "phase": session.current_phase})
        mem_transcript.append({"role": "assistant", "content": result["response_text"], "phase": new_phase_str})

        def _run():
            try:
                extraction = extract_memory_from_session(
                    session_id=mem_sid, visitor_id=mem_vid,
                    transcript=mem_transcript, profile_json=mem_profile,
                    outcome="completed", final_phase=new_phase_str, bot_arm=mem_arm,
                )
                if extraction:
                    store_memory(
                        db_session_maker=_get_session_local(),
                        session_id=mem_sid, visitor_id=mem_vid,
                        extraction=extraction, user_id=mem_uid, bot_arm=mem_arm,
                    )
            except Exception as e:
                logger.error(f"[SMS:{mem_sid}] Memory extraction failed: {e}")

        threading.Thread(target=_run, daemon=True).start()
    except Exception as e:
        logger.error(f"[SMS:{session.id}] Memory extraction thread launch failed: {e}")
