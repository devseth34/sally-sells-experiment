from __future__ import annotations
"""
Sally Sells — Layer 1: Comprehension Layer (The Analyst)

This layer examines each user message and produces a structured
ComprehensionOutput. It NEVER talks to the prospect — it only listens
and analyzes.
"""

import json
import os
import logging
from pathlib import Path
import google.generativeai as genai

# dotenv is loaded once in database.py (first import in main.py)

from app.schemas import NepqPhase
from app.models import (
    ComprehensionOutput,
    PhaseExitEvaluation,
    CriterionResult,
    ObjectionType,
    UserIntent,
    ProspectProfile,
)
from app.phase_definitions import get_phase_definition, get_exit_criteria_checklist

logger = logging.getLogger("sally.comprehension")



COMPREHENSION_SYSTEM_PROMPT_BASE = """You are a senior sales conversation analyst working behind the glass in a high-stakes B2B NEPQ (Neuro-Emotional Persuasion Questioning) sales process.

You are NOT the salesperson. You analyze each prospect message and produce a structured assessment.

YOUR TWO JOBS:
A) FACTUAL ANALYSIS — Extract what they said (intent, objections, profile data, exit criteria checklist)
B) EMOTIONAL INTELLIGENCE — Extract HOW they said it (their exact memorable phrases, emotional signals, energy level)

CRITICAL RULES:
1. Only extract information the prospect EXPLICITLY stated. Never infer or assume.
2. For pain_points and frustrations, only include what the PROSPECT said, not what the salesperson suggested.
3. EXIT CRITERIA CHECKLIST — For each criterion, evaluate TRUE or FALSE with evidence:
   - Mark TRUE only when there is CLEAR evidence from the conversation (current message OR earlier in conversation history OR already in the profile).
   - Mark FALSE when the criterion has not been addressed or evidence is too vague.
   - ALWAYS check the existing profile. If role is already filled from a previous turn, the "role_shared" criterion IS met.
   - Short answers CAN satisfy criteria. "I'm a dev at a fintech startup" satisfies BOTH role_shared AND company_or_industry_shared.
   - "yeah" or "ok" with no new info satisfies NOTHING new.
   - Be ACCURATE, not conservative.
4. NEW INFORMATION DETECTION:
   - TRUE: The prospect shared something concrete not already in the profile.
   - FALSE: Filler ("yeah", "ok"), repetition, or vague non-answers.
5. Objection detection: "too expensive" = PRICE, "need to ask my boss" = AUTHORITY, "not sure we need this" = NEED, "maybe next quarter" = TIMING.

RESPONSE QUALITY ASSESSMENT:
6. response_richness:
   - "thin": 1-5 words, filler, vague
   - "moderate": Real sentence with specifics, no emotional language
   - "rich": Multi-sentence, vivid detail, emotional language

7. emotional_depth:
   - "surface": Named a topic factually, no feeling
   - "moderate": Expressed a feeling or emotional engagement
   - "deep": Real vulnerability, fear, personal stakes

EMOTIONAL INTELLIGENCE:
8. prospect_exact_words: 2-3 most MEANINGFUL phrases worth mirroring. NOT filler.
9. emotional_cues: SPECIFIC emotional signals with context.
10. energy_level: "low/flat" | "neutral" | "warm" | "high/excited"

11. CONFUSION DETECTION: "I don't understand", "what do you mean", "huh?" → user_intent = "CONFUSION". CONFUSION is NOT PUSHBACK. If both, classify as CONFUSION.
"""

COMPREHENSION_OWNERSHIP_SECTION = """
OWNERSHIP PHASE EXIT CRITERIA RULES:
- commitment_question_asked: TRUE if Sally asked a "do you feel like..." commitment question. FALSE if she jumped straight to price.
- prospect_self_persuaded: TRUE if the PROSPECT articulated at least one specific reason why they feel the solution could work. Must be prospect's own words, not just "yeah".
- price_stated: TRUE if the $10,000 price has been explicitly mentioned.
- definitive_response: TRUE if prospect gave a clear yes to paid, yes to free, or clear no. "Not sure" is NOT definitive.

OBJECTION DIFFUSION STATUS (OWNERSHIP only):
- "not_applicable": No active objection being diffused
- "diffused": Sally lowered the temperature and prospect hasn't re-escalated
- "isolated": Sally asked "[objection] aside, do you still want this?" and prospect said yes
- "resolved": Prospect agreed to move forward despite the objection
- "repeated": Prospect raised the SAME objection again after Sally's diffusion
"""


