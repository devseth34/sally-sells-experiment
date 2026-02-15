from __future__ import annotations
"""
Sally Sells — Layer 1: Comprehension Layer (The Analyst)

This layer examines each user message and produces a structured
ComprehensionOutput. It NEVER talks to the prospect — it only listens
and analyzes.
"""

import json
import os
from pathlib import Path
from dotenv import load_dotenv
from anthropic import Anthropic

# Resolve .env path using absolute path — immune to cwd changes from uvicorn --reload
_ENV_PATH = Path(__file__).resolve().parent.parent.parent.parent / ".env"
load_dotenv(_ENV_PATH, override=True)

from app.schemas import NepqPhase
from app.models import (
    ComprehensionOutput,
    PhaseExitEvaluation,
    ObjectionType,
    UserIntent,
    ProspectProfile,
)
from app.phase_definitions import get_phase_definition

# Lazy client — created on first use, not at import time
_client: Anthropic | None = None

def _get_client() -> Anthropic:
    global _client
    if _client is None:
        load_dotenv(_ENV_PATH, override=True)
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(f"ANTHROPIC_API_KEY not found. Checked .env at: {_ENV_PATH}")
        _client = Anthropic(api_key=api_key)
    return _client

COMPREHENSION_SYSTEM_PROMPT = """You are a senior sales conversation analyst AND emotional intelligence expert working behind the glass in a high-stakes B2B NEPQ (Neuro-Emotional Persuasion Questioning) sales process.

You are NOT the salesperson. You analyze each prospect message and produce a structured assessment. Your analysis powers the salesperson's ability to mirror, empathize, and respond with genuine emotional intelligence.

YOUR TWO JOBS:
A) FACTUAL ANALYSIS — Extract what they said (intent, objections, profile data, exit criteria progress)
B) EMOTIONAL INTELLIGENCE — Extract HOW they said it (their exact memorable phrases, emotional signals, energy level, what they need to feel heard)

CRITICAL RULES:
1. Only extract information the prospect EXPLICITLY stated. Never infer or assume.
2. For pain_points and frustrations, only include what the PROSPECT said, not what the salesperson suggested.
3. CONFIDENCE SCORING — assess CUMULATIVELY across the ENTIRE conversation + existing profile:
   - 0-25%: Prospect hasn't addressed ANY exit criteria yet (first message, off-topic, or pure small talk)
   - 26-45%: Prospect has addressed ONE exit criterion partially or vaguely
   - 46-65%: Prospect has addressed at LEAST TWO exit criteria with some substance (even if brief)
   - 66-80%: Prospect has addressed MOST exit criteria clearly. Short answers count IF they contain real info (e.g. "I'm a dev" = role provided, even if brief)
   - 81-100%: ALL exit criteria are clearly met with concrete evidence
4. IMPORTANT: Short answers CAN be high-confidence if they contain real information.
   "I'm a dev at a fintech startup, looking into AI for automation" in ONE message = role + company context + reason = most CONNECTION criteria MET. That's 66%+ even though it's one sentence.
   "yeah" or "ok" with no new info = barely moves the needle.
5. ALWAYS look at the existing profile fields. If the profile already has role, company, etc. from earlier turns, those criteria ARE MET. Don't re-penalize for information already gathered.
6. Objection detection: "too expensive" = PRICE, "need to ask my boss" = AUTHORITY, "not sure we need this" = NEED, "maybe next quarter" = TIMING.
7. The goal is ACCURATE assessment, not conservative assessment. Under-scoring is just as bad as over-scoring because it traps the conversation in a loop.

EMOTIONAL INTELLIGENCE RULES:
8. prospect_exact_words: Pick the 2-3 most MEANINGFUL phrases the prospect said that deserve to be mirrored. These are the words that carry emotion, identity, or vulnerability. NOT filler.
   - Good: "it takes forever", "we're drowning in spreadsheets", "I'm basically a one-man army"
   - Bad: "yeah", "ok", "sure" (these are filler, not mirrorable)
9. emotional_cues: Identify SPECIFIC emotional signals with context. Not just "frustrated" but "frustrated about manual work consuming 2 days/week". Connect the emotion to what triggered it.
10. energy_level: Read their vibe.
   - "low/flat": short answers, disengaged, monosyllabic
   - "neutral": answering normally, neither excited nor checked out
   - "warm": sharing openly, friendly, engaged
   - "high/excited": passionate, detailed, animated, using exclamation marks or emphatic language
"""


