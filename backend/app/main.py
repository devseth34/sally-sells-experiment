"""
Sally Sells — FastAPI Application

Three-layer architecture: Comprehension -> Decision -> Response pipeline.
Persists prospect profile and thought logs per session.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session as DBSessionType
from sqlalchemy import func, case
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
from typing import Optional
from .database import get_db, DBSession, DBMessage, DBUser, init_db
from .schemas import (
    NepqPhase,
    BotArm,
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
    ResumeSessionResponse,
    RegisterRequest,
    LoginRequest,
    AuthResponse,
    IdentifyRequest,
    IdentifyResponse,
)
from .auth import (
    register_user,
    login_user,
    create_token,
    get_optional_user,
    get_required_user,
    merge_visitor_memory_to_user,
    find_user_by_name_and_phone,
)
from .agent import SallyEngine
from .bot_router import route_message, get_greeting as bot_get_greeting, BOT_DISPLAY_NAMES
from .sheets_logger import fire_sheets_log
from .quality_scorer import score_conversation
from .memory import extract_memory_from_session, store_memory, load_visitor_memory, format_memory_for_prompt, load_recent_conversation_context
from .sms import router as sms_router
from .followup import start_followup_worker
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

app.include_router(sms_router)


@app.on_event("startup")
def on_startup():
    t0 = time.monotonic()
    init_db()
    ms = (time.monotonic() - t0) * 1000
    logger.info(f"on_startup: init_db completed in {ms:.0f}ms")

    # Log whether optional integrations are configured
    if os.getenv("GOOGLE_SHEETS_WEBHOOK_URL"):
        logger.info("Google Sheets logging: ENABLED")
    else:
        logger.warning("Google Sheets logging: DISABLED (GOOGLE_SHEETS_WEBHOOK_URL not set)")

    # Start SMS follow-up worker (checks every 5 minutes)
    if os.getenv("TWILIO_ACCOUNT_SID") and os.getenv("TWILIO_AUTH_TOKEN"):
        start_followup_worker(interval_seconds=300)
        logger.info("SMS follow-up worker: ENABLED")
    else:
        logger.warning("SMS follow-up worker: DISABLED (TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN not set)")


@app.get("/")
def root():
    return {"status": "ok", "service": "Sally Sells API", "version": "2.0.0", "engine": "three-layer-nepq"}


@app.post("/api/debug/trigger-followups")
def trigger_followups():
    """Debug: manually trigger the follow-up check cycle."""
    from .followup import check_and_send_followups
    check_and_send_followups()
    return {"status": "ok", "message": "Follow-up check completed"}


@app.post("/api/debug/cleanup-test-sessions")
def cleanup_test_sessions(db: DBSessionType = Depends(get_db)):
    """Mark all fake test phone number sessions as done so follow-up worker ignores them."""
    import time as _time
    count = (
        db.query(DBSession)
        .filter(
            DBSession.channel == "sms",
            DBSession.phone_number.like("+141555%"),
            DBSession.sms_state != "done",
        )
        .update({
            DBSession.sms_state: "done",
            DBSession.status: "abandoned",
            DBSession.end_time: _time.time(),
        }, synchronize_session="fetch")
    )
    db.commit()
    return {"status": "ok", "test_sessions_cleaned": count}


# --- Authentication ---

@app.post("/api/auth/register", response_model=AuthResponse)
def register(request: RegisterRequest, db: DBSessionType = Depends(get_db)):
    """Register a new user account."""
    user = register_user(
        db=db,
        email=request.email,
        password=request.password,
        display_name=request.display_name,
        phone=request.phone,
    )

    # Merge anonymous visitor memory if visitor_id provided
    if request.visitor_id:
        merge_visitor_memory_to_user(db, request.visitor_id, user.id)

    token = create_token(user.id, user.email)
    return AuthResponse(
        token=token,
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
    )


@app.post("/api/auth/login", response_model=AuthResponse)
def login(request: LoginRequest, db: DBSessionType = Depends(get_db)):
    """Login with email and password."""
    user = login_user(db, request.email, request.password)

    # Merge anonymous visitor memory if visitor_id provided
    if request.visitor_id:
        merge_visitor_memory_to_user(db, request.visitor_id, user.id)

    token = create_token(user.id, user.email)
    return AuthResponse(
        token=token,
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
    )


@app.get("/api/auth/me")
def get_current_user(user: DBUser = Depends(get_required_user)):
    """Get current authenticated user info."""
    return {
        "user_id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "phone": user.phone,
    }


@app.post("/api/auth/identify", response_model=IdentifyResponse)
def identify_by_name_phone(request: IdentifyRequest, db: DBSessionType = Depends(get_db)):
    """
    Identify a non-authenticated user by name + phone.
    If a matching user is found, link the visitor to that user's memory.
    If no match, create a lightweight user record for future matching.
    """
    existing_user = find_user_by_name_and_phone(db, request.full_name, request.phone)

    if existing_user:
        # Found a match — merge visitor memory
        if request.visitor_id:
            merge_visitor_memory_to_user(db, request.visitor_id, existing_user.id)

        # Check if they have memory
        from .database import DBMemoryFact
        user_facts = db.query(DBMemoryFact).filter(
            DBMemoryFact.user_id == existing_user.id,
            DBMemoryFact.is_active == 1,
        ).count()

        has_mem = user_facts > 0
        if not has_mem and request.visitor_id:
            try:
                memory = load_visitor_memory(db, request.visitor_id)
                has_mem = memory.get("has_memory", False)
            except Exception:
                pass

        return IdentifyResponse(
            identified=True,
            user_id=existing_user.id,
            display_name=existing_user.display_name,
            has_memory=has_mem,
        )
    else:
        # No match — create a lightweight user record (no password, can't login)
        import re
        normalized_phone = re.sub(r'[\s\-\(\)\+]', '', request.phone.strip())

        new_user = DBUser(
            id=str(uuid.uuid4()),
            email=f"anon_{uuid.uuid4().hex[:8]}@placeholder.local",
            password_hash="",  # empty = can't login with password
            display_name=request.full_name.strip(),
            phone=normalized_phone,
            created_at=time.time(),
        )
        db.add(new_user)
        db.commit()

        # Link visitor memory to this new user
        if request.visitor_id:
            merge_visitor_memory_to_user(db, request.visitor_id, new_user.id)

        return IdentifyResponse(
            identified=False,
            user_id=new_user.id,
            display_name=new_user.display_name,
            has_memory=False,
        )


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


# --- Memory-Aware Greeting ---

def _extract_name_from_context(recent_context: str) -> str | None:
    """
    Try to extract the visitor's name from raw conversation context.
    Looks for common patterns like "I'm [Name]", "my name is [Name]",
    or the assistant addressing them by name.
    """
    import re

    # Pattern 1: Prospect self-introduction
    # "I'm Dev", "I am Sarah", "my name is Alex", "this is John", "it's Mike"
    # Also handles: "hey sally im John" (words between greeting and intro)
    match = re.search(
        r"Prospect:\s*.*?(?:I'm|I am|my name is|this is|it's|im)\s+([A-Z][a-zA-Z]+)",
        recent_context,
        re.IGNORECASE,
    )
    if match:
        candidate = match.group(1)
        # Filter out common words that aren't names
        non_names = {
            "there", "everyone", "all", "again", "back", "sure", "great",
            "well", "so", "what", "how", "interested", "looking", "here",
            "just", "really", "very", "actually", "also", "curious",
        }
        if candidate.lower() not in non_names:
            return candidate

    # Pattern 2: Sally addresses them by name
    # "Nice to meet you, Dev!" or "Hey Dev," or "Thanks Dev"
    match = re.search(
        r"Sally:.*?(?:nice to meet you|hey|hi|hello|thanks|welcome back|good to see you)[,!]?\s+([A-Z][a-zA-Z]+)[!,.\s]",
        recent_context,
        re.IGNORECASE,
    )
    if match:
        candidate = match.group(1)
        non_names = {
            "there", "everyone", "all", "again", "back", "sure", "great",
            "well", "so", "what", "how", "too", "and", "the", "that",
        }
        if candidate.lower() not in non_names:
            return candidate

    return None


def _generate_greeting_from_context(arm: BotArm, recent_context: str) -> str | None:
    """
    Generate a personalized greeting using raw conversation context when
    structured memory (memory_facts) is not yet available.

    This handles the race condition where memory extraction daemon hasn't
    completed, but we still have the full conversation transcript from
    DBMessage records (populated synchronously during conversation).
    """
    if arm == BotArm.SALLY_NEPQ:
        from .bots.base import get_client
        try:
            prompt = (
                "You are Sally, a warm and empathetic sales agent for 100x Academy. "
                "A visitor you've talked to before is starting a new chat. "
                "Below is their last conversation with you.\n\n"
                f"{recent_context}\n\n"
                "Based on this conversation, write a SHORT (2-3 sentences max) greeting that:\n"
                "- Uses their name if you can find it in the conversation\n"
                "- References ONE specific thing from the conversation (a pain point, something they were excited about, their situation)\n"
                "- Feels like a friend picking up a conversation, not a CRM lookup\n"
                "- Does NOT say 'I remember' or 'last time you said'\n"
                "- Does NOT re-introduce yourself — they already know you\n"
                "- If you cannot find their name, still write a warm personalized greeting based on what was discussed\n"
            )
            response = get_client().messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            greeting = response.content[0].text.strip().strip('"')
            if greeting:
                logger.info(f"[Greeting] Generated from recent_context: {greeting[:80]}...")
                return greeting
        except Exception as e:
            logger.error(f"[Greeting] Failed to generate from context: {e}")
            # Try to extract name for a template fallback
            name = _extract_name_from_context(recent_context)
            if name:
                return f"Hey {name}! Good to see you back. How have things been going?"
            return None

    elif arm in (BotArm.HANK_HYPES, BotArm.IVY_INFORMS):
        # For control bots, try to extract name from context for template greeting
        name = _extract_name_from_context(recent_context)
        if not name:
            return None
        if arm == BotArm.HANK_HYPES:
            return f"Hey {name}! Great to see you back! Ready to make some moves with AI?"
        else:
            return f"Hi {name}, welcome back. I'm here if you have more questions about the program."

    return None


def _generate_memory_greeting(arm: BotArm, memory: dict, recent_context: str = "") -> str | None:
    """
    Generate a relationship-aware personalized greeting for a returning visitor.
    Uses relationship context, emotional peaks, strategic notes, and recent
    conversation context to craft a greeting that feels like picking up a conversation.
    Returns None if no memory exists (caller falls back to default greeting).
    """
    if not memory.get("has_memory"):
        # No structured memory (memory_facts). But if we have recent conversation
        # context (raw messages from a prior session), generate a greeting from that.
        # This handles the race condition where async Gemini extraction hasn't finished.
        if recent_context:
            logger.info(f"[Greeting] No structured memory, but have recent_context ({len(recent_context)} chars) — generating from conversation history")
            return _generate_greeting_from_context(arm, recent_context)
        logger.debug(f"[Greeting] No memory and no recent_context — returning None")
        return None

    identity = memory.get("identity", {})
    name = identity.get("name")
    if not name:
        logger.debug(f"[Greeting] No name in identity — returning None (identity={identity})")
        return None  # No name → not enough info for a personalized greeting

    logger.info(f"[Greeting] Generating personalized greeting for {name} (arm={arm}, sessions={memory.get('session_count', '?')})")

    summaries = memory.get("session_summaries", [])
    last_summary = summaries[0] if summaries else None
    relationship = memory.get("relationship", {})
    emotional_peaks = memory.get("emotional_peaks", [])
    strategic_notes = memory.get("strategic_notes", {})
    unfinished_threads = memory.get("unfinished_threads", [])
    pain_points = memory.get("pain_points", [])
    session_count = memory.get("session_count", 1)

    if arm == BotArm.SALLY_NEPQ:
        # Sally gets a Claude-generated relationship-aware greeting
        from .bots.base import get_client
        try:
            prompt = (
                "You are Sally, a warm and empathetic sales agent for 100x Academy. "
                f"A returning visitor named {name} is back for chat #{session_count + 1}.\n\n"
            )

            # Identity context
            if identity.get("role"):
                prompt += f"They work as {identity['role']}"
                if identity.get("company"):
                    prompt += f" at {identity['company']}"
                prompt += ".\n"

            # Relationship context
            if relationship:
                rapport = relationship.get("rapport_level", "")
                lang_style = relationship.get("their_language_style", "")
                energy = relationship.get("energy_pattern", "")
                personal = [v for k, v in relationship.items() if k.startswith("personal_details_")]
                humor = [v for k, v in relationship.items() if k.startswith("humor_moments_")]
                trust = [v for k, v in relationship.items() if k.startswith("trust_signals_")]

                if rapport:
                    prompt += f"Rapport level: {rapport}\n"
                if lang_style:
                    prompt += f"Their communication style: {lang_style}\n"
                if energy:
                    prompt += f"Energy pattern: {energy}\n"
                if personal:
                    prompt += f"Personal details you know: {'; '.join(personal[:3])}\n"
                if humor:
                    prompt += f"Humor moments from past chats: {'; '.join(humor[:2])}\n"
                if trust:
                    prompt += f"Trust signals: {'; '.join(trust[:2])}\n"

            # Emotional peaks
            if emotional_peaks:
                prompt += "\nEmotional peaks from past sessions:\n"
                for peak in emotional_peaks[:3]:
                    if isinstance(peak, dict):
                        prompt += f"- {peak.get('moment', 'N/A')}: {peak.get('emotion', '')} — they said: \"{peak.get('their_words', '')}\"\n"
                    else:
                        prompt += f"- {peak}\n"

            # Strategic intelligence
            if strategic_notes:
                next_strategy = strategic_notes.get("next_session_strategy", "")
                what_worked = strategic_notes.get("what_worked", "")
                what_didnt = strategic_notes.get("what_didnt_work", "")
                weak_objection = strategic_notes.get("objection_vulnerability", "")
                if next_strategy:
                    prompt += f"\nRecommended approach for this session: {next_strategy}\n"
                if what_worked:
                    prompt += f"What worked last time: {what_worked}\n"
                if what_didnt:
                    prompt += f"What didn't work: {what_didnt}\n"
                if weak_objection:
                    prompt += f"Their weakest objection: {weak_objection}\n"

            if unfinished_threads:
                prompt += f"\nUnfinished threads to potentially pick up: {'; '.join(unfinished_threads[:3])}\n"

            # Last session context
            if last_summary:
                prompt += f"\nLast session summary: {last_summary['summary']}\n"
                outcome = last_summary.get("outcome", "")
                if outcome:
                    prompt += f"Last session outcome: {outcome}\n"

            # Special case handling
            last_outcome = last_summary.get("outcome", "") if last_summary else ""
            if "price" in last_outcome.lower() or "objection" in last_outcome.lower():
                prompt += "\nIMPORTANT: They had a price objection last time. Do NOT mention the workshop or price in your greeting. Focus on reconnecting as a person.\n"
            elif "completed_free" in last_outcome.lower() or "free_workshop" in last_outcome.lower():
                prompt += "\nThey completed the free workshop. You can ask how it went.\n"
            elif last_outcome and any(phase in last_outcome.lower() for phase in ["connection", "situation", "abandoned"]):
                prompt += "\nThey left early last time. Keep the greeting light and casual — no pressure.\n"

            # Recent conversation context — what was actually said last time
            if recent_context:
                prompt += f"\n{recent_context}\n"

            prompt += (
                "\nWrite a SHORT (2-3 sentences max) greeting that:\n"
                "- Reconnects as a PERSON first, not a sales agent\n"
                "- References ONE specific thing from your history (a personal detail, something they were excited about, or an unfinished thread)\n"
                "- Matches their energy and rapport level from before\n"
                "- Does NOT recite facts or list what you remember\n"
                "- Does NOT say 'I remember' or 'last time you said'\n"
                "- Feels like a friend picking up a conversation, not a CRM lookup\n"
                "- Uses their name naturally\n"
            )

            response = get_client().messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip().strip('"')
        except Exception as e:
            logger.error(f"Memory greeting generation failed: {e}")
            return f"Hey {name}! Good to see you back. How have things been going?"

    elif arm == BotArm.HANK_HYPES:
        # Enhanced Hank templates with pain point awareness
        if name and pain_points:
            return (
                f"Hey {name}! Great to see you again! "
                f"Last time you mentioned {pain_points[0][:60]} — "
                f"I've been thinking about the numbers on that. Ready to dig in?"
            )
        last_outcome = last_summary.get("outcome", "") if last_summary else ""
        if name and "price" in last_outcome.lower():
            return f"Hey {name}! Glad you came back. Let me show you why this is the BEST investment you'll make this year."
        elif name:
            return f"Hey {name}! Awesome to have you back! What's been happening on the AI front since we last chatted?"
        return bot_get_greeting(arm)

    elif arm == BotArm.IVY_INFORMS:
        # Enhanced Ivy templates with context awareness
        last_outcome = last_summary.get("outcome", "") if last_summary else ""
        if name and last_outcome:
            if "free" in last_outcome.lower():
                return f"Hi {name}. Welcome back. Last time you opted for the free workshop. I can provide more information about it or answer any new questions."
            elif last_outcome in ("abandoned_late", "abandoned_mid"):
                return f"Hi {name}. Good to see you again. I have context from our previous discussion. What information would be helpful today?"
            else:
                return f"Hi {name}. Welcome back. What would you like to know more about?"
        elif name:
            return f"Hi {name}. Welcome back. What information can I help with?"
        return bot_get_greeting(arm)

    return None


def _seed_profile_from_memory(memory: dict) -> str:
    """
    Pre-populate a prospect profile JSON from stored memory facts.
    Returns a JSON string suitable for db_session.prospect_profile.
    Seeds ALL ProspectProfile fields that have data in memory, so Sally's
    decision engine doesn't re-discover things already known.
    """
    if not memory.get("has_memory"):
        return "{}"

    profile = {}

    # Identity
    identity = memory.get("identity", {})
    for key in ("name", "role", "company", "industry"):
        if identity.get(key):
            profile[key] = identity[key]

    # Situation (all fields)
    situation = memory.get("situation", {})
    for key in ("team_size", "workflow_description", "current_state", "desired_state"):
        if situation.get(key):
            profile[key] = situation[key]
    if situation.get("tools_mentioned"):
        profile["tools_mentioned"] = situation["tools_mentioned"]

    # Pain points → seed into both pain_points and frustrations
    pain_points = memory.get("pain_points", [])
    if pain_points:
        profile["pain_points"] = pain_points
        profile["frustrations"] = pain_points  # ProspectProfile also has frustrations field

    # Objection history (useful for decision engine context)
    objection_history = memory.get("objection_history", [])
    if objection_history:
        profile["objection_history"] = objection_history

    return json.dumps(profile) if profile else "{}"


# --- Session Management ---

@app.post("/api/sessions", response_model=CreateSessionResponse)
def create_session(
    request: CreateSessionRequest,
    db: DBSessionType = Depends(get_db),
    current_user: Optional[DBUser] = Depends(get_optional_user),
):
    session_id = str(uuid.uuid4())[:8].upper()
    now = time.time()

    # Determine arm: explicit selection or random assignment (experiment mode)
    if request.selected_bot is not None:
        arm = request.selected_bot
    else:
        import random as _random
        arm = _random.choice(list(BotArm))
        logger.info(f"[Session {session_id}] Experiment mode: randomly assigned to {arm.value}")

    visitor_id = request.visitor_id
    initial_phase = NepqPhase.CONNECTION.value if arm == BotArm.SALLY_NEPQ else "CONVERSATION"

    # Determine user_id: authenticated user takes priority
    user_id = current_user.id if current_user else None

    # If authenticated and has visitor_id, merge any anonymous memory
    if user_id and visitor_id:
        try:
            merge_visitor_memory_to_user(db, visitor_id, user_id)
        except Exception as e:
            logger.error(f"[Session {session_id}] Failed to merge visitor memory: {e}")
            db.rollback()

    # Load memory for returning visitors/users
    memory = {}
    initial_profile = "{}"
    recent_context = ""
    if visitor_id or user_id:
        try:
            memory = load_visitor_memory(db, visitor_id or "", user_id=user_id)
            if memory.get("has_memory"):
                initial_profile = _seed_profile_from_memory(memory)
                logger.info(f"[Session {session_id}] Returning visitor/user — loaded memory with {memory.get('total_prior_sessions', 0)} prior session(s), identity={memory.get('identity', {})}")
            else:
                logger.info(f"[Session {session_id}] No memory facts found for visitor={visitor_id}, user_id={user_id}")
        except Exception as e:
            logger.error(f"[Session {session_id}] Failed to load visitor memory: {e}")
            db.rollback()  # Clear failed transaction so subsequent db.commit() works

        # Load recent conversation context (actual messages from last session)
        try:
            recent_context = load_recent_conversation_context(db, visitor_id or "", user_id=user_id)
            if recent_context:
                logger.info(f"[Session {session_id}] Loaded recent conversation context ({len(recent_context)} chars)")
        except Exception as e:
            logger.error(f"[Session {session_id}] Failed to load recent conversation context: {e}")

        # Fallback: if memory extraction hasn't completed yet (race condition with async daemon),
        # try to build a minimal memory dict from the last session's prospect_profile.
        # This ensures returning visitors get personalized greetings even if Gemini extraction is slow.
        if not memory.get("has_memory") and (visitor_id or user_id):
            try:
                from sqlalchemy import or_ as _or
                _id_conds = []
                if visitor_id:
                    _id_conds.append(DBSession.visitor_id == visitor_id)
                if user_id:
                    _id_conds.append(DBSession.user_id == user_id)
                if _id_conds:
                    # Check completed/abandoned first, then any session with a profile
                    prev_session = (
                        db.query(DBSession)
                        .filter(
                            _or(*_id_conds),
                            DBSession.status.in_(["completed", "abandoned"]),
                        )
                        .order_by(DBSession.end_time.desc())
                        .first()
                    )
                    # If no ended session, try active ones (user may not have properly ended)
                    if not prev_session:
                        prev_session = (
                            db.query(DBSession)
                            .filter(
                                _or(*_id_conds),
                                DBSession.prospect_profile.isnot(None),
                                DBSession.prospect_profile != "{}",
                            )
                            .order_by(DBSession.start_time.desc())
                            .first()
                        )
                    if prev_session and prev_session.prospect_profile:
                        try:
                            profile_data = json.loads(prev_session.prospect_profile)
                            # Try to get name from profile first, then from conversation context
                            fallback_name = profile_data.get("name")
                            if not fallback_name and recent_context:
                                fallback_name = _extract_name_from_context(recent_context)
                                if fallback_name:
                                    logger.info(f"[Session {session_id}] Extracted name '{fallback_name}' from recent_context")
                            if fallback_name:
                                memory = {
                                    "has_memory": True,
                                    "identity": {
                                        "name": fallback_name,
                                        "role": profile_data.get("role"),
                                        "company": profile_data.get("company"),
                                        "industry": profile_data.get("industry"),
                                    },
                                    "situation": {},
                                    "pain_points": profile_data.get("pain_points", []),
                                    "objection_history": [],
                                    "session_summaries": [],
                                    "total_prior_sessions": 1,
                                    "session_count": 1,
                                    "relationship": {},
                                    "emotional_peaks": [],
                                    "strategic_notes": {},
                                    "unfinished_threads": [],
                                }
                                initial_profile = _seed_profile_from_memory(memory)
                                logger.info(f"[Session {session_id}] Fallback: built memory from last session's prospect_profile (name={fallback_name})")
                        except (json.JSONDecodeError, Exception) as e:
                            logger.error(f"[Session {session_id}] Fallback profile parse failed: {e}")
                    elif recent_context:
                        # No previous session with profile found, but we have conversation context
                        extracted_name = _extract_name_from_context(recent_context)
                        if extracted_name:
                            memory = {
                                "has_memory": True,
                                "identity": {"name": extracted_name},
                                "situation": {},
                                "pain_points": [],
                                "objection_history": [],
                                "session_summaries": [],
                                "total_prior_sessions": 1,
                                "session_count": 1,
                                "relationship": {},
                                "emotional_peaks": [],
                                "strategic_notes": {},
                                "unfinished_threads": [],
                            }
                            logger.info(f"[Session {session_id}] Fallback: built memory from name extracted from recent_context (name={extracted_name})")
            except Exception as e:
                logger.error(f"[Session {session_id}] Fallback memory lookup failed: {e}")

    db_session = DBSession(
        id=session_id,
        status="active",
        current_phase=initial_phase,
        pre_conviction=request.pre_conviction,
        assigned_arm=arm.value,
        visitor_id=visitor_id,
        user_id=user_id,
        experiment_mode="true" if request.experiment_mode else None,
        start_time=now,
        message_count=1,
        retry_count=0,
        turn_number=0,
        prospect_profile=initial_profile,
        thought_logs="[]",
    )
    db.add(db_session)

    # Generate greeting — personalized for returning visitors, default for new
    greeting_text = _generate_memory_greeting(arm, memory, recent_context=recent_context)
    logger.info(f"[Session {session_id}] Greeting generation: has_memory={memory.get('has_memory')}, name={memory.get('identity', {}).get('name')}, result={'personalized' if greeting_text else 'default'}")
    if not greeting_text:
        greeting_text = bot_get_greeting(arm)
    greeting_id = str(uuid.uuid4())
    greeting_msg = DBMessage(
        id=greeting_id,
        session_id=session_id,
        role="assistant",
        content=greeting_text,
        timestamp=now,
        phase=initial_phase,
    )
    db.add(greeting_msg)
    db.commit()

    # In experiment mode, mask the real arm from the frontend
    if request.experiment_mode:
        display_arm = "experiment"
        display_name = "AI Assistant"
    else:
        display_arm = arm.value
        display_name = BOT_DISPLAY_NAMES[arm]

    return CreateSessionResponse(
        session_id=session_id,
        current_phase=initial_phase,
        pre_conviction=request.pre_conviction,
        assigned_arm=display_arm,
        bot_display_name=display_name,
        greeting=MessageResponse(
            id=greeting_id,
            role="assistant",
            content=greeting_text,
            timestamp=now,
            phase=initial_phase,
        ),
        visitor_id=visitor_id,
    )


# --- Session Resumption ---

@app.get("/api/visitors/{visitor_id}/active-session", response_model=ResumeSessionResponse)
def get_active_session(
    visitor_id: str,
    db: DBSessionType = Depends(get_db),
    current_user: Optional[DBUser] = Depends(get_optional_user),
):
    """Check if a visitor/user has a resumable session (active or recently abandoned within 24h)."""
    import time as _time
    from sqlalchemy import or_
    cutoff = _time.time() - 86400  # 24 hours ago

    # Search by visitor_id OR user_id (if authenticated)
    identity_conditions = [DBSession.visitor_id == visitor_id]
    if current_user:
        identity_conditions.append(DBSession.user_id == current_user.id)

    db_session = (
        db.query(DBSession)
        .filter(
            or_(*identity_conditions),
            DBSession.status.in_(["active", "abandoned"]),
            DBSession.start_time > cutoff,
        )
        .order_by(DBSession.start_time.desc())
        .first()
    )

    if not db_session:
        raise HTTPException(status_code=404, detail="No resumable session found")

    # Reactivate if it was abandoned
    if db_session.status == "abandoned":
        db_session.status = "active"
        db_session.end_time = None
        db.commit()

    # Load all messages
    messages = (
        db.query(DBMessage)
        .filter(DBMessage.session_id == db_session.id)
        .order_by(DBMessage.timestamp)
        .all()
    )

    arm = BotArm(db_session.assigned_arm) if db_session.assigned_arm else BotArm.SALLY_NEPQ

    return ResumeSessionResponse(
        session_id=db_session.id,
        current_phase=db_session.current_phase,
        assigned_arm=arm.value,
        bot_display_name=BOT_DISPLAY_NAMES[arm],
        messages=[
            MessageResponse(
                id=m.id,
                role=m.role,
                content=m.content,
                timestamp=m.timestamp,
                phase=m.phase,
            )
            for m in messages
        ],
        visitor_id=visitor_id,
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
    arm = BotArm(db_session.assigned_arm) if db_session.assigned_arm else BotArm.SALLY_NEPQ
    is_sally = arm == BotArm.SALLY_NEPQ

    # For Sally sessions, parse current phase as NepqPhase; for control bots, keep as string
    current_phase_str = db_session.current_phase
    current_phase = NepqPhase(current_phase_str) if current_phase_str in [p.value for p in NepqPhase] else None
    previous_phase = current_phase

    # Load visitor memory BEFORE any db.add() — if this fails and we rollback,
    # no pending writes are lost
    memory_block = ""
    if db_session.visitor_id or getattr(db_session, 'user_id', None):
        try:
            visitor_memory = load_visitor_memory(
                db, db_session.visitor_id or "", user_id=getattr(db_session, 'user_id', None)
            )
            memory_block = format_memory_for_prompt(visitor_memory)

            # Append recent conversation context (actual messages from prior session)
            if memory_block:
                try:
                    recent_ctx = load_recent_conversation_context(
                        db, db_session.visitor_id or "", user_id=getattr(db_session, 'user_id', None)
                    )
                    if recent_ctx:
                        memory_block = memory_block + "\n\n" + recent_ctx
                except Exception as e:
                    logger.error(f"[Session {session_id}] Failed to load recent conversation context: {e}")
        except Exception as e:
            logger.error(f"[Session {session_id}] Failed to load visitor memory: {e}")
            db.rollback()  # Clear failed transaction so subsequent db operations work
            # Re-fetch db_session since rollback expires all loaded objects
            db_session = db.query(DBSession).filter(DBSession.id == session_id).first()

    # Check for _switch_context in prospect profile (one-time injection after bot switch)
    try:
        profile_data = json.loads(db_session.prospect_profile or "{}")
        switch_ctx = profile_data.pop("_switch_context", None)
        if switch_ctx:
            switch_block = "[PRIOR CONVERSATION CONTEXT:\n" + switch_ctx + "]"
            memory_block = (memory_block + "\n\n" + switch_block) if memory_block else switch_block
            # Remove _switch_context so it only fires once
            db_session.prospect_profile = json.dumps(profile_data)
    except (json.JSONDecodeError, Exception):
        pass

    # Save user message
    user_msg_id = str(uuid.uuid4())
    user_msg = DBMessage(
        id=user_msg_id,
        session_id=session_id,
        role="user",
        content=request.content,
        timestamp=now,
        phase=current_phase.value if current_phase else current_phase_str,
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

    # Run the engine (Sally's three-layer pipeline or control bot single-prompt)
    logger.info(f"[Session {session_id}] Processing turn {db_session.turn_number} in {current_phase_str} (arm={arm.value})")

    try:
        result = route_message(
            arm=arm,
            user_message=request.content,
            conversation_history=conversation_history,
            memory_context=memory_block,
            # Sally-specific params (ignored for Hank/Ivy):
            current_phase=current_phase or NepqPhase.CONNECTION,
            profile_json=db_session.prospect_profile or "{}",
            retry_count=db_session.retry_count,
            turn_number=db_session.turn_number,
            conversation_start_time=db_session.start_time,
            consecutive_no_new_info=getattr(db_session, 'consecutive_no_new_info', 0) or 0,
            turns_in_current_phase=getattr(db_session, 'turns_in_current_phase', 0) or 0,
            deepest_emotional_depth=getattr(db_session, 'deepest_emotional_depth', 'surface') or 'surface',
            objection_diffusion_step=getattr(db_session, 'objection_diffusion_step', 0) or 0,
            ownership_substep=getattr(db_session, 'ownership_substep', 0) or 0,
            # Shared params for link tracking:
            session_id=session_id,
            channel=getattr(db_session, 'channel', 'web') or 'web',
        )
    except Exception as e:
        logger.error(f"[Session {session_id}] Engine error: {e}")
        result = {
            "response_text": "How has that been playing out for you day-to-day?",
            "new_phase": current_phase.value if current_phase else current_phase_str,
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
    new_phase_str = result["new_phase"]
    new_phase = NepqPhase(new_phase_str) if new_phase_str in [p.value for p in NepqPhase] else None
    db_session.current_phase = new_phase_str

    # Sally-specific state tracking — skip for control bots
    if is_sally:
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

    # Append thought log (Sally only — control bots return empty thought logs)
    existing_logs = []
    if is_sally:
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
                extra_user_msg={"role": "user", "content": request.content, "phase": current_phase.value if current_phase else current_phase_str, "timestamp": now},
            )
            fire_sheets_log("session", _sd, _md)
        except Exception as e:
            logger.error(f"[Session {session_id}] Sheets log (completed) error: {e}")

        # Async quality scoring — Sally only (fire-and-forget via daemon thread)
        if is_sally:
            try:
                # Snapshot data for the scorer thread (avoid DB session sharing across threads)
                all_msgs_for_scoring = [
                    {"role": m.role, "content": m.content, "phase": m.phase}
                    for m in messages
                ]
                # Add the current user message (not yet in the DB query result)
                all_msgs_for_scoring.append({"role": "user", "content": request.content, "phase": current_phase.value if current_phase else current_phase_str})
                # Add Sally's response (use result dict since response_text variable is defined later)
                all_msgs_for_scoring.append({"role": "assistant", "content": result["response_text"], "phase": new_phase.value if new_phase else new_phase_str})

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
                        from app.database import _get_session_local
                        scoring_db = _get_session_local()()
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

        # Async memory extraction — runs after session ends (fire-and-forget)
        if db_session.visitor_id or getattr(db_session, 'user_id', None):
            try:
                mem_session_id = session_id
                mem_visitor_id = db_session.visitor_id or ""
                mem_user_id = getattr(db_session, 'user_id', None)
                mem_bot_arm = arm.value
                mem_profile_json = db_session.prospect_profile or "{}"
                mem_outcome = "completed" if db_session.status == "completed" else "abandoned"
                mem_final_phase = new_phase_str
                mem_transcript = [
                    {"role": m.role, "content": m.content, "phase": m.phase}
                    for m in messages
                ]
                mem_transcript.append({"role": "user", "content": request.content, "phase": current_phase.value if current_phase else current_phase_str})
                mem_transcript.append({"role": "assistant", "content": result["response_text"], "phase": new_phase_str})

                def _run_memory_extraction():
                    try:
                        extraction = extract_memory_from_session(
                            session_id=mem_session_id,
                            visitor_id=mem_visitor_id,
                            transcript=mem_transcript,
                            profile_json=mem_profile_json,
                            outcome=mem_outcome,
                            final_phase=mem_final_phase,
                            bot_arm=mem_bot_arm,
                        )
                        if extraction:
                            from app.database import _get_session_local
                            store_memory(
                                db_session_maker=_get_session_local(),
                                session_id=mem_session_id,
                                visitor_id=mem_visitor_id,
                                extraction=extraction,
                                user_id=mem_user_id,
                                bot_arm=mem_bot_arm,
                            )
                    except Exception as e:
                        logger.error(f"[Session {mem_session_id}] Memory extraction failed: {e}")

                t_mem = threading.Thread(target=_run_memory_extraction, daemon=True)
                t_mem.start()
            except Exception as e:
                logger.error(f"[Session {session_id}] Memory extraction thread launch failed: {e}")

    # Gmail escalation: trigger when entering OWNERSHIP (first time only) — Sally only
    if is_sally and new_phase == NepqPhase.OWNERSHIP and previous_phase != NepqPhase.OWNERSHIP and not db_session.escalation_sent:
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
            transcript_lines.append(f"[{current_phase.value if current_phase else current_phase_str}] Prospect: {request.content}")
            transcript_text = "\n".join(transcript_lines)

            sent = _send_escalation_email(session_id, profile_for_email, transcript_text)
            if sent:
                db_session.escalation_sent = time.time()

            # Google Sheets: log hot lead
            _sd, _md = _serialize_for_sheets(
                db_session, db,
                extra_user_msg={"role": "user", "content": request.content, "phase": current_phase.value if current_phase else current_phase_str, "timestamp": now},
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

    # --- Link Guarantee: ensure correct links appear in closing responses ---
    import re
    tidycal_path = os.getenv("TIDYCAL_PATH", "")
    tidycal_url = f"https://tidycal.com/{tidycal_path}" if tidycal_path else ""
    stripe_fallback = os.getenv("STRIPE_PAYMENT_LINK", "")
    text_lower = response_text.lower()

    # Step 1: Remove ALL hallucinated Calendly URLs (we don't use Calendly)
    if "calendly.com" in text_lower:
        response_text = re.sub(r'https?://calendly\.com/\S+', '', response_text)
        response_text = re.sub(r'\s+', ' ', response_text).strip()
        logger.warning(f"[Session {session_id}] Stripped hallucinated Calendly URL")
        text_lower = response_text.lower()

    # Step 2: Determine if this is a link-delivery turn
    is_closing_phase = new_phase in (NepqPhase.COMMITMENT, NepqPhase.TERMINATED, NepqPhase.OWNERSHIP)
    has_any_link = "http://" in text_lower or "https://" in text_lower or "[PAYMENT_LINK]" in response_text
    mentions_sending_link = any(w in text_lower for w in ["send you", "here's the link", "booking link", "workshop link", "secure your spot", "link to"])
    is_free_context = any(w in text_lower for w in ["free workshop", "free online", "free version", "free ai", "no cost"])

    # Step 3: If Sally promises a link but didn't include one, inject it
    if is_closing_phase and mentions_sending_link and not has_any_link:
        if is_free_context and tidycal_url:
            response_text = response_text.rstrip() + f"\n\n{tidycal_url}"
            logger.info(f"[Session {session_id}] Injected TidyCal link (LLM forgot to include it)")
        elif stripe_fallback:
            response_text = response_text.rstrip() + f"\n\n{stripe_fallback}"
            logger.info(f"[Session {session_id}] Injected Stripe link (LLM forgot to include it)")

    # Step 4: Ensure TidyCal URL is correct (LLM might write wrong tidycal path)
    if "tidycal.com" in text_lower and tidycal_url:
        response_text = re.sub(r'https?://tidycal\.com/\S+', tidycal_url, response_text)

    # Step 5: Replace [INVITATION_LINK] placeholder with tracked invitation URL
    if "[INVITATION_LINK]" in response_text:
        from app.invitation import build_invitation_url
        invitation_url = build_invitation_url(
            session_id=session_id,
            arm=arm.value,
            channel=getattr(db_session, 'channel', 'web') or 'web',
        )
        response_text = response_text.replace("[INVITATION_LINK]", invitation_url)

    # Step 6: Track invitation link sent (check for the base URL in the response)
    from app.invitation import INVITATION_URL as _INVITATION_BASE
    if _INVITATION_BASE.lower() in response_text.lower() and not getattr(db_session, 'invitation_link_sent', None):
        db_session.invitation_link_sent = "true"
        db_session.invitation_link_sent_at = time.time()
        logger.info(f"[Session {session_id}] Invitation link sent")

    # Save assistant message
    assistant_msg_id = str(uuid.uuid4())
    assistant_msg = DBMessage(
        id=assistant_msg_id,
        session_id=session_id,
        role="assistant",
        content=response_text,
        timestamp=time.time(),
        phase=new_phase.value if new_phase else new_phase_str,
    )
    db.add(assistant_msg)
    db_session.message_count += 1
    db.commit()

    prev_phase_display = previous_phase.value if previous_phase else current_phase_str
    new_phase_display = new_phase.value if new_phase else new_phase_str
    logger.info(f"[Session {session_id}] Turn complete: {prev_phase_display} -> {new_phase_display} "
                f"(changed={result['phase_changed']}, ended={result['session_ended']})")

    return SendMessageResponse(
        user_message=MessageResponse(
            id=user_msg_id,
            role="user",
            content=request.content,
            timestamp=now,
            phase=prev_phase_display,
        ),
        assistant_message=MessageResponse(
            id=assistant_msg_id,
            role="assistant",
            content=response_text,
            timestamp=assistant_msg.timestamp,
            phase=new_phase_display,
        ),
        current_phase=new_phase_display,
        previous_phase=prev_phase_display,
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
        "assigned_arm": getattr(db_session, 'assigned_arm', None),
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
def list_sessions(
    db: DBSessionType = Depends(get_db),
    channel: Optional[str] = Query(None, description="Filter by channel: web, sms"),
    arm: Optional[str] = Query(None, description="Filter by arm: sally_nepq, hank_hypes, ivy_informs"),
    status: Optional[str] = Query(None, description="Filter by status: active, completed, abandoned, switched"),
    search: Optional[str] = Query(None, description="Search by session ID or phone number"),
    start_date: Optional[float] = Query(None, description="Filter sessions after this unix timestamp"),
    end_date: Optional[float] = Query(None, description="Filter sessions before this unix timestamp"),
):
    query = db.query(DBSession)
    if channel:
        query = query.filter(DBSession.channel == channel)
    if arm:
        query = query.filter(DBSession.assigned_arm == arm)
    if status:
        query = query.filter(DBSession.status == status)
    if search:
        query = query.filter(
            (DBSession.id.ilike(f"%{search}%")) |
            (DBSession.phone_number.ilike(f"%{search}%"))
        )
    if start_date:
        query = query.filter(DBSession.start_time >= start_date)
    if end_date:
        query = query.filter(DBSession.start_time <= end_date)

    sessions = query.order_by(DBSession.start_time.desc()).limit(200).all()
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
            assigned_arm=getattr(s, 'assigned_arm', None),
            channel=getattr(s, 'channel', None),
            phone_number=getattr(s, 'phone_number', None),
            turn_number=getattr(s, 'turn_number', None),
            followup_count=getattr(s, 'followup_count', None),
            experiment_mode=getattr(s, 'experiment_mode', None),
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


# --- Analytics Trends ---

@app.get("/api/analytics/trends")
def get_trends(db: DBSessionType = Depends(get_db)):
    """Time-series data for dashboard trend charts."""
    cutoff = time.time() - 30 * 86400  # last 30 days

    # --- 1. Sessions by day ---
    # For PostgreSQL: convert unix float → timestamp → date
    date_col = func.date(func.to_timestamp(DBSession.start_time))

    day_rows = (
        db.query(
            date_col.label("day"),
            func.count(DBSession.id).label("total"),
            func.count(func.nullif(DBSession.assigned_arm != "sally_nepq", True)).label("sally"),
            func.count(func.nullif(DBSession.assigned_arm != "hank_hypes", True)).label("hank"),
            func.count(func.nullif(DBSession.assigned_arm != "ivy_informs", True)).label("ivy"),
            func.count(func.nullif(DBSession.channel != "web", True)).label("web"),
            func.count(func.nullif(DBSession.channel != "sms", True)).label("sms"),
        )
        .filter(DBSession.start_time >= cutoff)
        .group_by(date_col)
        .order_by(date_col)
        .all()
    )

    sessions_by_day = [
        {
            "date": str(row.day),
            "total": row.total,
            "sally": row.sally,
            "hank": row.hank,
            "ivy": row.ivy,
            "web": row.web,
            "sms": row.sms,
        }
        for row in day_rows
    ]

    # --- 2. CDS by day ---
    from sqlalchemy import case as sql_case

    cds_rows = (
        db.query(
            date_col.label("day"),
            func.avg(DBSession.cds_score).label("mean_cds"),
            func.avg(sql_case(
                (DBSession.assigned_arm == "sally_nepq", DBSession.cds_score),
            )).label("sally_cds"),
            func.avg(sql_case(
                (DBSession.assigned_arm == "hank_hypes", DBSession.cds_score),
            )).label("hank_cds"),
            func.avg(sql_case(
                (DBSession.assigned_arm == "ivy_informs", DBSession.cds_score),
            )).label("ivy_cds"),
            func.count(DBSession.id).label("count"),
        )
        .filter(
            DBSession.start_time >= cutoff,
            DBSession.cds_score.isnot(None),
        )
        .group_by(date_col)
        .order_by(date_col)
        .all()
    )

    cds_by_day = [
        {
            "date": str(row.day),
            "mean_cds": round(float(row.mean_cds), 2) if row.mean_cds is not None else None,
            "sally_cds": round(float(row.sally_cds), 2) if row.sally_cds is not None else None,
            "hank_cds": round(float(row.hank_cds), 2) if row.hank_cds is not None else None,
            "ivy_cds": round(float(row.ivy_cds), 2) if row.ivy_cds is not None else None,
            "count": row.count,
        }
        for row in cds_rows
    ]

    # --- 3. Avg length by arm ---
    arm_rows = (
        db.query(
            DBSession.assigned_arm.label("arm"),
            func.avg(DBSession.message_count).label("avg_messages"),
            func.avg(DBSession.turn_number).label("avg_turns"),
            func.avg(DBSession.end_time - DBSession.start_time).label("avg_duration_seconds"),
        )
        .filter(
            DBSession.status == "completed",
            DBSession.assigned_arm.isnot(None),
            DBSession.end_time.isnot(None),
        )
        .group_by(DBSession.assigned_arm)
        .all()
    )

    avg_length_by_arm = [
        {
            "arm": row.arm,
            "avg_messages": round(float(row.avg_messages), 1) if row.avg_messages else 0,
            "avg_turns": round(float(row.avg_turns), 1) if row.avg_turns else 0,
            "avg_duration_minutes": round(float(row.avg_duration_seconds) / 60, 1) if row.avg_duration_seconds else 0,
        }
        for row in arm_rows
    ]

    # --- 4. Funnel ---
    total_sessions = db.query(DBSession).count()
    reached_active = db.query(DBSession).filter(
        DBSession.sms_state.in_(["active", "post_survey", "done"]) |
        (DBSession.channel != "sms")
    ).count()
    reached_completed = db.query(DBSession).filter(DBSession.status == "completed").count()
    has_cds = db.query(DBSession).filter(DBSession.cds_score.isnot(None)).count()

    return {
        "sessions_by_day": sessions_by_day,
        "cds_by_day": cds_by_day,
        "avg_length_by_arm": avg_length_by_arm,
        "funnel": {
            "total_sessions": total_sessions,
            "reached_active": reached_active,
            "reached_completed": reached_completed,
            "has_cds": has_cds,
        },
    }


# --- CDS Monitoring (Experiment Mode) ---

@app.get("/api/monitoring/cds-summary")
def get_cds_summary(db: DBSessionType = Depends(get_db)):
    """Per-arm CDS summary for experiment monitoring. Only includes experiment-mode sessions."""
    from sqlalchemy import func as sqlfunc

    results = (
        db.query(
            DBSession.assigned_arm,
            sqlfunc.count(DBSession.id).label("total_sessions"),
            sqlfunc.count(DBSession.cds_score).label("completed_cds"),
            sqlfunc.avg(DBSession.cds_score).label("mean_cds"),
            sqlfunc.min(DBSession.cds_score).label("min_cds"),
            sqlfunc.max(DBSession.cds_score).label("max_cds"),
        )
        .filter(
            DBSession.assigned_arm.isnot(None),
            DBSession.experiment_mode == "true",
        )
        .group_by(DBSession.assigned_arm)
        .all()
    )

    arms = {}
    for row in results:
        arms[row.assigned_arm] = {
            "total_sessions": row.total_sessions,
            "completed_cds": row.completed_cds,
            "mean_cds": round(float(row.mean_cds), 3) if row.mean_cds else None,
            "min_cds": row.min_cds,
            "max_cds": row.max_cds,
        }

    # Sally's lift vs each control
    sally = arms.get("sally_nepq", {})
    sally_mean = sally.get("mean_cds")
    lifts = {}
    if sally_mean is not None:
        for arm_name in ["hank_hypes", "ivy_informs"]:
            control = arms.get(arm_name, {})
            control_mean = control.get("mean_cds")
            if control_mean is not None:
                lifts[arm_name] = round(sally_mean - float(control_mean), 3)

    # Session counts by status for experiment sessions
    status_counts = {}
    for status in ["active", "completed", "abandoned"]:
        count = db.query(DBSession).filter(
            DBSession.experiment_mode == "true",
            DBSession.status == status,
        ).count()
        status_counts[status] = count

    return {
        "arms": arms,
        "sally_lift_vs_controls": lifts,
        "experiment_session_counts": status_counts,
        "target": {
            "min_sessions_per_arm": 20,
            "total_target": 60,
            "sally_cds_target": 0.5,
            "lift_target": 0.3,
        },
    }


# --- Admin Analytics ---

@app.get("/api/admin/analytics")
def get_admin_analytics(db: DBSessionType = Depends(get_db)):
    """Comprehensive analytics for the admin dashboard."""
    experiment_filter = DBSession.experiment_mode == "true"

    # Per-arm aggregations
    arm_counts = (
        db.query(
            DBSession.assigned_arm,
            func.count(DBSession.id).label("total"),
            func.count(case((DBSession.status == "completed", 1))).label("completed"),
            func.count(case((DBSession.status == "abandoned", 1))).label("abandoned"),
            func.count(case((DBSession.status == "switched", 1))).label("switched"),
            func.count(case((DBSession.status == "active", 1))).label("active"),
            func.count(case((DBSession.cds_score.isnot(None), 1))).label("has_cds"),
            func.avg(DBSession.cds_score).label("mean_cds"),
            func.avg(DBSession.pre_conviction).label("mean_pre"),
            func.avg(DBSession.post_conviction).label("mean_post"),
            func.avg(DBSession.message_count).label("avg_messages"),
            func.avg(DBSession.turn_number).label("avg_turns"),
        )
        .filter(experiment_filter, DBSession.assigned_arm.isnot(None))
        .group_by(DBSession.assigned_arm)
        .all()
    )

    # Channel breakdown
    channel_counts = (
        db.query(
            DBSession.channel,
            func.count(DBSession.id).label("count"),
        )
        .filter(experiment_filter)
        .group_by(DBSession.channel)
        .all()
    )

    # Follow-up stats
    followup_stats = (
        db.query(
            func.count(case((DBSession.followup_count > 0, 1))).label("sessions_with_followups"),
            func.avg(DBSession.followup_count).label("avg_followups"),
            func.sum(DBSession.followup_count).label("total_followups_sent"),
        )
        .filter(experiment_filter, DBSession.channel == "sms")
        .first()
    )

    # Phase distribution at session end (Sally only)
    phase_at_end = (
        db.query(
            DBSession.current_phase,
            func.count(DBSession.id).label("count"),
        )
        .filter(
            experiment_filter,
            DBSession.assigned_arm == "sally_nepq",
            DBSession.status.in_(["completed", "abandoned"]),
        )
        .group_by(DBSession.current_phase)
        .all()
    )

    # Recent sessions (last 50)
    recent = (
        db.query(DBSession)
        .filter(experiment_filter)
        .order_by(DBSession.start_time.desc())
        .limit(50)
        .all()
    )

    # Build response
    arms_data = {}
    total_experiment = 0
    total_with_cds = 0
    for row in arm_counts:
        arms_data[row.assigned_arm] = {
            "total": row.total,
            "completed": row.completed,
            "abandoned": row.abandoned,
            "switched": row.switched,
            "active": row.active,
            "has_cds": row.has_cds,
            "mean_cds": round(float(row.mean_cds), 2) if row.mean_cds else None,
            "mean_pre": round(float(row.mean_pre), 1) if row.mean_pre else None,
            "mean_post": round(float(row.mean_post), 1) if row.mean_post else None,
            "avg_messages": round(float(row.avg_messages), 1) if row.avg_messages else None,
            "avg_turns": round(float(row.avg_turns), 1) if row.avg_turns else None,
            "completion_rate": round(row.completed / row.total * 100, 1) if row.total > 0 else 0,
        }
        total_experiment += row.total
        total_with_cds += row.has_cds

    # Sally lift calculations
    sally_mean = arms_data.get("sally_nepq", {}).get("mean_cds")
    lifts = {}
    if sally_mean is not None:
        for control in ["hank_hypes", "ivy_informs"]:
            control_mean = arms_data.get(control, {}).get("mean_cds")
            if control_mean is not None:
                lifts[control] = round(sally_mean - control_mean, 2)

    # Go/Iterate/Kill status
    status = "insufficient_data"
    if sally_mean is not None and total_with_cds >= 20:
        if sally_mean >= 0.5 and all(v >= 0.3 for v in lifts.values()):
            status = "GO"
        elif sally_mean >= 0.2:
            status = "ITERATE"
        else:
            status = "KILL"

    return {
        "experiment_status": status,
        "total_experiment_sessions": total_experiment,
        "total_with_cds": total_with_cds,
        "target_sessions": 60,
        "progress_pct": round(total_with_cds / 60 * 100, 1) if total_with_cds else 0,
        "arms": arms_data,
        "sally_lift": lifts,
        "channels": {row.channel or "unknown": row.count for row in channel_counts},
        "followups": {
            "sessions_with_followups": followup_stats.sessions_with_followups if followup_stats else 0,
            "avg_followups_per_session": round(float(followup_stats.avg_followups), 1) if followup_stats and followup_stats.avg_followups else 0,
            "total_sent": followup_stats.total_followups_sent if followup_stats else 0,
        },
        "sally_phase_distribution": {row.current_phase: row.count for row in phase_at_end},
        "recent_sessions": [
            {
                "id": s.id,
                "arm": s.assigned_arm,
                "channel": getattr(s, 'channel', 'web'),
                "status": s.status,
                "pre_conviction": s.pre_conviction,
                "post_conviction": s.post_conviction,
                "cds_score": s.cds_score,
                "message_count": s.message_count,
                "turn_number": s.turn_number,
                "current_phase": s.current_phase,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "followup_count": getattr(s, 'followup_count', 0),
            }
            for s in recent
        ],
    }


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

        # Async memory extraction on abandon
        if db_session.visitor_id or getattr(db_session, 'user_id', None):
            try:
                mem_sid = session_id
                mem_vid = db_session.visitor_id or ""
                mem_uid = getattr(db_session, 'user_id', None)
                mem_bot_arm = db_session.assigned_arm or "unknown"
                mem_profile = db_session.prospect_profile or "{}"
                mem_phase = db_session.current_phase
                all_msgs_mem = (
                    db.query(DBMessage)
                    .filter(DBMessage.session_id == session_id)
                    .order_by(DBMessage.timestamp)
                    .all()
                )
                mem_transcript = [{"role": m.role, "content": m.content, "phase": m.phase} for m in all_msgs_mem]

                def _run_abandon_memory():
                    try:
                        extraction = extract_memory_from_session(
                            session_id=mem_sid,
                            visitor_id=mem_vid,
                            transcript=mem_transcript,
                            profile_json=mem_profile,
                            outcome="abandoned",
                            final_phase=mem_phase,
                            bot_arm=mem_bot_arm,
                        )
                        if extraction:
                            from app.database import _get_session_local
                            store_memory(
                                db_session_maker=_get_session_local(),
                                session_id=mem_sid,
                                visitor_id=mem_vid,
                                extraction=extraction,
                                user_id=mem_uid,
                                bot_arm=mem_bot_arm,
                            )
                    except Exception as e:
                        logger.error(f"[Session {mem_sid}] Abandon memory extraction failed: {e}")

                t = threading.Thread(target=_run_abandon_memory, daemon=True)
                t.start()
            except Exception as e:
                logger.error(f"[Session {session_id}] Abandon memory thread failed: {e}")

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


# --- Visitor Memory ---

@app.get("/api/visitors/{visitor_id}/memory")
def get_visitor_memory(visitor_id: str, db: DBSessionType = Depends(get_db)):
    """Debug endpoint: view stored memory for a visitor."""
    memory = load_visitor_memory(db, visitor_id)
    return memory


@app.delete("/api/visitors/{visitor_id}/memory")
def delete_visitor_memory(visitor_id: str, db: DBSessionType = Depends(get_db)):
    """Delete all stored memory for a visitor (privacy / 'Forget Me')."""
    from .database import DBMemoryFact, DBSessionSummary

    facts_deleted = db.query(DBMemoryFact).filter(DBMemoryFact.visitor_id == visitor_id).delete()
    summaries_deleted = db.query(DBSessionSummary).filter(DBSessionSummary.visitor_id == visitor_id).delete()
    db.commit()

    logger.info(f"[Privacy] Deleted memory for visitor {visitor_id[:8]}: {facts_deleted} facts, {summaries_deleted} summaries")

    return {
        "status": "ok",
        "visitor_id": visitor_id,
        "facts_deleted": facts_deleted,
        "summaries_deleted": summaries_deleted,
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


# --- Bot Switching ---

@app.post("/api/sessions/{session_id}/switch")
def switch_bot(
    session_id: str,
    request: dict,  # {"new_bot": "sally_nepq" | "hank_hypes" | "ivy_informs"}
    db: DBSessionType = Depends(get_db),
    current_user: Optional[DBUser] = Depends(get_optional_user),
):
    """
    Switch to a different bot mid-conversation.

    1. Ends the current session with status='switched'
    2. Builds a conversation summary from the current session
    3. Creates a new session with the new bot, injecting the summary as context
    4. Returns the new session with the new bot's greeting
    """
    new_bot_str = request.get("new_bot")
    if not new_bot_str or new_bot_str not in [b.value for b in BotArm]:
        raise HTTPException(status_code=400, detail=f"Invalid bot: {new_bot_str}. Use: sally_nepq, hank_hypes, ivy_informs")

    new_arm = BotArm(new_bot_str)

    # Find current session
    db_session = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not db_session:
        raise HTTPException(status_code=404, detail="Session not found")

    current_arm = BotArm(db_session.assigned_arm) if db_session.assigned_arm else BotArm.SALLY_NEPQ
    if current_arm == new_arm:
        raise HTTPException(status_code=400, detail="Already talking to this bot")

    # Build conversation summary from the current session
    messages = (
        db.query(DBMessage)
        .filter(DBMessage.session_id == session_id)
        .order_by(DBMessage.timestamp)
        .all()
    )

    # Create a compact summary of the conversation so far
    summary_lines = []
    for m in messages[-20:]:  # Last 20 messages max
        role = "User" if m.role == "user" else "Bot"
        content = m.content[:200] + "..." if len(m.content) > 200 else m.content
        summary_lines.append(f"{role}: {content}")
    conversation_summary = "\n".join(summary_lines)

    # Get prospect profile from current session
    profile_json = db_session.prospect_profile or "{}"

    # End current session as "switched"
    db_session.status = "switched"
    db_session.end_time = time.time()
    if hasattr(db_session, 'sms_state') and db_session.sms_state:
        db_session.sms_state = "done"

    # Create new session
    new_session_id = str(uuid.uuid4())[:8].upper()
    now = time.time()
    initial_phase = NepqPhase.CONNECTION.value if new_arm == BotArm.SALLY_NEPQ else "CONVERSATION"

    visitor_id = db_session.visitor_id
    user_id = current_user.id if current_user else getattr(db_session, 'user_id', None)

    # Inject switch context into prospect profile for Sally to read on first turn
    try:
        profile_data = json.loads(profile_json) if profile_json and profile_json != "{}" else {}
    except (json.JSONDecodeError, Exception):
        profile_data = {}
    profile_data["_switch_context"] = conversation_summary
    enriched_profile_json = json.dumps(profile_data)

    new_db_session = DBSession(
        id=new_session_id,
        status="active",
        current_phase=initial_phase,
        pre_conviction=db_session.pre_conviction,
        assigned_arm=new_arm.value,
        visitor_id=visitor_id,
        user_id=user_id,
        phone_number=getattr(db_session, 'phone_number', None),
        channel=getattr(db_session, 'channel', 'web'),
        sms_state="active" if getattr(db_session, 'channel', None) == "sms" else None,
        experiment_mode=getattr(db_session, 'experiment_mode', None),
        start_time=now,
        message_count=1,
        retry_count=0,
        turn_number=0,
        prospect_profile=enriched_profile_json,
        thought_logs="[]",
    )
    db.add(new_db_session)

    # Generate a context-aware greeting from the new bot
    # Inject the conversation summary so the new bot knows what was discussed
    switch_context = (
        f"[SYSTEM: The user just switched from {BOT_DISPLAY_NAMES[current_arm]} to you. "
        f"Here is a summary of their conversation so far:\n\n"
        f"{conversation_summary}\n\n"
        f"Acknowledge the switch briefly and naturally, then continue the conversation "
        f"from where it left off. Do NOT re-introduce yourself with your standard greeting. "
        f"Do NOT restart the conversation from scratch. Reference something specific "
        f"from the summary to show you have context.]"
    )

    # Generate a contextual greeting using Claude
    from app.bots.base import get_client as get_anthropic_client
    try:
        bot_instance = None
        if new_arm == BotArm.HANK_HYPES:
            from app.bots.hank import HankBot
            bot_instance = HankBot()
        elif new_arm == BotArm.IVY_INFORMS:
            from app.bots.ivy import IvyBot
            bot_instance = IvyBot()

        if bot_instance:
            # For Hank/Ivy: use their system prompt + switch context
            response = get_anthropic_client().messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=200,
                system=bot_instance.system_prompt,
                messages=[{"role": "user", "content": switch_context}],
            )
            greeting_text = response.content[0].text.strip()
        else:
            # For Sally: generate a contextual greeting using the conversation summary
            sally_switch_prompt = (
                f"You are Sally from 100x. The user just switched to you from another AI assistant. "
                f"Here's what they discussed:\n\n{conversation_summary}\n\n"
                f"Write a brief, warm greeting (2 sentences max) that acknowledges you have context "
                f"and asks a natural follow-up question based on what they shared. "
                f"Sound like a friend, not a robot."
            )
            response = get_anthropic_client().messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=150,
                messages=[{"role": "user", "content": sally_switch_prompt}],
            )
            greeting_text = response.content[0].text.strip()
    except Exception as e:
        logger.error(f"[Switch] Failed to generate contextual greeting: {e}")
        greeting_text = f"Hey, I'm {BOT_DISPLAY_NAMES[new_arm]}. I've got context from your previous chat — let's continue."

    # Save greeting message
    greeting_id = str(uuid.uuid4())
    greeting_msg = DBMessage(
        id=greeting_id,
        session_id=new_session_id,
        role="assistant",
        content=greeting_text,
        timestamp=now,
        phase=initial_phase,
    )
    db.add(greeting_msg)
    db.commit()

    # Trigger memory extraction on the ended session (background thread)
    if visitor_id or user_id:
        try:
            mem_transcript = [{"role": m.role, "content": m.content, "phase": m.phase} for m in messages]
            def _extract():
                try:
                    extraction = extract_memory_from_session(
                        session_id=session_id, visitor_id=visitor_id or "",
                        transcript=mem_transcript, profile_json=profile_json,
                        outcome="switched", final_phase=db_session.current_phase,
                        bot_arm=current_arm.value,
                    )
                    if extraction:
                        store_memory(
                            db_session_maker=_get_session_local(),
                            session_id=session_id, visitor_id=visitor_id or "",
                            extraction=extraction, user_id=user_id,
                            bot_arm=current_arm.value,
                        )
                except Exception as e:
                    logger.error(f"[Switch] Memory extraction failed for {session_id}: {e}")
            threading.Thread(target=_extract, daemon=True).start()
        except Exception as e:
            logger.error(f"[Switch] Memory extraction thread failed: {e}")

    logger.info(f"[Switch] {session_id} ({current_arm.value}) → {new_session_id} ({new_arm.value})")

    return {
        "previous_session_id": session_id,
        "new_session_id": new_session_id,
        "new_arm": new_arm.value,
        "bot_display_name": BOT_DISPLAY_NAMES[new_arm],
        "current_phase": initial_phase,
        "greeting": {
            "id": greeting_id,
            "role": "assistant",
            "content": greeting_text,
            "timestamp": now,
            "phase": initial_phase,
        },
    }


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
