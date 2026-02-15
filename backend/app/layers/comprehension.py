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
    CriterionResult,
    ObjectionType,
    UserIntent,
    ProspectProfile,
)
from app.phase_definitions import get_phase_definition, get_exit_criteria_checklist

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
A) FACTUAL ANALYSIS — Extract what they said (intent, objections, profile data, exit criteria checklist)
B) EMOTIONAL INTELLIGENCE — Extract HOW they said it (their exact memorable phrases, emotional signals, energy level, what they need to feel heard)

CRITICAL RULES:
1. Only extract information the prospect EXPLICITLY stated. Never infer or assume.
2. For pain_points and frustrations, only include what the PROSPECT said, not what the salesperson suggested.
3. EXIT CRITERIA CHECKLIST — For each criterion, evaluate TRUE or FALSE with evidence:
   - Mark TRUE only when there is CLEAR evidence from the conversation (current message OR earlier in conversation history OR already in the profile).
   - Mark FALSE when the criterion has not been addressed or evidence is too vague.
   - ALWAYS check the existing profile. If role is already filled from a previous turn, the "role_shared" criterion IS met.
   - Short answers CAN satisfy criteria. "I'm a dev at a fintech startup" satisfies BOTH role_shared AND company_or_industry_shared.
   - "yeah" or "ok" with no new info satisfies NOTHING new.
   - Be ACCURATE, not conservative. Marking something false when it's clearly been addressed is just as bad as marking it true prematurely.
4. NEW INFORMATION DETECTION — Determine if this message contains substantive NEW information:
   - TRUE: The prospect shared something concrete not already in the profile (new facts, details, emotions, decisions).
   - FALSE: The message is filler ("yeah", "ok"), repetition of already-known info, or vague non-answers that add nothing new.
   - This is about whether the CONVERSATION is progressing, not just whether the prospect is talking.
5. Objection detection: "too expensive" = PRICE, "need to ask my boss" = AUTHORITY, "not sure we need this" = NEED, "maybe next quarter" = TIMING.

RESPONSE QUALITY ASSESSMENT:
6. response_richness — How substantive was the prospect's message?
   - "thin": 1-5 words, filler, vague, no real content (e.g., "yeah", "ok", "not sure", "probably data stuff")
   - "moderate": Real sentence with some specifics but no emotional language (e.g., "We do data migration for mid-size companies")
   - "rich": Multi-sentence, vivid detail, stories, emotional language, or vulnerability (e.g., "honestly the worst part is when we find mismatched records at 2am and the whole team has to scramble")

7. emotional_depth — How emotionally engaged is the prospect?
   - "surface": Named a topic factually, no feeling (e.g., "data validation issues", "we use Salesforce", "it takes a while")
   - "moderate": Expressed a feeling or showed some emotional engagement (e.g., "it's frustrating", "I'm worried about X", "that costs us money")
   - "deep": Showed real vulnerability, fear, personal stakes, or vivid emotional language (e.g., "I lie awake thinking about this", "I'm scared I'll lose my job", "my team is burning out and I feel responsible")

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

OBJECTION DIFFUSION STATUS (only relevant in OWNERSHIP phase):
11. objection_diffusion_status — After Sally's diffusion attempt, assess the outcome:
   - "not_applicable": No active objection being diffused
   - "diffused": Sally lowered the temperature ("that's not a problem...") and prospect hasn't re-escalated
   - "isolated": Sally isolated the objection from the desire and prospect confirmed they still want it
   - "resolved": Prospect agreed to move forward despite the objection
   - "repeated": Prospect raised the SAME objection again after Sally's diffusion attempt
"""


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
    # Remove empty lists
    profile_dict = {k: v for k, v in profile_dict.items() if v and v != []}

    # Build checklist section for the prompt
    checklist_prompt = ""
    for criterion_id, description in checklist.items():
        checklist_prompt += f'    "{criterion_id}": {{"met": true/false, "evidence": "<specific evidence or null>"}},\n'

    prompt = f"""Analyze the prospect's latest message in this sales conversation.

CURRENT PHASE: {current_phase.value}
PHASE PURPOSE: {phase_def.get('purpose', 'N/A')}

EXIT CRITERIA CHECKLIST — Evaluate EACH criterion as true/false:
{json.dumps(checklist, indent=2)}

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
        "criteria": {{
{checklist_prompt}        }},
        "reasoning": "<brief reasoning about overall phase progress>",
        "missing_info": ["<what still needs to be uncovered>"]
    }},
    "response_richness": "thin" | "moderate" | "rich",
    "emotional_depth": "surface" | "moderate" | "deep",
    "new_information": true/false,
    "objection_diffusion_status": "not_applicable" | "diffused" | "isolated" | "resolved" | "repeated",
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

EXIT CRITERIA EVALUATION RULES:
- Evaluate CUMULATIVELY across the ENTIRE conversation, not just the latest message.
- Check each criterion against BOTH the existing profile AND the new message AND the conversation history.
- If the profile already has "role" filled from a previous turn, "role_shared" IS met (true).
- Short answers CAN satisfy criteria. "I'm a dev at a fintech" satisfies role AND company criteria.
- "yeah" or "ok" with no substance satisfies NOTHING new.

NEW INFORMATION RULE:
- Set "new_information" to true ONLY if this message adds something concrete that wasn't already in the profile.
- Repeating the same frustration counts as false. Adding a NEW detail about it counts as true.
- Filler responses ("yeah", "ok", "sure", "makes sense") are false.
- Emotional deepening (expressing MORE feeling about something already discussed) counts as true IF it reveals something new (e.g., "honestly it keeps me up at night" adds emotional depth even if the topic was known).

OWNERSHIP PHASE EXIT CRITERIA RULES:
- commitment_question_asked: TRUE if Sally asked a "do you feel like..." commitment question about the solution (not just any question). FALSE if Sally jumped straight to price.
- prospect_self_persuaded: TRUE if the PROSPECT (not Sally) articulated at least one specific reason why they feel the solution could work for them. Must be the prospect's own words and reasoning, not just "yeah" or "sure".
- price_stated: TRUE if the $10,000 price has been explicitly mentioned in the conversation.
- definitive_response: TRUE if prospect gave a clear response to the offer: yes to paid, yes to free, or a clear no. "Not sure" or "let me think" is NOT definitive.

OBJECTION DIFFUSION STATUS (OWNERSHIP only):
- Set to "not_applicable" unless there is an active objection being handled
- Set to "diffused" if Sally lowered the temperature and the prospect hasn't re-escalated
- Set to "isolated" if Sally asked "[objection] aside, do you still want this?" and prospect said yes
- Set to "resolved" if prospect agreed to move forward despite the objection
- Set to "repeated" if prospect raised the SAME objection again after Sally's diffusion

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
        # Fallback: return a safe default with empty checklist
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
            # Handle malformed: treat truthy as met
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
