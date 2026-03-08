"""
Sally Sells — Memory Extraction & Retrieval

Extracts structured facts and summaries from completed sessions.
Runs asynchronously after session end (same pattern as quality_scorer.py).
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Optional

import google.generativeai as genai

from app.database import DBMemoryFact, DBSessionSummary, DBSession, DBMessage

logger = logging.getLogger("sally.memory")

# Lazy Gemini config (same pattern as comprehension.py)
_gemini_configured = False


def _ensure_gemini():
    global _gemini_configured
    if not _gemini_configured:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not found")
        genai.configure(api_key=api_key)
        _gemini_configured = True


EXTRACTION_PROMPT = """You are a relationship memory system for an NEPQ sales conversation platform.
Your job is to extract BOTH factual information AND emotional/relational context from this conversation.

Think of yourself as a friend taking mental notes so they can pick up the conversation naturally next time.

CONVERSATION TRANSCRIPT:
{transcript}

PROSPECT PROFILE (extracted during conversation):
{profile}

SESSION OUTCOME: {outcome}
FINAL PHASE REACHED: {final_phase}

Extract the following as JSON. Only include fields where you have CLEAR evidence.
Do NOT infer or assume anything not explicitly stated.

Return this EXACT JSON structure:
{{
    "identity": {{
        "name": "<their name or null>",
        "role": "<their job title/role or null>",
        "company": "<company name or null>",
        "industry": "<industry or null>"
    }},
    "situation": {{
        "team_size": "<string or null>",
        "tools_mentioned": ["<tools/platforms they use>"],
        "workflow_description": "<how they work day-to-day or null>",
        "desired_state": "<what they want to achieve or null>"
    }},
    "pain_points": ["<specific pain points in THEIR words>"],
    "objection_history": ["<objections raised, e.g. 'PRICE: said $10k is too much for their budget right now'>"],

    "relationship_context": {{
        "rapport_level": "<cold | warming | warm | strong>",
        "trust_signals": ["<moments where they opened up or showed trust, e.g. 'admitted they felt overwhelmed managing 3 people'>"],
        "resistance_signals": ["<moments of pushback or guardedness, e.g. 'deflected when asked about budget'>"],
        "personal_details": ["<non-business things they mentioned: kids, location, hobbies, background, e.g. 'mentioned they just moved to Austin'>"],
        "humor_moments": ["<anything funny or lighthearted that happened, e.g. 'joked about their CRM being held together with duct tape'>"],
        "their_language_style": "<how they communicate: formal/casual, short/long answers, uses emoji, technical jargon, etc.>",
        "energy_pattern": "<how their energy changed through the conversation: started low but warmed up, consistently engaged, lost interest midway, etc.>"
    }},

    "emotional_peaks": [
        {{
            "moment": "<what was being discussed>",
            "emotion": "<what they seemed to feel: excited, frustrated, vulnerable, proud, anxious>",
            "their_words": "<their actual phrase that showed this emotion>",
            "phase": "<which NEPQ phase this happened in>"
        }}
    ],

    "strategic_notes": {{
        "what_worked": "<what approach or question got the best response from them>",
        "what_didnt_work": "<what approach fell flat or caused them to disengage>",
        "unfinished_threads": ["<topics that came up but weren't fully explored, e.g. 'mentioned wanting to automate invoicing but we moved on'>"],
        "next_session_strategy": "<if they come back, what's the best approach? e.g. 'They were close to saying yes but need to check with their CEO. Start by asking if they talked to their CEO.'>",
        "objection_vulnerability": "<their weakest objection point, e.g. 'price objection was soft — they acknowledged the ROI but said timing was bad. Timing is the real blocker.'>"
    }},

    "session_summary": "<2-3 sentences written as if you're briefing a friend who's about to call this person. Be specific and human, not clinical. Example: 'Alex runs sales at a 12-person fintech startup. He's drowning in manual follow-ups and knows AI could help but balked at the $10k price. He was genuinely interested though — got really animated when we talked about automating his Apollo workflows. I think if you lead with the free workshop he'd convert later.'>",
    "conversation_outcome": "<one of: completed_paid, completed_free, abandoned_early, abandoned_mid, abandoned_late, hard_no, still_exploring>"
}}