def _build_system_prompt(current_phase: NepqPhase) -> str:
    """Build phase-appropriate comprehension system prompt."""
    prompt = COMPREHENSION_SYSTEM_PROMPT_BASE
    late_phases = {NepqPhase.OWNERSHIP, NepqPhase.COMMITMENT}
    if current_phase in late_phases:
        prompt += COMPREHENSION_OWNERSHIP_SECTION
    return prompt


def build_comprehension_prompt(
    current_phase: NepqPhase,
    user_message: str,
    conversation_history: list[dict],
    prospect_profile: ProspectProfile,
) -> str:
    """Build the analysis prompt for Layer 1."""

    phase_def = get_phase_definition(current_phase)
    checklist = get_exit_criteria_checklist(current_phase)

    # Format conversation history (last 10 messages for context)
    recent_history = conversation_history[-10:]
    history_text = ""
    for msg in recent_history:
        role = "SALLY" if msg["role"] == "assistant" else "PROSPECT"
        history_text += f"{role}: {msg['content']}\n"

    # Format current profile state
    profile_dict = prospect_profile.model_dump(exclude_none=True)
    profile_dict = {k: v for k, v in profile_dict.items() if v and v != []}

    # Build checklist section for the prompt
    checklist_prompt = ""
    for criterion_id, description in checklist.items():
        checklist_prompt += f'    "{criterion_id}": {{"met": true/false, "evidence": "<specific evidence or null>"}},\n'

    # Phase-relevant profile fields only
    extraction_targets = phase_def.get("extraction_targets", [])
    profile_fields_str = ", ".join(extraction_targets) if extraction_targets else "name, role, company, industry"

    prompt = f"""Analyze the prospect's latest message.
##
PHASE: {current_phase.value}
PURPOSE: {phase_def.get('purpose', 'N/A')}

EXIT CRITERIA — Evaluate EACH as true/false:
{json.dumps(checklist, indent=2)}

PROSPECT PROFILE SO FAR:
{json.dumps(profile_dict, indent=2) if profile_dict else "Nothing yet."}

CONVERSATION:
{history_text}

LATEST MESSAGE: "{user_message}"

Respond with this EXACT JSON:
{{
    "user_intent": "DIRECT_ANSWER" | "DEFLECTION" | "QUESTION" | "OBJECTION" | "SMALL_TALK" | "AGREEMENT" | "PUSHBACK" | "CONFUSION",
    "emotional_tone": "<one or two words>",
    "emotional_intensity": "low" | "medium" | "high",
    "objection_type": "PRICE" | "TIMING" | "AUTHORITY" | "NEED" | "NONE",
    "objection_detail": "<specific objection or null>",
    "profile_updates": {{
        "<field>": "<value from this message>"
    }},
    "exit_evaluation": {{
        "criteria": {{
{checklist_prompt}        }},
        "reasoning": "<brief reasoning>",
        "missing_info": ["<what still needs to be uncovered>"]
    }},
    "response_richness": "thin" | "moderate" | "rich",
    "emotional_depth": "surface" | "moderate" | "deep",
    "new_information": true/false,
    "objection_diffusion_status": "not_applicable" | "diffused" | "isolated" | "resolved" | "repeated",
    "prospect_exact_words": ["<2-3 meaningful phrases worth mirroring>"],
    "emotional_cues": ["<emotional signals with context>"],
    "energy_level": "low/flat" | "neutral" | "warm" | "high/excited",
    "summary": "<one sentence>"
}}

PROFILE FIELDS FOR THIS PHASE: {profile_fields_str}
For list fields (pain_points, frustrations, tools_mentioned, success_metrics), provide ONLY NEW items.
Evaluate criteria CUMULATIVELY across the entire conversation, not just the latest message.
Check existing profile — if role is already filled, role_shared IS met."""

    early_phases = {NepqPhase.CONNECTION, NepqPhase.SITUATION, NepqPhase.PROBLEM_AWARENESS, NepqPhase.SOLUTION_AWARENESS}
    if current_phase in early_phases:
        prompt += """
Set objection_diffusion_status to "not_applicable" for this phase."""

    prompt += """

Return ONLY the JSON. No markdown, no explanation."""

    return prompt


