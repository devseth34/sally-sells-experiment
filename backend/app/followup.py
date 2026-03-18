"""
Sally Sells — SMS Follow-Up Sequencing

Background worker that checks for stale SMS sessions and sends
persona-appropriate follow-up messages via Twilio outbound SMS.

Follow-up intervals by bot personality:
- Hank (aggressive): every 12 hours
- Sally (empathetic): every 24 hours
- Ivy (patient): every 48 hours

Max 3 follow-ups per session. Stops if user texts PAUSE.
"""

import os
import time
import json
import uuid
import logging
import threading
from typing import Optional

from twilio.rest import Client as TwilioClient
from anthropic import Anthropic

from app.database import DBSession, DBMessage, _get_session_local
from app.schemas import BotArm

logger = logging.getLogger("sally.followup")

# --- Configuration ---

FOLLOWUP_CONFIG = {
    BotArm.HANK_HYPES.value: {
        "interval_hours": 12,
        "max_followups": 3,
        "persona": "hank",
    },
    BotArm.SALLY_NEPQ.value: {
        "interval_hours": 24,
        "max_followups": 3,
        "persona": "sally",
    },
    BotArm.IVY_INFORMS.value: {
        "interval_hours": 48,
        "max_followups": 3,
        "persona": "ivy",
    },
}

# --- Follow-Up Message Generation Prompts ---

FOLLOWUP_PROMPTS = {
    "hank": """You are Hank, a high-energy aggressive sales AI for 100x.
You're following up with someone who stopped responding to your conversation via SMS.

CONVERSATION SO FAR:
{transcript_summary}

THEIR SITUATION: {profile_summary}

LAST MESSAGE WAS: {last_message}
TIME SINCE LAST MESSAGE: {gap_description}
THIS IS FOLLOW-UP #{followup_number} OF 3.

Write a SHORT follow-up SMS (2-3 sentences max) in Hank's style:
- Energetic, persistent, friendly but pushy
- Reference something specific from the conversation
- Create urgency or FOMO
- Ask a direct question to get them re-engaged
- If follow-up #2 or #3, escalate the urgency slightly
- Keep it casual and text-like (this is SMS, not email)

IMPORTANT: Do NOT re-introduce yourself. They know who you are. Jump straight into the follow-up.""",

    "sally": """You are Sally, an empathetic NEPQ sales consultant for 100x.
You're following up with someone who stopped responding to your conversation via SMS.

CONVERSATION SO FAR:
{transcript_summary}

THEIR SITUATION: {profile_summary}
CURRENT NEPQ PHASE: {current_phase}

LAST MESSAGE WAS: {last_message}
TIME SINCE LAST MESSAGE: {gap_description}
THIS IS FOLLOW-UP #{followup_number} OF 3.

Write a SHORT follow-up SMS (2-3 sentences max) in Sally's NEPQ style:
- Warm, understanding, zero pressure
- Reference something specific they shared (a pain point, their situation, what they were exploring)
- Show you remember and care about their specific situation
- Ask a thoughtful question relevant to where they were in the conversation
- If in early phases (CONNECTION/SITUATION): casual check-in, reference what you were discussing
- If in PROBLEM_AWARENESS/CONSEQUENCE: reference the specific pain they shared, ask how things have been
- If in OWNERSHIP/COMMITMENT: gentle reminder, no pressure, reference their interest

IMPORTANT: Do NOT re-introduce yourself. Do NOT pitch. Sound like a friend checking in, not a salesperson following up.""",

    "ivy": """You are Ivy, a neutral information assistant for 100x.
You're following up with someone who stopped responding to your conversation via SMS.

CONVERSATION SO FAR:
{transcript_summary}

THEIR SITUATION: {profile_summary}

LAST MESSAGE WAS: {last_message}
TIME SINCE LAST MESSAGE: {gap_description}
THIS IS FOLLOW-UP #{followup_number} OF 3.

Write a SHORT follow-up SMS (1-2 sentences max) in Ivy's neutral style:
- Purely informational, zero persuasion
- Mention you're available if they have more questions
- If they had asked about something specific, reference it
- Very brief and non-intrusive

IMPORTANT: Do NOT try to sell. Do NOT create urgency. Just a neutral availability reminder.""",
}

# --- Twilio Client (lazy init) ---

_twilio_client: Optional[TwilioClient] = None


