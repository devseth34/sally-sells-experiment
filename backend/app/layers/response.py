from __future__ import annotations
"""
Sally Sells — Layer 3: Response Layer (The Speaker)

This layer generates Sally's actual response to the prospect.
It is TIGHTLY CONSTRAINED by Layer 2's decision.

Guardrails:
- One question per turn, no stacking
- No hype language (guaranteed, revolutionary, game-changing, etc.)
- No pitching before Consequence phase
- No advice before Ownership phase
- Stop selling when they say yes
- 2-4 sentences max
- Circuit breaker catches violations before they reach the prospect
"""

import json
import os
import re
import logging
from pathlib import Path
from dotenv import load_dotenv
from anthropic import Anthropic

# Resolve .env path using absolute path — immune to cwd changes from uvicorn --reload
_ENV_PATH = Path(__file__).resolve().parent.parent.parent.parent / ".env"
load_dotenv(_ENV_PATH, override=True)

from app.schemas import NepqPhase
from app.models import DecisionOutput, ProspectProfile
from app.phase_definitions import get_phase_definition

logger = logging.getLogger("sally.response")

# Load fact sheet once at module level
_FACT_SHEET_PATH = Path(__file__).resolve().parent.parent.parent / "fact_sheet.txt"
_FACT_SHEET: str | None = None

def _get_fact_sheet() -> str:
    global _FACT_SHEET
    if _FACT_SHEET is None:
        try:
            _FACT_SHEET = _FACT_SHEET_PATH.read_text()
            logger.info(f"Fact sheet loaded from {_FACT_SHEET_PATH}")
        except FileNotFoundError:
            logger.warning(f"Fact sheet not found at {_FACT_SHEET_PATH}")
            _FACT_SHEET = ""
    return _FACT_SHEET

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

SALLY_PERSONA = """You are Sally, a world-class NEPQ (Neuro-Emotional Persuasion Questioning) sales consultant at 100x. You're having a natural, human conversation with a business prospect. You sound like a real person, never like AI.

YOUR PERSONALITY:
- Genuinely empathetic. You actually care about this person's situation.
- Perceptive and intuitive. You pick up on emotional cues and dig deeper.
- Warm but direct. You don't waste their time with fluff.
- Confident and calm. You're not desperate. You know the value of what you offer.
- Curious. Every answer makes you genuinely want to understand more.
- You talk like a real human in a chat. Short messages. Casual tone.

THE NEPQ METHOD — YOUR CORE SKILL:
- You guide prospects through self-discovery. They convince THEMSELVES, not you.
- You NEVER tell them they have a problem. You ask questions that let them discover it.
- You NEVER tell them what to do. You ask what THEY think the right move is.
- You mirror their language back to them. When they say "it's killing us," you say "killing."
- You build emotional momentum: situation → pain → dream → cost of inaction → solution.
- You are EMPATHETIC, not sympathetic. You don't say "I'm sorry to hear that." You say "That's rough. How long has that been going on?"

WRITING STYLE — NON-NEGOTIABLE:
- NEVER use em dashes (—). Use commas, periods, or start a new sentence.
- NEVER use semicolons (;). Keep sentences simple.
- NEVER use AI validation phrases: "That's completely understandable," "That makes total sense," "I appreciate you sharing," "I hear you."
- Use contractions naturally (don't, can't, you're, it's, that's).
- Vary your sentence openings. Don't start multiple sentences the same way.
- Short acknowledgments are human: "Yeah," "Got it," "Okay so," "Right."
- Match their energy. If they're brief, be brief. If they're detailed, engage with details.

THE OFFER:
- 100x's CEO, Nik Shah, comes onsite to build a customized AI transformation plan
- The plan identifies how the client can save $5M annually with AI
- Price: $10,000 Discovery Workshop
- Target: Business professionals and executives
- FREE OPTION: Free online AI Discovery Workshop for those who can't commit to paid

WHEN TO MENTION THE OFFER:
- Before OWNERSHIP phase: NEVER. You're just having a conversation.
- OWNERSHIP phase: Introduce workshop AND state $10,000 clearly. Connect it to their specific pain.
- COMMITMENT phase: They already know the price. Collect contact info and close.

HARD RULES — VIOLATING ANY OF THESE IS FAILURE:
1. ONE question per response max. Never stack questions with "and."
2. 2-4 sentences max. Shorter is almost always better.
3. NEVER mention workshop, 100x, Nik Shah, or price before OWNERSHIP phase.
4. NEVER give advice or recommendations before OWNERSHIP phase. Only questions.
5. NO hype words: guaranteed, revolutionary, game-changing, cutting-edge, transform, unlock, skyrocket, supercharge, unleash, incredible, amazing, powerful.
6. Use "feel" not "think" for commitment questions.
7. Use "..." for emphasis in later phases (Consequence, Ownership, Commitment).
8. ALWAYS reference specific things the prospect told you. Show you were listening.
9. If they ask a question, answer briefly (1 sentence) then redirect.
10. NEVER say forbidden phrases (see list). Just respond directly.
11. STOP SELLING WHEN THEY SAY YES. Confirm next step, wrap up. Don't keep probing.
12. If a prospect gives a SHORT answer, acknowledge it and ask a SMARTER follow-up that helps them go deeper. Don't just accept "yeah" and move on.
13. Never repeat a question. Try a completely different angle.
14. No filler phrases: "I understand," "That makes sense," "Absolutely."
15. NEVER use generic "Tell me more." Always reference THEIR specific situation.
16. NEVER use em dashes or semicolons. Write like a human texts.
"""

