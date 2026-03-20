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

import hashlib
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
from app.bot_router import route_message, get_greeting as bot_get_greeting, BOT_DISPLAY_NAMES
from app.memory import (
    extract_memory_from_session, store_memory,
    load_visitor_memory, format_memory_for_prompt,
)
from app.followup import send_sms
import threading

logger = logging.getLogger("sally.sms")

router = APIRouter()


def _phone_to_visitor_id(phone: str) -> str:
    """Generate a deterministic visitor_id from a phone number."""
    return "sms_" + hashlib.sha256(phone.encode()).hexdigest()[:16]


# --- TwiML Helpers ---

def twiml_reply(message: str) -> Response:
    """Return a TwiML response with one or more <Message> elements."""
    segments = _split_sms(message)
    messages_xml = "".join(f"<Message>{_escape_xml(s)}</Message>" for s in segments)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><Response>{messages_xml}</Response>'
    return Response(content=xml, media_type="application/xml")


def _empty_twiml() -> Response:
    """Return an empty TwiML response (acknowledges receipt, sends no SMS)."""
    xml = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
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
            DBSession.sms_state.in_(["pre_survey", "active", "post_survey", "rating_before_link"]),
        )
        .order_by(DBSession.start_time.desc())
        .first()
    )


# --- Survey Messages ---

PRE_SURVEY_MSG = (
    "Hey! Welcome to 100x. Before we chat, quick question:\n\n"
    "On a scale of 1-10, how interested are you in using AI to improve "
    "your mortgage business?\n\n"
    "Reply with a number from 1 to 10."
)