def _get_twilio_client() -> TwilioClient:
    global _twilio_client
    if _twilio_client is None:
        sid = os.getenv("TWILIO_ACCOUNT_SID")
        token = os.getenv("TWILIO_AUTH_TOKEN")
        if not sid or not token:
            raise RuntimeError("TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN required for follow-ups")
        _twilio_client = TwilioClient(sid, token)
    return _twilio_client


# --- Anthropic Client (lazy init) ---

_anthropic_client: Optional[Anthropic] = None


def _get_anthropic_client() -> Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY required for follow-up message generation")
        _anthropic_client = Anthropic(api_key=api_key)
    return _anthropic_client


# --- Message Generation ---

def generate_followup_message(
    arm: str,
    transcript_summary: str,
    profile_summary: str,
    last_message: str,
    gap_description: str,
    followup_number: int,
    current_phase: str = "CONVERSATION",
) -> str:
    """Generate a persona-appropriate follow-up message using Claude."""
    config = FOLLOWUP_CONFIG.get(arm)
    if not config:
        return ""

    prompt_template = FOLLOWUP_PROMPTS[config["persona"]]
    prompt = prompt_template.format(
        transcript_summary=transcript_summary,
        profile_summary=profile_summary,
        last_message=last_message,
        gap_description=gap_description,
        followup_number=followup_number,
        current_phase=current_phase,
    )

    try:
        response = _get_anthropic_client().messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        # Strip quotes if Claude wrapped the message in quotes
        if text.startswith('"') and text.endswith('"'):
            text = text[1:-1]
        return text
    except Exception as e:
        logger.error(f"Follow-up message generation failed: {e}")
        return ""


def _build_transcript_summary(messages: list, max_messages: int = 10) -> str:
    """Build a compact transcript summary from recent messages."""
    recent = messages[-max_messages:] if len(messages) > max_messages else messages
    lines = []
    for m in recent:
        role = "Bot" if m.role == "assistant" else "User"
        content = m.content[:150] + "..." if len(m.content) > 150 else m.content
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _build_profile_summary(profile_json: str) -> str:
    """Build a compact profile summary from prospect profile JSON."""
    try:
        profile = json.loads(profile_json or "{}")
    except json.JSONDecodeError:
        return "No profile data available"

    parts = []
    if profile.get("name"):
        parts.append(f"Name: {profile['name']}")
    if profile.get("role"):
        parts.append(f"Role: {profile['role']}")
    if profile.get("company"):
        parts.append(f"Company: {profile['company']}")
    if profile.get("industry"):
        parts.append(f"Industry: {profile['industry']}")
    if profile.get("pain_points"):
        parts.append(f"Pain points: {', '.join(profile['pain_points'])}")
    if profile.get("desired_state"):
        parts.append(f"Desired state: {profile['desired_state']}")
    if profile.get("cost_of_inaction"):
        parts.append(f"Cost of inaction: {profile['cost_of_inaction']}")

    return "; ".join(parts) if parts else "No profile data available"


# --- Send SMS ---

def send_sms(to: str, body: str) -> bool:
    """Send an outbound SMS via Twilio."""
    if not to or len(to) < 11 or to.startswith("+141555") or to.startswith("+1555"):
        logger.warning(f"[Followup] Blocked SMS to invalid/test number: {to}")
        return False

    from_number = os.getenv("TWILIO_PHONE_NUMBER")
    if not from_number:
        logger.error("TWILIO_PHONE_NUMBER not set — cannot send follow-up")
        return False

    try:
        client = _get_twilio_client()
        message = client.messages.create(
            body=body,
            from_=from_number,
            to=to,
        )
        logger.info(f"Follow-up SMS sent: {message.sid} to {to}")
        return True
    except Exception as e:
        logger.error(f"Failed to send follow-up SMS to {to}: {e}")
        return False


# --- The Worker ---

def check_and_send_followups():
    """
    Check all active SMS sessions for follow-up eligibility and send messages.
    Called periodically by the background scheduler.
    """
    SessionLocal = _get_session_local()
    db = SessionLocal()

    try:
        now = time.time()

        # Find all active SMS sessions that might need follow-ups
        active_sessions = (
            db.query(DBSession)
            .filter(
                DBSession.channel == "sms",
                DBSession.sms_state == "active",
                DBSession.status == "active",
                DBSession.phone_number.isnot(None),
            )
            .all()
        )

        for session in active_sessions:
            try:
                _process_session_followup(db, session, now)
            except Exception as e:
                logger.error(f"[Followup] Error processing session {session.id}: {e}")
                db.rollback()

    except Exception as e:
        logger.error(f"[Followup] Worker error: {e}")
    finally:
        db.close()


