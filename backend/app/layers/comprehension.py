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
_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
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

COMPREHENSION_SYSTEM_PROMPT = """You are a sales conversation analyst. You analyze prospect messages in a B2B sales context.

You are NOT the salesperson. You are the analyst sitting behind the glass, studying the conversation.

Your job is to produce a structured JSON analysis of what the prospect just said. Be precise and evidence-based — only report what you can actually see in the message, not what you assume.

IMPORTANT RULES:
- Only extract information the prospect explicitly stated. Do NOT infer or assume.
- For pain_points and frustrations, only include things the PROSPECT said, not things the salesperson suggested.
- Be conservative with confidence scores. If the prospect gave a vague answer, that's lower confidence than a specific one.
- Objection detection should be specific: "too expensive" is PRICE, "need to ask my boss" is AUTHORITY, "not sure we need this" is NEED, "maybe next quarter" is TIMING.
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

IMPORTANT: The exit_evaluation.confidence should reflect how well ALL the exit criteria are met CUMULATIVELY across the entire conversation, not just this one message. Look at the full profile + this message together.

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
        model="claude-3-haiku-20240307",
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
        objection_type=ObjectionType(data.get("objection_type", "NONE")),
        objection_detail=data.get("objection_detail"),
        profile_updates=data.get("profile_updates", {}),
        exit_evaluation=exit_eval,
        summary=data.get("summary", ""),
    )