POST_SURVEY_MSG = (
    "One last question — after our chat, how interested are you NOW in "
    "exploring AI for your mortgage business?\n\n"
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
    upper = message.upper()
    if upper in ("STOP", "END", "QUIT", "CANCEL"):
        session = _find_active_sms_session(db, phone)
        if session:
            session.status = "abandoned"
            session.end_time = time.time()
            session.sms_state = "done"
            db.commit()
            logger.info(f"[SMS] Session {session.id} ended by opt-out")
        return twiml_reply("Got it, conversation ended. Text anytime to start a new one.")

    # --- Check for follow-up pause ---
    if upper == "PAUSE":
        session = _find_active_sms_session(db, phone)
        if session:
            session.followup_paused = "true"
            db.commit()
        return twiml_reply(
            "Got it, I won't send any more follow-ups. "
            "You can still text me anytime to continue our conversation."
        )

    # --- Check for bot switch ---
    if upper.startswith("SWITCH"):
        parts = message.upper().split()
        bot_map = {"SALLY": BotArm.SALLY_NEPQ, "HANK": BotArm.HANK_HYPES, "IVY": BotArm.IVY_INFORMS}

        if len(parts) < 2 or parts[1] not in bot_map:
            return twiml_reply("To switch bots, text: SWITCH SALLY, SWITCH HANK, or SWITCH IVY")

        target_arm = bot_map[parts[1]]
        session = _find_active_sms_session(db, phone)

        if not session:
            return twiml_reply("No active conversation to switch. Text anything to start a new one.")

        if session.sms_state != "active":
            return twiml_reply("Can only switch during an active conversation. Text NEW to start fresh.")

        current_arm = BotArm(session.assigned_arm) if session.assigned_arm else BotArm.SALLY_NEPQ
        if current_arm == target_arm:
            return twiml_reply(f"You're already talking to {BOT_DISPLAY_NAMES[target_arm]}!")

        # Build conversation summary
        messages_db = (
            db.query(DBMessage)
            .filter(DBMessage.session_id == session.id)
            .order_by(DBMessage.timestamp)
            .all()
        )
        summary_lines = []
        for m in messages_db[-20:]:
            role = "User" if m.role == "user" else "Bot"
            content = m.content[:200] + "..." if len(m.content) > 200 else m.content
            summary_lines.append(f"{role}: {content}")
        conversation_summary = "\n".join(summary_lines)
        profile_json = session.prospect_profile or "{}"

        # Inject switch context into prospect profile for Sally to read on first turn
        try:
            profile_data = json.loads(profile_json) if profile_json and profile_json != "{}" else {}
        except (json.JSONDecodeError, Exception):
            profile_data = {}
        profile_data["_switch_context"] = conversation_summary
        enriched_profile_json = json.dumps(profile_data)

        # End current session
        session.status = "switched"
        session.end_time = time.time()
        session.sms_state = "done"

        # Create new session
        new_session_id = str(uuid.uuid4())[:8].upper()
        now = time.time()
        initial_phase = NepqPhase.CONNECTION.value if target_arm == BotArm.SALLY_NEPQ else "CONVERSATION"

        new_session = DBSession(
            id=new_session_id,
            status="active",
            current_phase=initial_phase,
            pre_conviction=session.pre_conviction,
            assigned_arm=target_arm.value,
            visitor_id=session.visitor_id or _phone_to_visitor_id(phone),
            user_id=getattr(session, 'user_id', None),
            phone_number=phone,
            channel="sms",
            sms_state="active",
            experiment_mode=getattr(session, 'experiment_mode', None),
            start_time=now,
            message_count=1,
            retry_count=0,
            turn_number=0,
            prospect_profile=enriched_profile_json,
            thought_logs="[]",
        )
        db.add(new_session)
        db.commit()

        old_session_id = session.id
        target_display = BOT_DISPLAY_NAMES[target_arm]
        current_display = BOT_DISPLAY_NAMES[current_arm]

        logger.info(f"[SMS Switch] {old_session_id} ({current_arm.value}) → {new_session_id} ({target_arm.value})")

        # Generate greeting + send via REST API in background (avoids Twilio timeout)
        threading.Thread(
            target=_switch_greeting_async,
            args=(new_session_id, phone, target_arm, conversation_summary,
                  initial_phase, target_display, current_display),
            daemon=True,
        ).start()

        return _empty_twiml()

    # --- Check for memory reset ---
    if upper == "RESET":
        from app.database import DBMemoryFact, DBSessionSummary

        # End any active session
        session = _find_active_sms_session(db, phone)
        if session:
            session.status = "abandoned"
            session.end_time = time.time()
            session.sms_state = "done"

        # Find visitor_id from any session with this phone number
        any_session = (
            db.query(DBSession)
            .filter(DBSession.phone_number == phone)
            .order_by(DBSession.start_time.desc())
            .first()
        )

        facts_deleted = 0
        summaries_deleted = 0
        if any_session and any_session.visitor_id:
            vid = any_session.visitor_id
            facts_deleted = db.query(DBMemoryFact).filter(DBMemoryFact.visitor_id == vid).delete()
            summaries_deleted = db.query(DBSessionSummary).filter(DBSessionSummary.visitor_id == vid).delete()

        db.commit()

        logger.info(f"[SMS Reset] Phone {phone}: {facts_deleted} facts, {summaries_deleted} summaries deleted")

        return twiml_reply(
            f"Memory cleared ({facts_deleted} facts, {summaries_deleted} notes removed). "
            "Text anything to start completely fresh."
        )

    # --- Find existing session ---
    session = _find_active_sms_session(db, phone)

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

        visitor_id = _phone_to_visitor_id(phone)
        session = DBSession(
            id=session_id,
            status="active",
            current_phase="CONVERSATION",  # Will be updated after arm assignment
            phone_number=phone,
            channel="sms",
            sms_state="pre_survey",
            experiment_mode="true",  # SMS sessions are always experiment mode
            visitor_id=visitor_id,
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
        # User is re-engaged — reset follow-up pause so follow-ups can resume later
        if getattr(session, 'followup_paused', None) == "true":
            session.followup_paused = None
            db.commit()
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

    # --- State: rating_before_link (rate before getting invitation link) ---
    if session.sms_state == "rating_before_link":
        score = _parse_number(message)
        if score is None:
            return twiml_reply(
                "Please reply with a number from 1 to 10 to rate the conversation."
            )

        session.post_conviction = score
        pre = session.pre_conviction or 0
        session.cds_score = score - pre
        session.sms_state = "done"
        session.status = "completed"
        session.end_time = time.time()
        db.commit()

        cds = session.cds_score
        cds_str = f"+{cds}" if cds > 0 else str(cds)
        invitation_url = session.pending_invitation_url or ""
        logger.info(f"[SMS] Session {session.id} CDS={cds_str} (pre={pre}, post={score})")

        return twiml_reply(
            f"Thanks! Your conviction shifted by {cds_str}.\n\n"
            f"Here's where to request your invitation: {invitation_url}\n\n"
            "Text NEW anytime to start a fresh conversation."
        )

    # --- State: done ---
    if session.sms_state == "done":
        return twiml_reply(
            "This conversation has ended. Text NEW to start a fresh one."
        )

    # --- Fallback ---
    return twiml_reply("Something went wrong. Text NEW to start over.")


# --- Async Switch Greeting ---

def _switch_greeting_async(
    new_session_id, phone, target_arm, conversation_summary,
    initial_phase, target_display, current_display,
):
    """Background thread: generate switch greeting via Claude and send via Twilio REST API."""
    SessionLocal = _get_session_local()
    db = SessionLocal()
    try:
        from app.bots.base import get_client as get_anthropic_client

        switch_context = (
            f"[SYSTEM: The user just switched from {current_display} to you via SMS. "
            f"Conversation summary:\n{conversation_summary}\n\n"
            f"Send a brief acknowledgment and continue naturally. 2-3 sentences max. "
            f"Reference something specific from the conversation.]"
        )

        try:
            if target_arm == BotArm.HANK_HYPES:
                from app.bots.hank import HankBot
                bot = HankBot()
            elif target_arm == BotArm.IVY_INFORMS:
                from app.bots.ivy import IvyBot
                bot = IvyBot()
            else:
                bot = None

            if bot:
                resp = get_anthropic_client().messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=200,
                    system=bot.system_prompt,
                    messages=[{"role": "user", "content": switch_context}],
                )
                greeting_text = resp.content[0].text.strip()
            else:
                sally_switch_prompt = (
                    f"You are Sally from 100x. The user just switched to you from another AI assistant via SMS. "
                    f"Here's what they discussed:\n\n{conversation_summary}\n\n"
                    f"Write a brief, warm greeting (2 sentences max) that acknowledges you have context "
                    f"and asks a natural follow-up question based on what they shared. "
                    f"Sound like a friend, not a robot. Keep it short for SMS."
                )
                resp = get_anthropic_client().messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=150,
                    messages=[{"role": "user", "content": sally_switch_prompt}],
                )
                greeting_text = resp.content[0].text.strip()
        except Exception as e:
            logger.error(f"[SMS Switch] Greeting generation failed: {e}")
            greeting_text = f"Hey, I'm {target_display}. I've got context from your chat — let's continue."

        # Save greeting to DB
        greeting_msg = DBMessage(
            id=str(uuid.uuid4()),
            session_id=new_session_id,
            role="assistant",
            content=greeting_text,
            timestamp=time.time(),
            phase=initial_phase,
        )
        db.add(greeting_msg)
        db.commit()

        # Send via Twilio REST API
        send_sms(phone, f"Switched to {target_display}.\n\n{greeting_text}")
        logger.info(f"[SMS Switch] Greeting sent for session {new_session_id}")

    except Exception as e:
        logger.error(f"[SMS Switch] Async greeting error: {e}", exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        try:
            send_sms(phone, f"Switched to {target_display}. How can I help?")
        except Exception:
            pass
    finally:
        db.close()


# --- Active Message Processing ---

def _handle_active_message(session: DBSession, message: str, db: DBSessionType) -> Response:
    """
    Accept user message, save to DB, then process bot response asynchronously.

    Returns an empty TwiML immediately (within ~100ms) to avoid Twilio's
    15-second webhook timeout. The actual bot reply is sent via Twilio REST API
    in a background thread.
    """
    now = time.time()
    session_id = session.id
    current_phase_str = session.current_phase

    # Save user message immediately (fast DB write)
    user_msg = DBMessage(
        id=str(uuid.uuid4()),
        session_id=session_id,
        role="user",
        content=message,
        timestamp=now,
        phase=current_phase_str,
    )
    db.add(user_msg)
    session.message_count += 1
    session.turn_number += 1
    db.commit()

    # Capture all values needed by background thread (avoid DetachedInstanceError)
    thread_args = dict(
        session_id=session_id,
        phone=session.phone_number,
        message=message,
        visitor_id=session.visitor_id,
        user_id=getattr(session, 'user_id', None),
        assigned_arm=session.assigned_arm,
        current_phase_str=current_phase_str,
        prospect_profile=session.prospect_profile or "{}",
        start_time=session.start_time,
        retry_count=session.retry_count,
        turn_number=session.turn_number,
        thought_logs=session.thought_logs,
        consecutive_no_new_info=getattr(session, 'consecutive_no_new_info', 0) or 0,
        turns_in_current_phase=getattr(session, 'turns_in_current_phase', 0) or 0,
        deepest_emotional_depth=getattr(session, 'deepest_emotional_depth', 'surface') or 'surface',
        objection_diffusion_step=getattr(session, 'objection_diffusion_step', 0) or 0,
        ownership_substep=getattr(session, 'ownership_substep', 0) or 0,
        msg_timestamp=now,
    )

    threading.Thread(
        target=_process_and_reply_async,
        kwargs=thread_args,
        daemon=True,
    ).start()

    logger.info(f"[SMS:{session_id}] Accepted message, processing async")
    return _empty_twiml()


def _send_sms_segments(phone: str, text: str):
    """Send a message via Twilio REST API, splitting long texts into segments."""
    segments = _split_sms(text)
    for segment in segments:
        send_sms(phone, segment)


def _process_and_reply_async(
    session_id, phone, message, visitor_id, user_id,
    assigned_arm, current_phase_str, prospect_profile,
    start_time, retry_count, turn_number, thought_logs,
    consecutive_no_new_info, turns_in_current_phase,
    deepest_emotional_depth, objection_diffusion_step,
    ownership_substep, msg_timestamp,
):
    """Background thread: generate bot response and send via Twilio REST API."""
    SessionLocal = _get_session_local()
    db = SessionLocal()
    try:
        session = db.query(DBSession).filter(DBSession.id == session_id).first()
        if not session:
            logger.error(f"[SMS:{session_id}] Session not found in async worker")
            return

        arm = BotArm(assigned_arm) if assigned_arm else BotArm.SALLY_NEPQ
        is_sally = arm == BotArm.SALLY_NEPQ
        current_phase = NepqPhase(current_phase_str) if current_phase_str in [p.value for p in NepqPhase] else None

        # Detect return-after-gap for resumption context
        last_msg = (
            db.query(DBMessage)
            .filter(DBMessage.session_id == session_id, DBMessage.role == "assistant")
            .order_by(DBMessage.timestamp.desc())
            .first()
        )
        gap_seconds = msg_timestamp - last_msg.timestamp if last_msg else 0
        gap_hours = gap_seconds / 3600

        resumption_context = ""
        if gap_hours >= 1:
            gap_str = f"{int(gap_hours)} hours" if gap_hours < 48 else f"{int(gap_hours / 24)} days"
            resumption_context = (
                f"\n\n[SYSTEM NOTE: The user is returning after {gap_str} of silence. "
                f"They were previously in the {current_phase_str} phase. "
                f"Acknowledge the gap naturally (e.g., 'hey, good to hear from you again') "
                f"and continue where you left off. Do NOT restart the conversation from scratch. "
                f"Reference what you were discussing before.]"
            )
            logger.info(f"[SMS:{session_id}] User returning after {gap_str} gap")

        # Load memory context
        memory_block = ""
        if visitor_id or user_id:
            try:
                visitor_memory = load_visitor_memory(
                    db, visitor_id or "", user_id=user_id
                )
                memory_block = format_memory_for_prompt(visitor_memory)
            except Exception as e:
                logger.error(f"[SMS:{session_id}] Memory load failed: {e}")
                db.rollback()
                session = db.query(DBSession).filter(DBSession.id == session_id).first()

        # Check for _switch_context in prospect profile (one-time injection after bot switch)
        try:
            profile_data = json.loads(session.prospect_profile or "{}")
            switch_ctx = profile_data.pop("_switch_context", None)
            if switch_ctx:
                switch_block = "[PRIOR CONVERSATION CONTEXT:\n" + switch_ctx + "]"
                memory_block = (memory_block + "\n\n" + switch_block) if memory_block else switch_block
                session.prospect_profile = json.dumps(profile_data)
        except (json.JSONDecodeError, Exception):
            pass

        # Combine memory + resumption context
        full_context = memory_block
        if resumption_context:
            full_context = (memory_block + resumption_context) if memory_block else resumption_context

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

        # Route through bot engine
        logger.info(f"[SMS:{session_id}] Async: routing to {arm.value}, turn {turn_number}")
        route_start = time.monotonic()

        try:
            result = route_message(
                arm=arm,
                user_message=message,
                conversation_history=conversation_history,
                memory_context=full_context,
                current_phase=current_phase or NepqPhase.CONNECTION,
                profile_json=session.prospect_profile or "{}",
                retry_count=retry_count,
                turn_number=turn_number,
                conversation_start_time=start_time,
                consecutive_no_new_info=consecutive_no_new_info,
                turns_in_current_phase=turns_in_current_phase,
                deepest_emotional_depth=deepest_emotional_depth,
                objection_diffusion_step=objection_diffusion_step,
                ownership_substep=ownership_substep,
                session_id=session_id,
                channel="sms",
            )
        except Exception as e:
            logger.error(f"[SMS:{session_id}] Async engine error: {e}")
            result = {
                "response_text": "Sorry, I had a hiccup. Could you say that again?",
                "new_phase": current_phase_str,
                "new_profile_json": session.prospect_profile or "{}",
                "thought_log_json": "{}",
                "phase_changed": False,
                "session_ended": False,
                "retry_count": retry_count + 1,
                "consecutive_no_new_info": 0,
                "turns_in_current_phase": 0,
                "deepest_emotional_depth": "surface",
                "objection_diffusion_step": 0,
                "ownership_substep": 0,
            }

        route_ms = (time.monotonic() - route_start) * 1000
        logger.info(f"[SMS:{session_id}] route_message completed in {route_ms:.0f}ms")

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

        # Replace [INVITATION_LINK] with tracked URL (invitation pages work fine in SMS)
        if "[INVITATION_LINK]" in response_text:
            from app.invitation import build_invitation_url
            invitation_url = build_invitation_url(
                session_id=session_id,
                arm=arm,
                channel="sms",
            )
            response_text = response_text.replace("[INVITATION_LINK]", invitation_url)

        # Track invitation link sent
        from app.invitation import INVITATION_URL as _INVITATION_BASE
        if _INVITATION_BASE.lower() in response_text.lower() and not getattr(session, 'invitation_link_sent', None):
            session.invitation_link_sent = "true"
            session.invitation_link_sent_at = time.time()
            logger.info(f"[SMS] Session {session_id}: invitation link sent")

        # Check session end
        if result["session_ended"]:
            from app.invitation import INVITATION_URL as _INV_BASE

            # Check if response contains invitation link — gate behind rating
            has_invitation = _INV_BASE.lower() in response_text.lower()

            if has_invitation:
                # Strip the invitation URL from the message text
                invitation_url_match = re.search(r'https?://[^\s]*100x\.inc/academy/[^\s]*', response_text)
                saved_url = invitation_url_match.group(0) if invitation_url_match else ""
                response_text = re.sub(r'https?://[^\s]*100x\.inc/academy/[^\s]*', '', response_text).strip()
                # Clean up orphaned link text like "Here's the link: " with no URL
                response_text = re.sub(r':\s*$', '.', response_text)

                session.pending_invitation_url = saved_url
                session.sms_state = "rating_before_link"
                # Don't set status=completed yet — wait for rating
            else:
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

            # Send final bot message + rating/survey prompt
            rating_prompt = (
                "Before I share the link — on a scale of 1-10, how would you "
                "rate this conversation?\n\nReply with a number from 1 to 10."
            ) if has_invitation else POST_SURVEY_MSG
            _send_sms_segments(phone, f"{response_text}\n\n---\n\n{rating_prompt}")

            # Trigger memory extraction in background
            _trigger_memory_extraction(session, messages, message, result, new_phase_str)
            return

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

        # Send response via Twilio REST API
        success = send_sms(phone, response_text)
        logger.info(f"[SMS:{session_id}] Async reply sent via REST API (success={success})")

    except Exception as e:
        logger.error(f"[SMS:{session_id}] Async worker error: {e}", exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        # Send fallback so user isn't left hanging
        try:
            send_sms(phone, "Sorry, I ran into an issue. Could you try sending that again?")
        except Exception:
            pass
    finally:
        db.close()


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


# --- Health Check ---

@router.get("/api/sms/health")
async def sms_health():
    """Quick health check for SMS subsystem — verifies required env vars are set."""
    import os
    checks = {
        "twilio_sid_set": bool(os.getenv("TWILIO_ACCOUNT_SID")),
        "twilio_token_set": bool(os.getenv("TWILIO_AUTH_TOKEN")),
        "twilio_phone_set": bool(os.getenv("TWILIO_PHONE_NUMBER")),
        "anthropic_key_set": bool(os.getenv("ANTHROPIC_API_KEY")),
    }
    all_ok = all(checks.values())
    return {"status": "ok" if all_ok else "missing_config", "checks": checks}