def _process_session_followup(db, session: DBSession, now: float):
    """Check if a single session needs a follow-up and send it."""
    arm = session.assigned_arm or "sally_nepq"
    config = FOLLOWUP_CONFIG.get(arm)
    if not config:
        return

    # Skip if follow-ups are paused
    if session.followup_paused == "true":
        return

    # Skip if max follow-ups reached
    followup_count = session.followup_count or 0
    if followup_count >= config["max_followups"]:
        return

    # Skip fake/test phone numbers
    phone = session.phone_number or ""
    if not phone or len(phone) < 11:
        logger.debug(f"[Followup] Skipping session {session.id}: invalid phone {phone}")
        return
    # Known test number prefixes (automated test suite uses +141555XXXX)
    test_prefixes = ("+141555", "+1555", "+100000", "+14155500", "+14155501")
    if any(phone.startswith(p) for p in test_prefixes):
        logger.debug(f"[Followup] Skipping session {session.id}: test phone number {phone}")
        return

    # Find the last message (from either party)
    last_msg = (
        db.query(DBMessage)
        .filter(DBMessage.session_id == session.id)
        .order_by(DBMessage.timestamp.desc())
        .first()
    )
    if not last_msg:
        return

    # Only follow up if the last message was from the BOT (user hasn't replied)
    if last_msg.role != "assistant":
        return

    # Check if enough time has passed since last message or last follow-up
    last_activity = last_msg.timestamp
    if session.last_followup_at and session.last_followup_at > last_activity:
        last_activity = session.last_followup_at

    hours_since = (now - last_activity) / 3600
    if hours_since < config["interval_hours"]:
        return  # Not time yet

    # --- Time for a follow-up ---
    logger.info(
        f"[Followup] Session {session.id} ({arm}): "
        f"{hours_since:.1f}h since last activity, sending follow-up #{followup_count + 1}"
    )

    # Build context for message generation
    all_messages = (
        db.query(DBMessage)
        .filter(DBMessage.session_id == session.id)
        .order_by(DBMessage.timestamp)
        .all()
    )

    transcript_summary = _build_transcript_summary(all_messages)
    profile_summary = _build_profile_summary(session.prospect_profile)

    gap_hours = (now - last_msg.timestamp) / 3600
    if gap_hours < 24:
        gap_description = f"{int(gap_hours)} hours ago"
    else:
        gap_description = f"{int(gap_hours / 24)} days ago"

    # Generate follow-up message
    followup_text = generate_followup_message(
        arm=arm,
        transcript_summary=transcript_summary,
        profile_summary=profile_summary,
        last_message=last_msg.content[:200],
        gap_description=gap_description,
        followup_number=followup_count + 1,
        current_phase=session.current_phase,
    )

    if not followup_text:
        logger.warning(f"[Followup] Session {session.id}: empty follow-up generated, skipping")
        return

    # Send the SMS
    if not send_sms(session.phone_number, followup_text):
        return  # Failed to send, try again next cycle

    # Save the follow-up as a message in the DB
    followup_msg = DBMessage(
        id=str(uuid.uuid4()),
        session_id=session.id,
        role="assistant",
        content=followup_text,
        timestamp=now,
        phase=session.current_phase,
    )
    db.add(followup_msg)
    session.message_count = (session.message_count or 0) + 1

    # Update follow-up tracking
    session.followup_count = followup_count + 1
    session.last_followup_at = now
    db.commit()

    logger.info(f"[Followup] Session {session.id} ({arm}): follow-up #{followup_count + 1} sent successfully")


# --- Background Scheduler ---

_worker_running = False


def start_followup_worker(interval_seconds: int = 300):
    """
    Start the follow-up worker as a background daemon thread.
    Checks every `interval_seconds` (default: 5 minutes).
    """
    global _worker_running
    if _worker_running:
        logger.info("[Followup] Worker already running")
        return

    _worker_running = True

    def _run():
        logger.info(f"[Followup] Worker started (checking every {interval_seconds}s)")
        while True:
            try:
                check_and_send_followups()
            except Exception as e:
                logger.error(f"[Followup] Worker cycle error: {e}")
            time.sleep(interval_seconds)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    logger.info("[Followup] Background worker thread started")
