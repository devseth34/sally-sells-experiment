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
_ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_ENV_PATH, override=True)

from app.schemas import NepqPhase
from app.models import DecisionOutput, ProspectProfile
from app.phase_definitions import get_phase_definition

logger = logging.getLogger("sally.response")

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

SALLY_PERSONA = """You are Sally, a senior sales consultant at 100x. You're having a natural conversation with a business prospect.

YOUR PERSONALITY:
- Warm, curious, and genuinely interested in the prospect's situation
- You listen more than you talk
- You ask thoughtful questions that make the prospect think
- You NEVER sound like a pushy salesperson
- You're confident but not aggressive
- You use a conversational, natural tone — not corporate speak

THE OFFER:
- 100x's CEO, Nik Shah, comes onsite to build a customized AI transformation plan
- The plan identifies how the client can save $5M annually with AI
- Price: $10,000 Discovery Workshop
- Target: C-suite executives in real estate and financial services

WHEN TO MENTION THE OFFER:
- Before OWNERSHIP phase: NEVER mention it. Just ask questions.
- In OWNERSHIP phase: Introduce the workshop AND state the price clearly. Say something like "It's a $10,000 investment" or "The workshop is $10,000." The prospect must hear the price BEFORE you ask for commitment.
- In COMMITMENT phase: They already know the price. Just ask for the yes/no.

HARD RULES — VIOLATING THESE IS AN AUTOMATIC FAILURE:
1. Ask ONE question per response. Never stack multiple questions. Never use "and" to join two questions.
2. Keep responses to 2-4 sentences. Shorter is better. No walls of text.
3. NEVER mention the $10,000 workshop, 100x, Nik Shah, or the offer before OWNERSHIP phase. Before that, you are just having a conversation.
4. NEVER give advice, suggestions, or recommendations before OWNERSHIP phase. You are asking questions, not consulting.
5. NEVER use hype words: "guaranteed," "revolutionary," "game-changing," "cutting-edge," "transform," "unlock," "skyrocket," "supercharge," "unleash," "incredible," "amazing," "unbelievable," "mind-blowing," "powerful." Use plain, honest language.
6. Use "feel" instead of "think" when asking commitment questions (e.g., "Do you feel like..." not "Do you think...").
7. In later phases (Consequence, Ownership, Commitment), use verbal pausing with "..." for emphasis.
8. Reference specific things the prospect told you earlier — show you were listening.
9. If the prospect asks you a direct question, answer it briefly (one sentence), then redirect with your own question.
10. Never say "That's a great question" or "Great point" — it sounds patronizing. Also never say "I appreciate you sharing that" — it sounds robotic.
11. CRITICAL — STOP SELLING WHEN THEY SAY YES. When a prospect agrees (even with conditions like "sure, if timing works"), confirm the next step and wrap up warmly. Do NOT keep probing or asking more questions. Overasking after a yes loses the deal.
12. If the conversation has been going for more than 8-10 exchanges, start wrapping up. Long conversations lose deals.
13. Never repeat a question you've already asked, even rephrased. Try a completely different angle or gracefully close.
14. No filler phrases: "I understand," "That makes sense," "Absolutely," "Of course." Just respond directly.
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
]


def circuit_breaker(response_text: str, target_phase: NepqPhase) -> str:
    """
    Lightweight post-generation check. If the response violates hard rules,
    return a safe fallback instead.

    Checks:
    1. Multiple questions (more than one '?' in the response)
    2. Forbidden hype words
    3. Pitching before Consequence phase
    4. Response too long (more than 5 sentences)

    Returns the original response if clean, or a safe fallback if violated.
    """
    text_lower = response_text.lower()

    # Check 1: Multiple questions
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
            return "Tell me more about how that's been affecting your day-to-day?"

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

    # Check 5: Too long (more than 5 sentences)
    sentences = [s.strip() for s in re.split(r'[.!?]+', response_text) if s.strip()]
    if len(sentences) > 5:
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
        objection_instructions = f"""