def build_comprehension_prompt(
    current_phase: NepqPhase,
    user_message: str,
    conversation_history: list[dict],
    prospect_profile: ProspectProfile,
) -> str:
    """Build the analysis prompt for Layer 1."""

    phase_def = get_phase_definition(current_phase)

    # Format conversation history (last 10 messages for context)
    recent_history = conversation_history[-10:]
    history_text = ""
    for msg in recent_history:
        role = "SALLY" if msg["role"] == "assistant" else "PROSPECT"
        history_text += f"{role}: {msg['content']}\n"

    # Format current profile state
    profile_dict = prospect_profile.model_dump(exclude_none=True)
    # Remove empty lists
    profile_dict = {k: v for k, v in profile_dict.items() if v and v != []}

    prompt = f"""Analyze the prospect's latest message in this sales conversation.

CURRENT PHASE: {current_phase.value}
PHASE PURPOSE: {phase_def.get('purpose', 'N/A')}

EXIT CRITERIA FOR THIS PHASE:
{json.dumps(phase_def.get('exit_criteria', []), indent=2)}

WHAT WE KNOW ABOUT THE PROSPECT SO FAR:
{json.dumps(profile_dict, indent=2) if profile_dict else "Nothing yet — this may be early in the conversation."}

RECENT CONVERSATION:
{history_text}

LATEST PROSPECT MESSAGE:
"{user_message}"

Produce your analysis as a JSON object with this EXACT structure:
{{
    "user_intent": "DIRECT_ANSWER" | "DEFLECTION" | "QUESTION" | "OBJECTION" | "SMALL_TALK" | "AGREEMENT" | "PUSHBACK",
    "emotional_tone": "<one or two words: engaged, skeptical, frustrated, defensive, excited, neutral, warm, guarded, etc.>",
    "emotional_intensity": "low" | "medium" | "high",
    "objection_type": "PRICE" | "TIMING" | "AUTHORITY" | "NEED" | "NONE",
    "objection_detail": "<specific objection if any, or null>",
    "profile_updates": {{
        "<field_name>": "<value extracted from this message>"
    }},
    "exit_evaluation": {{
        "confidence": <0-100>,
        "reasoning": "<why this confidence level>",
        "key_evidence": ["<specific things the prospect said>"],
        "missing_info": ["<what still needs to be uncovered>"]
    }},
    "prospect_exact_words": ["<2-3 exact phrases from their message worth mirroring back — the words that carry emotion, identity, or vulnerability>"],
    "emotional_cues": ["<specific emotional signals with context, e.g. 'frustrated about manual reporting consuming 2 days/week', 'proud of building the team from scratch'>"],
    "energy_level": "low/flat" | "neutral" | "warm" | "high/excited",
    "summary": "<one sentence: what happened this turn>"
}}

PROFILE FIELDS YOU CAN UPDATE:
- name, role, company, industry
- current_state, team_size, tools_mentioned (list)
- pain_points (list — APPEND, don't replace), frustrations (list — APPEND)
- desired_state, success_metrics (list)
- cost_of_inaction, timeline_pressure, competitive_risk
- decision_authority, decision_timeline, budget_signals
- email, phone

CRITICAL: For list fields (pain_points, frustrations, tools_mentioned, success_metrics), provide ONLY the NEW items to add, not the full list.

IMPORTANT: The exit_evaluation.confidence MUST reflect CUMULATIVE progress across the ENTIRE conversation, not just the latest message.
- Check each exit criterion against BOTH the existing profile AND the new message
- If the profile already has "role" filled from a previous turn, that criterion IS met regardless of the current message
- Count how many exit criteria are satisfied total, then score accordingly
- A conversation where 2 of 3 exit criteria are already met should score 66%+, even if the latest message only addresses the third

Return ONLY the JSON object. No markdown, no explanation."""

    return prompt


def run_comprehension(
    current_phase: NepqPhase,
    user_message: str,
    conversation_history: list[dict],
    prospect_profile: ProspectProfile,
) -> ComprehensionOutput:
    """
    Run Layer 1 analysis on a user message.

    Returns a structured ComprehensionOutput with intent classification,
    objection detection, profile updates, and exit criteria evaluation.
    """

    prompt = build_comprehension_prompt(
        current_phase, user_message, conversation_history, prospect_profile
    )

    response = _get_client().messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=800,
        system=COMPREHENSION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    # Parse the JSON response
    raw_text = response.content[0].text.strip()

    # Clean potential markdown wrapping
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1]  # Remove first line
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        # Fallback: return a safe default
        return ComprehensionOutput(
            user_intent=UserIntent.DIRECT_ANSWER,
            emotional_tone="neutral",
            objection_type=ObjectionType.NONE,
            objection_detail=None,
            profile_updates={},
            exit_evaluation=PhaseExitEvaluation(
                confidence=30,
                reasoning="Failed to parse LLM output",
                key_evidence=[],
                missing_info=["Unable to analyze this turn"],
            ),
            summary="Analysis failed — defaulting to safe state",
        )

    # Build the ComprehensionOutput from parsed data
    exit_eval = PhaseExitEvaluation(
        confidence=data.get("exit_evaluation", {}).get("confidence", 30),
        reasoning=data.get("exit_evaluation", {}).get("reasoning", ""),
        key_evidence=data.get("exit_evaluation", {}).get("key_evidence", []),
        missing_info=data.get("exit_evaluation", {}).get("missing_info", []),
    )

    return ComprehensionOutput(
        user_intent=UserIntent(data.get("user_intent", "DIRECT_ANSWER")),
        emotional_tone=data.get("emotional_tone", "neutral"),
        emotional_intensity=data.get("emotional_intensity", "medium"),
        objection_type=ObjectionType(data.get("objection_type", "NONE")),
        objection_detail=data.get("objection_detail"),
        profile_updates=data.get("profile_updates", {}),
        exit_evaluation=exit_eval,
        prospect_exact_words=data.get("prospect_exact_words", []),
        emotional_cues=data.get("emotional_cues", []),
        energy_level=data.get("energy_level", "neutral"),
        summary=data.get("summary", ""),
    )