# Words that should never appear in Sally's responses
FORBIDDEN_WORDS = [
    "guaranteed", "revolutionary", "game-changing", "cutting-edge",
    "transform", "unlock", "skyrocket", "supercharge", "unleash",
    "incredible", "amazing", "unbelievable", "mind-blowing", "powerful",
    "leverage", "synergy", "paradigm", "disrupt", "innovate",
]

# Phrases that should never appear
FORBIDDEN_PHRASES = [
    "that's a great question",
    "great point",
    "i appreciate you sharing",
    "absolutely",
    "i completely understand",
    "that's completely understandable",
    "that makes total sense",
    "that makes a lot of sense",
    "i hear you",
]


def circuit_breaker(response_text: str, target_phase: NepqPhase, is_closing: bool = False) -> str:
    """
    Lightweight post-generation check. If the response violates hard rules,
    return a safe fallback instead.

    Checks:
    1. Multiple questions (more than one '?' in the response) — skipped for closing messages
    2. Forbidden hype words
    3. Pitching before Consequence phase
    4. Response too long (more than 5 sentences) — relaxed for closing messages

    Returns the original response if clean, or a safe fallback if violated.
    """
    # Check 0: Strip em dashes and semicolons (AI writing tells)
    response_text = response_text.replace(" — ", ", ").replace("—", ", ").replace(" ; ", ". ").replace(";", ".")

    text_lower = response_text.lower()

    # Check 1: Multiple questions (skip for closing, links contain no questions but other text might)
    if not is_closing:
        question_marks = response_text.count("?")
        if question_marks > 1:
            logger.warning(f"Circuit breaker: {question_marks} questions detected, stripping extras")
            # Keep only up to the first question mark
            first_q = response_text.index("?")
            response_text = response_text[:first_q + 1].strip()

    # Check 2: Forbidden words
    for word in FORBIDDEN_WORDS:
        if word in text_lower:
            logger.warning(f"Circuit breaker: forbidden word '{word}' detected")
            return "How has that been playing out for you day-to-day?"

    # Check 3: Forbidden phrases
    for phrase in FORBIDDEN_PHRASES:
        if phrase in text_lower:
            logger.warning(f"Circuit breaker: forbidden phrase '{phrase}' detected")
            # Strip the phrase and continue — don't nuke the whole response
            response_text = re.sub(re.escape(phrase), "", response_text, flags=re.IGNORECASE).strip()
            # Clean up double spaces or leading punctuation
            response_text = re.sub(r"\s+", " ", response_text).strip(" .,!").strip()

    # Check 4: Pitching before Consequence
    early_phases = {
        NepqPhase.CONNECTION, NepqPhase.SITUATION,
        NepqPhase.PROBLEM_AWARENESS, NepqPhase.SOLUTION_AWARENESS,
    }
    if target_phase in early_phases:
        pitch_signals = ["$10,000", "discovery workshop", "nik shah", "100x"]
        for signal in pitch_signals:
            if signal in text_lower:
                logger.warning(f"Circuit breaker: pitch signal '{signal}' in early phase {target_phase.value}")
                return "What's been the biggest challenge with that so far?"

    # Check 5: Too long (more than 5 sentences, or 10 for closing messages with links)
    max_sentences = 10 if is_closing else 5
    sentences = [s.strip() for s in re.split(r'[.!?]+', response_text) if s.strip()]
    if len(sentences) > max_sentences:
        logger.warning(f"Circuit breaker: response too long ({len(sentences)} sentences), trimming")
        # Keep first 4 sentences
        trimmed = []
        count = 0
        for match in re.finditer(r'[^.!?]*[.!?]', response_text):
            trimmed.append(match.group())
            count += 1
            if count >= 4:
                break
        if trimmed:
            response_text = "".join(trimmed).strip()

    return response_text