OBJECTION CONTEXT: The prospect just raised an objection: {decision.objection_context}

You need to:
1. Acknowledge their concern warmly (e.g., "That's completely understandable...")
2. Gently redirect back to the phase objective
3. Do NOT argue with the objection — work around it
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

    # Add end instructions
    end_instructions = ""
    if decision.action == "END":
        end_instructions = """
SESSION ENDING: Wrap up the conversation gracefully.
Thank them for their time, summarize what you discussed briefly, and leave the door open.
If they committed to the workshop, confirm next steps.
If not, be warm and say you're available if they want to revisit.
"""

    # Add contact collection instructions
    contact_instructions = ""
    if target_phase == NepqPhase.COMMITMENT:
        profile_dict_check = profile.model_dump()
        needs_email = not profile_dict_check.get("email")
        needs_phone = not profile_dict_check.get("phone")
        has_either = not needs_email or not needs_phone

        if needs_email and needs_phone and not has_either:
            contact_instructions = """
CONTACT COLLECTION: The prospect has agreed. Now collect their info naturally.
Ask: "That's great to hear! What's the best email to send the details over to?"
Do NOT ask for both email and phone in the same message.
"""
        elif needs_email:
            contact_instructions = """
CONTACT COLLECTION: You still need their email.
Ask naturally: "What's the best email to send the workshop details to?"
"""
        elif needs_phone:
            contact_instructions = """
CONTACT COLLECTION: You have their email. Now get their phone.
Ask naturally: "And what's the best number to reach you at for scheduling?"
"""
        elif not needs_email and not needs_phone:
            stripe_link = os.getenv("STRIPE_PAYMENT_LINK", "")
            calendly_link = os.getenv("CALENDLY_URL", "")
            contact_instructions = f"""
CLOSING: You have their email and phone. Confirm next steps, include booking and payment links, and end warmly.

You MUST include these two links in your response (copy them exactly):
- Booking link: {calendly_link}
- Payment link: {stripe_link}

Format your response like this:
"Perfect — I'll send the details to [email] and our team will reach out at [phone]. In the meantime, here are your next steps:

Book your Discovery Workshop: {calendly_link}
Complete payment: {stripe_link}

Really enjoyed our conversation today, [name]!"
"""

    prompt = f"""Generate Sally's next response in this conversation.

{phase_instructions}
{objection_instructions}
{break_glass_instructions}
{transition_instructions}
{end_instructions}
{contact_instructions}

WHAT WE KNOW ABOUT THIS PROSPECT:
{json.dumps(profile_dict, indent=2) if profile_dict else "Limited info so far."}

RECENT CONVERSATION:
{history_text}

PROSPECT'S LATEST MESSAGE:
"{user_message}"

MANAGER'S DECISION: {decision.action} — {decision.reason}

Now generate Sally's response. Remember:
- ONE question max
- 2-4 sentences, no more
- Natural, warm, conversational
- Reference their specific situation when possible
- No hype words, no corporate speak
- No advice or recommendations before Ownership phase

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
            "Hi there! I'm Sally from 100x. Thanks for taking the time to chat today. "
            "I'd love to learn more about you and what brings you here. "
            "What's your role, and what got you interested in exploring AI solutions?"
        )

    prompt = build_response_prompt(
        decision, user_message, conversation_history, profile
    )

    response = _get_client().messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=200,  # 2-4 sentences max
        system=SALLY_PERSONA,
        messages=[{"role": "user", "content": prompt}],
    )

    response_text = response.content[0].text.strip()

    # Strip any quotation marks the LLM might wrap the response in
    if response_text.startswith('"') and response_text.endswith('"'):
        response_text = response_text[1:-1]

    # Run circuit breaker
    target_phase = NepqPhase(decision.target_phase)
    response_text = circuit_breaker(response_text, target_phase)

    return response_text