# Lazy client config — configured on first use
_gemini_configured = False

def _ensure_gemini_configured():
    global _gemini_configured
    if not _gemini_configured:
        load_dotenv(_ENV_PATH, override=True)
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(f"GEMINI_API_KEY not found. Checked .env at: {_ENV_PATH}")
        genai.configure(api_key=api_key)
        _gemini_configured = True


def run_comprehension(
    current_phase: NepqPhase,
    user_message: str,
    conversation_history: list[dict],
    prospect_profile: ProspectProfile,
) -> ComprehensionOutput:
    """
    Run Layer 1 analysis on a user message using Gemini Flash.
    """

    system_prompt = _build_system_prompt(current_phase)
    user_prompt = build_comprehension_prompt(
        current_phase, user_message, conversation_history, prospect_profile
    )

    _ensure_gemini_configured()

    model = genai.GenerativeModel(
        "gemini-2.0-flash",
        system_instruction=system_prompt,
    )

    response = model.generate_content(
        user_prompt,
        generation_config=genai.types.GenerationConfig(
            max_output_tokens=1500,
            temperature=0.1,
        ),
        safety_settings=[
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ],
    )

    raw_text = response.text.strip()

    raw_text = response.text.strip()

    # Clean potential markdown wrapping
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1] if "\n" in raw_text else raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        # Retry once — Gemini occasionally truncates JSON
        logger.warning(f"Gemini JSON parse failed, retrying. Fragment: {raw_text[:200]}")
        try:
            retry_response = model.generate_content(
                user_prompt,
                generation_config=genai.types.GenerationConfig(
                    max_output_tokens=1500,
                    temperature=0.1,
                ),
                safety_settings=[
                    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                ],
            )
            raw_text = retry_response.text.strip()
            if raw_text.startswith("```"):
                raw_text = raw_text.split("\n", 1)[1] if "\n" in raw_text else raw_text[3:]
                if raw_text.endswith("```"):
                    raw_text = raw_text[:-3]
                raw_text = raw_text.strip()
            data = json.loads(raw_text)
            logger.info("Gemini retry succeeded")
        except (json.JSONDecodeError, Exception) as retry_err:
            logger.error(f"Gemini retry also failed: {retry_err}")
        checklist = get_exit_criteria_checklist(current_phase)
        default_criteria = {
            cid: CriterionResult(met=False, evidence=None)
            for cid in checklist
        }
        return ComprehensionOutput(
            user_intent=UserIntent.DIRECT_ANSWER,
            emotional_tone="neutral",
            objection_type=ObjectionType.NONE,
            objection_detail=None,
            profile_updates={},
            exit_evaluation=PhaseExitEvaluation(
                criteria=default_criteria,
                reasoning="Failed to parse LLM output",
                missing_info=["Unable to analyze this turn"],
            ),
            new_information=False,
            summary="Analysis failed — defaulting to safe state",
        )

    # Build checklist criteria from parsed data
    raw_criteria = data.get("exit_evaluation", {}).get("criteria", {})
    criteria = {}
    for cid, cval in raw_criteria.items():
        if isinstance(cval, dict):
            criteria[cid] = CriterionResult(
                met=bool(cval.get("met", False)),
                evidence=cval.get("evidence"),
            )
        else:
            criteria[cid] = CriterionResult(met=bool(cval), evidence=None)

    exit_eval = PhaseExitEvaluation(
        criteria=criteria,
        reasoning=data.get("exit_evaluation", {}).get("reasoning", ""),
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
        response_richness=data.get("response_richness", "moderate"),
        emotional_depth=data.get("emotional_depth", "surface"),
        prospect_exact_words=data.get("prospect_exact_words", []),
        emotional_cues=data.get("emotional_cues", []),
        energy_level=data.get("energy_level", "neutral"),
        new_information=data.get("new_information", True),
        objection_diffusion_status=data.get("objection_diffusion_status", "not_applicable"),
        summary=data.get("summary", ""),
    )