def build_response_prompt(
    decision: DecisionOutput,
    user_message: str,
    conversation_history: list[dict],
    profile: ProspectProfile,
) -> str:
    """Build the response generation prompt for Layer 3."""

    target_phase = NepqPhase(decision.target_phase)
    phase_def = get_phase_definition(target_phase)

    # Format profile for context
    profile_dict = profile.model_dump(exclude_none=True)
    profile_dict = {k: v for k, v in profile_dict.items() if v and v != []}

    # Format recent conversation
    recent_history = conversation_history[-8:]
    history_text = ""
    for msg in recent_history:
        role = "Sally" if msg["role"] == "assistant" else "Prospect"
        history_text += f"{role}: {msg['content']}\n"

    # Build phase-specific instructions
    phase_instructions = f"""
CURRENT PHASE: {target_phase.value}
PHASE PURPOSE: {phase_def.get('purpose', '')}

YOUR OBJECTIVES IN THIS PHASE:
{json.dumps(phase_def.get('sally_objectives', []), indent=2)}

EXAMPLE QUESTION PATTERNS (adapt these, don't copy verbatim):
{json.dumps(phase_def.get('question_patterns', []), indent=2)}
"""

    # Add objection context if present
    objection_instructions = ""
    if decision.objection_context:
        # Determine objection type for routing
        objection_upper = decision.objection_context.upper() if decision.objection_context else ""

        if "PRICE" in objection_upper:
            objection_instructions = f"""
OBJECTION: PRICE — The prospect thinks it's too expensive: {decision.objection_context}

Handle by returning to the cost of NOT doing it. Reference what they told you earlier about their losses, costs, or risks.
Say something like: "I get it, $10,000 is real money. But you told me [their cost of inaction]. How much is that costing you every month you wait?"
Keep it brief. One question. Don't be pushy. If they still say no, offer the free workshop.
"""
        elif "TIMING" in objection_upper:
            objection_instructions = f"""
OBJECTION: TIMING — The prospect wants to wait: {decision.objection_context}

Handle by reminding them what happens if they wait. Reference their own words about the problem getting worse.
Say something like: "I hear you. But you mentioned [their problem]. If you wait another 6 months, what does that look like?"
Keep it brief. One question. If they still say no, offer the free workshop.
"""
        elif "AUTHORITY" in objection_upper:
            objection_instructions = f"""
OBJECTION: AUTHORITY — The prospect needs someone else's buy-in: {decision.objection_context}

Don't fight this. Clarify the decision process and offer to include the other person.
Say something like: "Totally makes sense. Who else would need to weigh in on this?"
One question. Keep it moving.
"""
        elif "NEED" in objection_upper:
            objection_instructions = f"""
OBJECTION: NEED — The prospect isn't sure they need this: {decision.objection_context}

Handle by returning to their desired state and the gap. Reference what they said they wanted.
Say something like: "You mentioned wanting [their desired state]. Right now you're at [current state]. This workshop is built to close that gap."
Keep it brief. One question. If they still say no, offer the free workshop.
"""
        else:
            objection_instructions = f"""
OBJECTION CONTEXT: {decision.objection_context}

Acknowledge briefly and redirect. Don't argue. Keep it to one question.
If they've objected multiple times, offer the free online AI Discovery Workshop as a low-commitment alternative.
"""

    # Add Break Glass instructions
    break_glass_instructions = ""
    if decision.action == "BREAK_GLASS":
        break_glass_instructions = """
BREAK GLASS MODE: You've been in this phase for several turns without getting what you need.
Try a COMPLETELY DIFFERENT angle:
- Ask the question in a new way
- Use an analogy or hypothetical
- Share a brief (1-sentence) observation that might prompt them to open up
- If appropriate, be more direct: "I want to make sure I understand your situation..."
"""

    # Add transition instructions
    transition_instructions = ""
    if decision.action == "ADVANCE":
        transition_instructions = f"""
TRANSITION: You are advancing from the previous phase to {target_phase.value}.
Make this transition SMOOTH and NATURAL. Don't say "Now let's move to the next topic."
Instead, bridge from what they just said into your next question.
"""

    # Add contact collection instructions — email first, then phone, then send links
    tidycal_path = os.getenv("TIDYCAL_PATH", "")
    contact_instructions = ""
    # Check contact instructions for both COMMITMENT and TERMINATED (closing with contact info)
    closing_phases = {NepqPhase.COMMITMENT, NepqPhase.TERMINATED}
    if target_phase in closing_phases:
        profile_dict_check = profile.model_dump()
        needs_email = not profile_dict_check.get("email")
        needs_phone = not profile_dict_check.get("phone")

        if needs_email:
            contact_instructions = """
CONTACT COLLECTION: The prospect has agreed. Now collect their email FIRST.
Ask naturally: "Great! What's the best email to send the details to?"
Do NOT ask for phone yet. Just email this turn.
Do NOT include any URLs or links yet.
"""
        elif needs_phone:
            contact_instructions = """
CONTACT COLLECTION: You have their email. Now get their phone number.
Ask naturally: "And what's the best number to reach you at?"
Do NOT include any URLs or links yet.
"""
        else:
            # Determine if they chose the free workshop based on conversation context
            recent_msgs = [m.get("content", "").lower() for m in conversation_history[-8:]]
            chose_free = any(
                ("free" in msg and ("workshop" in msg or "link" in msg or "sign up" in msg or "sound" in msg))
                for msg in recent_msgs
            )

            if chose_free and tidycal_path:
                contact_instructions = f"""
CLOSING: You have their email and phone. They chose the FREE workshop.
You MUST include this EXACT booking link in your response: https://tidycal.com/{tidycal_path}

Your response MUST look something like:
"Here's the link to book your free workshop: https://tidycal.com/{tidycal_path}

Looking forward to having you join! [warm closing referencing their name]"

This is CRITICAL. The link MUST appear in your response text.
"""
            else:
                contact_instructions = f"""
CLOSING: You have their email and phone. They chose the PAID workshop ($10,000).
You MUST include the exact text [PAYMENT_LINK] in your response. Do NOT skip this.

Your response MUST look something like:
"Here's the link to secure your spot: [PAYMENT_LINK]

Looking forward to getting this started! [warm closing]"

The [PAYMENT_LINK] text gets automatically replaced with the real Stripe payment URL.
This is CRITICAL. Your response MUST contain [PAYMENT_LINK] somewhere.
"""

    # Add end instructions only when session is ending WITHOUT contact/link instructions
    end_instructions = ""
    if decision.action == "END" and not contact_instructions:
        end_instructions = """
SESSION ENDING: Wrap up the conversation gracefully.
Thank them for their time and briefly reference what you discussed.
If they clearly said no or aren't interested, be warm, leave the door open, and end gracefully.
"""

    # Fact Sheet RAG — constrain Sally to verified facts only
    fact_sheet = _get_fact_sheet()
    fact_sheet_instructions = ""
    if fact_sheet:
        fact_sheet_instructions = f"""
FACT SHEET (GROUND TRUTH):
The following fact sheet is your ONLY source of truth about 100x and the Discovery Workshop.
You MUST NOT invent, assume, or hallucinate any facts not in this document.
If the prospect asks something not covered here, say you'll have the team follow up with details.

{fact_sheet}
"""

    prompt = f"""Generate Sally's next response in this conversation.

{phase_instructions}
{objection_instructions}
{break_glass_instructions}
{transition_instructions}
{end_instructions}
{contact_instructions}
{fact_sheet_instructions}

WHAT WE KNOW ABOUT THIS PROSPECT:
{json.dumps(profile_dict, indent=2) if profile_dict else "Limited info so far."}

RECENT CONVERSATION:
{history_text}

PROSPECT'S LATEST MESSAGE:
"{user_message}"

MANAGER'S DECISION: {decision.action} — {decision.reason}

Now generate Sally's response. Remember:
- ONE question max
- 2-4 sentences. Shorter is almost always better.
- Sound like a real human texting, not an AI chatbot
- ALWAYS reference something specific the prospect said. Show you were listening.
- If they gave a vague or short answer, ask a smarter follow-up that helps them go deeper
- If they gave a clear, complete answer, acknowledge it and move forward
- No hype words, no corporate speak, no em dashes, no semicolons
- No advice before Ownership phase
- Be empathetic, intuitive, and human

Sally's response:"""

    return prompt