Return ONLY the JSON. No markdown, no explanation."""


def extract_memory_from_session(
    session_id: str,
    visitor_id: str,
    transcript: list[dict],
    profile_json: str,
    outcome: str,
    final_phase: str,
    bot_arm: str = "unknown",
) -> dict:
    """
    Run Gemini to extract structured memory from a completed session.
    Returns the parsed extraction dict.
    """
    _ensure_gemini()

    # Build transcript text with bot-specific role label
    bot_names = {"sally_nepq": "Sally", "hank_hypes": "Hank", "ivy_informs": "Ivy"}
    bot_display = bot_names.get(bot_arm, "Agent")

    transcript_text = ""
    for msg in transcript:
        role = bot_display if msg.get("role") == "assistant" else "Prospect"
        transcript_text += f"{role}: {msg.get('content', '')}\n"

    prompt = EXTRACTION_PROMPT.format(
        transcript=transcript_text,
        profile=profile_json,
        outcome=outcome,
        final_phase=final_phase,
    )
    # Add bot context so extraction knows which bot had the conversation
    prompt = f"BOT THAT HAD THIS CONVERSATION: {bot_arm}\n\n" + prompt

    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=2500,
                temperature=0.1,
            ),
        )
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        return json.loads(raw)
    except Exception as e:
        logger.error(f"[Session {session_id}] Memory extraction failed: {e}")
        return {}


def store_memory(db_session_maker, session_id: str, visitor_id: str, extraction: dict, user_id: str = None, bot_arm: str = "unknown"):
    """
    Store extracted memory facts and session summary in the database.
    Handles conflict resolution: newer facts supersede older ones.
    """
    db = db_session_maker()
    now = time.time()

    try:
        # --- Store individual facts ---
        facts_to_store = []

        # Identity facts
        identity = extraction.get("identity", {})
        for key in ["name", "role", "company", "industry"]:
            val = identity.get(key)
            if val and str(val).lower() not in ("null", "none", ""):
                facts_to_store.append(("identity", key, str(val)))

        # Situation facts
        situation = extraction.get("situation", {})
        for key in ["team_size", "workflow_description"]:
            val = situation.get(key)
            if val and str(val).lower() not in ("null", "none", ""):
                facts_to_store.append(("situation", key, str(val)))
        tools = situation.get("tools_mentioned", [])
        if tools:
            facts_to_store.append(("situation", "tools_mentioned", json.dumps(tools)))

        # Pain points (each as separate fact)
        for i, pain in enumerate(extraction.get("pain_points", [])):
            if pain:
                facts_to_store.append(("pain_point", f"pain_{i}", pain))

        # Desired state (nested inside situation in the extraction schema)
        desired = situation.get("desired_state")
        if desired and str(desired).lower() not in ("null", "none", ""):
            facts_to_store.append(("situation", "desired_state", str(desired)))

        # Objection history
        for i, obj in enumerate(extraction.get("objection_history", [])):
            if obj:
                facts_to_store.append(("objection_history", f"objection_{i}", obj))

        # Emotional signals (kept for backward compat with old extractions)
        for i, sig in enumerate(extraction.get("emotional_signals", [])):
            if sig:
                facts_to_store.append(("emotional_signal", f"signal_{i}", sig))

        # Relationship context
        relationship = extraction.get("relationship_context", {})
        for key in ["rapport_level", "their_language_style", "energy_pattern"]:
            val = relationship.get(key)
            if val and str(val).lower() not in ("null", "none", ""):
                facts_to_store.append(("relationship", key, str(val)))

        for key in ["trust_signals", "resistance_signals", "personal_details", "humor_moments"]:
            items = relationship.get(key, [])
            for i, item in enumerate(items):
                if item:
                    facts_to_store.append(("relationship", f"{key}_{i}", str(item)))

        # Emotional peaks
        for i, peak in enumerate(extraction.get("emotional_peaks", [])):
            if peak and isinstance(peak, dict):
                facts_to_store.append(("emotional_peak", f"peak_{i}", json.dumps(peak)))

        # Strategic notes
        strategic = extraction.get("strategic_notes", {})
        for key in ["what_worked", "what_didnt_work", "objection_vulnerability", "next_session_strategy"]:
            val = strategic.get(key)
            if val and str(val).lower() not in ("null", "none", ""):
                facts_to_store.append(("strategy", key, str(val)))

        unfinished = strategic.get("unfinished_threads", [])
        for i, thread in enumerate(unfinished):
            if thread:
                facts_to_store.append(("strategy", f"unfinished_thread_{i}", str(thread)))

        # Supersede old facts for same visitor + category + key
        for category, key, value in facts_to_store:
            # Deactivate any existing fact with same category+key for this visitor
            existing = (
                db.query(DBMemoryFact)
                .filter(
                    DBMemoryFact.visitor_id == visitor_id,
                    DBMemoryFact.category == category,
                    DBMemoryFact.fact_key == key,
                    DBMemoryFact.is_active == 1,
                )
                .all()
            )
            for old in existing:
                old.is_active = 0
                old.updated_at = now

            # Insert new fact
            db.add(DBMemoryFact(
                id=str(uuid.uuid4()),
                visitor_id=visitor_id,
                user_id=user_id,
                source_session_id=session_id,
                category=category,
                fact_key=key,
                fact_value=value,
                confidence=1.0,
                created_at=now,
                updated_at=now,
                is_active=1,
            ))

        # --- Store session summary ---
        summary_text = extraction.get("session_summary", "No summary available.")
        outcome_val = extraction.get("conversation_outcome", "unknown")
        pain_points = extraction.get("pain_points", [])
        objections = extraction.get("objection_history", [])

        db.add(DBSessionSummary(
            id=str(uuid.uuid4()),
            visitor_id=visitor_id,
            user_id=user_id,
            session_id=session_id,
            summary_text=summary_text,
            outcome=outcome_val,
            final_phase=extraction.get("final_phase", "unknown"),
            key_pain_points=json.dumps(pain_points),
            key_objections=json.dumps(objections),
            created_at=now,
        ))

        db.commit()
        logger.info(f"[Session {session_id}] Stored {len(facts_to_store)} memory facts + 1 session summary for visitor {visitor_id[:8]}")

    except Exception as e:
        logger.error(f"[Session {session_id}] Failed to store memory: {e}")
        db.rollback()
    finally:
        db.close()


def load_visitor_memory(db, visitor_id: str, user_id: str = None) -> dict:
    """
    Load all active memory for a visitor/user. Returns a dict structured for prompt injection.
    Queries by visitor_id OR user_id (if authenticated) so cross-device memory works.
    """
    from sqlalchemy import or_

    # Build filter: match by visitor_id OR user_id
    conditions = []
    if visitor_id:
        conditions.append(DBMemoryFact.visitor_id == visitor_id)
    if user_id:
        conditions.append(DBMemoryFact.user_id == user_id)

    if not conditions:
        return {"has_memory": False}

    # Load active facts
    facts = (
        db.query(DBMemoryFact)
        .filter(
            or_(*conditions),
            DBMemoryFact.is_active == 1,
        )
        .order_by(DBMemoryFact.updated_at.desc())
        .all()
    )

    # Load session summaries (most recent first, max 3)
    summary_conditions = []
    if visitor_id:
        summary_conditions.append(DBSessionSummary.visitor_id == visitor_id)
    if user_id:
        summary_conditions.append(DBSessionSummary.user_id == user_id)

    summaries = (
        db.query(DBSessionSummary)
        .filter(or_(*summary_conditions))
        .order_by(DBSessionSummary.created_at.desc())
        .limit(3)
        .all()
    )

    if not facts and not summaries:
        return {"has_memory": False}

    # Organize facts by category
    identity = {}
    situation = {}
    pain_points = []
    objection_history = []
    emotional_signals = []
    relationship = {}
    emotional_peaks = []
    strategic_notes = {}
    unfinished_threads = []

    for fact in facts:
        if fact.category == "identity":
            identity[fact.fact_key] = fact.fact_value
        elif fact.category == "situation":
            if fact.fact_key == "tools_mentioned":
                try:
                    situation["tools_mentioned"] = json.loads(fact.fact_value)
                except json.JSONDecodeError:
                    situation["tools_mentioned"] = [fact.fact_value]
            else:
                situation[fact.fact_key] = fact.fact_value
        elif fact.category == "pain_point":
            pain_points.append(fact.fact_value)
        elif fact.category == "objection_history":
            objection_history.append(fact.fact_value)
        elif fact.category == "emotional_signal":
            emotional_signals.append(fact.fact_value)
        elif fact.category == "relationship":
            if fact.fact_key in ("rapport_level", "their_language_style", "energy_pattern"):
                relationship[fact.fact_key] = fact.fact_value
            elif "trust_signal" in fact.fact_key:
                relationship.setdefault("trust_signals", []).append(fact.fact_value)
            elif "resistance_signal" in fact.fact_key:
                relationship.setdefault("resistance_signals", []).append(fact.fact_value)
            elif "personal_detail" in fact.fact_key:
                relationship.setdefault("personal_details", []).append(fact.fact_value)
            elif "humor_moment" in fact.fact_key:
                relationship.setdefault("humor_moments", []).append(fact.fact_value)
        elif fact.category == "emotional_peak":
            try:
                emotional_peaks.append(json.loads(fact.fact_value))
            except json.JSONDecodeError:
                emotional_peaks.append({"moment": fact.fact_value})
        elif fact.category == "strategy":
            if fact.fact_key.startswith("unfinished_thread"):
                unfinished_threads.append(fact.fact_value)
            else:
                strategic_notes[fact.fact_key] = fact.fact_value

    summary_list = [
        {
            "summary": s.summary_text,
            "outcome": s.outcome,
            "phase": s.final_phase,
        }
        for s in summaries
    ]

    return {
        "has_memory": True,
        "identity": identity,
        "situation": situation,
        "pain_points": pain_points,
        "objection_history": objection_history,
        "emotional_signals": emotional_signals,
        "relationship": relationship,
        "emotional_peaks": emotional_peaks,
        "strategic_notes": strategic_notes,
        "unfinished_threads": unfinished_threads,
        "session_summaries": summary_list,
        "total_prior_sessions": len(summaries),
        "session_count": len(summaries),  # alias for total_prior_sessions (used by greeting generator)
    }


def format_memory_for_prompt(memory: dict) -> str:
    """
    Format loaded memory into a natural-language block for prompt injection.
    Designed to help Sally sound like a person who knows this person, not a database readout.
    """
    if not memory.get("has_memory"):
        return ""

    lines = []
    total = memory.get("total_prior_sessions", 0)
    lines.append(f"YOU KNOW THIS PERSON — you've chatted {total} time(s) before.\n")

    # Identity (brief)
    identity = memory.get("identity", {})
    id_parts = []
    if identity.get("name"): id_parts.append(identity["name"])
    if identity.get("role"): id_parts.append(identity["role"])
    if identity.get("company"): id_parts.append(f"at {identity['company']}")
    if identity.get("industry"): id_parts.append(f"({identity['industry']})")
    if id_parts:
        lines.append("Who they are: " + " ".join(id_parts))

    # Situation
    situation = memory.get("situation", {})
    sit_parts = []
    if situation.get("team_size"): sit_parts.append(f"team of {situation['team_size']}")
    if situation.get("tools_mentioned"):
        tools = situation["tools_mentioned"]
        if isinstance(tools, list): sit_parts.append(f"uses {', '.join(tools)}")
    if situation.get("workflow_description"): sit_parts.append(situation["workflow_description"])
    if situation.get("desired_state"): sit_parts.append(f"wants: {situation['desired_state']}")
    if sit_parts:
        lines.append("Their situation: " + " | ".join(sit_parts))

    # Pain points
    pain_points = memory.get("pain_points", [])
    if pain_points:
        lines.append(f"What's bothering them: {'; '.join(pain_points)}")

    # Relationship context
    relationship = memory.get("relationship", {})
    if relationship:
        lines.append("")  # blank line
        lines.append("YOUR RELATIONSHIP WITH THEM:")
        rapport = relationship.get("rapport_level", "unknown")
        lines.append(f"  Rapport: {rapport}")

        style = relationship.get("their_language_style")
        if style:
            lines.append(f"  How they talk: {style}")

        energy = relationship.get("energy_pattern")
        if energy:
            lines.append(f"  Energy pattern: {energy}")

        personal = relationship.get("personal_details", [])
        if personal:
            lines.append(f"  Personal things they shared: {'; '.join(personal[:3])}")

        humor = relationship.get("humor_moments", [])
        if humor:
            lines.append(f"  Inside jokes / funny moments: {'; '.join(humor[:2])}")

        trust = relationship.get("trust_signals", [])
        if trust:
            lines.append(f"  Moments they opened up: {'; '.join(trust[:3])}")

    # Emotional peaks
    peaks = memory.get("emotional_peaks", [])
    if peaks:
        lines.append("")
        lines.append("EMOTIONAL MOMENTS (things that hit them):")
        for peak in peaks[:3]:
            if isinstance(peak, dict):
                moment = peak.get("moment", "")
                emotion = peak.get("emotion", "")
                words = peak.get("their_words", "")
                if moment:
                    line = f"  - {moment}"
                    if emotion: line += f" (they felt: {emotion})"
                    if words: line += f" — they said: \"{words}\""
                    lines.append(line)

    # Strategic notes
    strategic = memory.get("strategic_notes", {})
    if strategic:
        lines.append("")
        lines.append("STRATEGIC INTELLIGENCE:")
        if strategic.get("what_worked"):
            lines.append(f"  What worked last time: {strategic['what_worked']}")
        if strategic.get("what_didnt_work"):
            lines.append(f"  What didn't work: {strategic['what_didnt_work']}")
        if strategic.get("next_session_strategy"):
            lines.append(f"  RECOMMENDED APPROACH: {strategic['next_session_strategy']}")
        if strategic.get("objection_vulnerability"):
            lines.append(f"  Their weakest objection: {strategic['objection_vulnerability']}")

    # Unfinished threads
    unfinished = memory.get("unfinished_threads", [])
    if unfinished:
        lines.append(f"  Unfinished threads to pick up: {'; '.join(unfinished[:3])}")

    # Objection history
    objections = memory.get("objection_history", [])
    if objections:
        lines.append(f"\nPast objections: {'; '.join(objections)}")

    # Session summaries
    summaries = memory.get("session_summaries", [])
    if summaries:
        lines.append("\nPREVIOUS SESSION SUMMARIES:")
        for i, s in enumerate(summaries[:3]):
            lines.append(f"  Session {i+1} ({s['outcome']}, reached {s['phase']}): {s['summary']}")

        # Cross-bot context
        lines.append("")
        lines.append("NOTE: This person may have spoken to different team members previously (Sally, Hank, or Ivy). Each has a different style. Use what you learned from ANY of their conversations, regardless of who they spoke with.")

    lines.append("")
    lines.append("REMEMBER: You KNOW this person. Use this knowledge like a friend would — naturally, never robotically. Never say 'I remember' or 'you previously mentioned'. Just know it.")

    return "\n".join(lines)


def load_recent_conversation_context(db, visitor_id: str, user_id: str = None) -> str:
    """
    Load the actual messages from the most recent completed/abandoned session.
    Returns a formatted string of the last conversation, or empty string if no prior session.
    Limited to 20 most recent messages to stay within token budget.
    """
    from sqlalchemy import or_

    # Build filter for visitor_id OR user_id
    conditions = []
    if visitor_id:
        conditions.append(DBSession.visitor_id == visitor_id)
    if user_id:
        conditions.append(DBSession.user_id == user_id)

    if not conditions:
        return ""

    # Find the most recent non-active session
    recent_session = (
        db.query(DBSession)
        .filter(
            or_(*conditions),
            DBSession.status.in_(["completed", "abandoned"]),
        )
        .order_by(DBSession.end_time.desc())
        .first()
    )

    # Fallback: if no ended session, check for active sessions that have messages
    # (user may have closed tab without session being properly ended)
    if not recent_session:
        recent_session = (
            db.query(DBSession)
            .filter(
                or_(*conditions),
                DBSession.status == "active",
            )
            .order_by(DBSession.start_time.desc())
            .first()
        )

    if not recent_session:
        return ""

    # Load messages from that session (last 20)
    messages = (
        db.query(DBMessage)
        .filter(DBMessage.session_id == recent_session.id)
        .order_by(DBMessage.timestamp)
        .all()
    )

    if not messages:
        return ""

    # Take the last 20 messages
    recent_messages = messages[-20:]

    # Format as conversation
    lines = []
    outcome = recent_session.status  # "completed" or "abandoned"
    phase = recent_session.current_phase or "unknown"
    lines.append(f"LAST CONVERSATION (ended: {outcome}, reached: {phase}):")

    # Use bot-specific role label based on which bot had the session
    bot_names = {"sally_nepq": "Sally", "hank_hypes": "Hank", "ivy_informs": "Ivy"}
    bot_display = bot_names.get(recent_session.assigned_arm, "Agent") if recent_session.assigned_arm else "Sally"

    for msg in recent_messages:
        role = bot_display if msg.role == "assistant" else "Prospect"
        lines.append(f"{role}: {msg.content}")

    return "\n".join(lines)