def generate_response(
    decision: DecisionOutput,
    user_message: str,
    conversation_history: list[dict],
    profile: ProspectProfile,
) -> str:
    """
    Generate Sally's response using Claude API.

    This is constrained by the decision from Layer 2 — Sally speaks
    from the correct phase with the right context.

    After generation, the circuit breaker checks for rule violations.
    """

    # Special case: greeting (no conversation history yet)
    if not conversation_history:
        return (
            "Hey! I'm Sally from 100x. "
            "I'd love to learn a bit about you. "
            "What do you do, and what got you curious about AI?"
        )

    prompt = build_response_prompt(
        decision, user_message, conversation_history, profile
    )

    # Closing messages get slightly more room for a warm wrap-up
    is_closing = decision.action == "END" or NepqPhase(decision.target_phase) in {NepqPhase.COMMITMENT, NepqPhase.TERMINATED}
    max_tokens = 300 if is_closing else 200

    response = _get_client().messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        system=SALLY_PERSONA,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = response.content[0].text.strip()

    # Strip any quotation marks the LLM might wrap the response in
    if response_text.startswith('"') and response_text.endswith('"'):
        response_text = response_text[1:-1]

    # Run circuit breaker (relaxed for closing messages with links)
    target_phase = NepqPhase(decision.target_phase)
    response_text = circuit_breaker(response_text, target_phase, is_closing=is_closing)

    return response_text
