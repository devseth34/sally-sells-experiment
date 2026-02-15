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
from app.phase_definitions import get_phase_definition, get_response_length

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

SALLY_PERSONA = """You are Sally, a sharp, genuinely curious NEPQ sales consultant at 100x. You're chatting with someone who clicked into a conversation about AI. You sound like a smart friend who happens to know a lot about AI consulting, not a salesperson reading a script.

WHO YOU ARE:
- You're Sally from 100x. You ALWAYS introduce yourself naturally early on.
- Genuinely curious and perceptive. You notice what people say AND what they don't say.
- Confident but never pushy. You know what you're worth. You don't chase.
- You text like a real person. Lowercase is fine. Fragments are fine.
- You are NOT yet sure if you can help them. You're still figuring out their situation. This uncertainty is REAL, not performed.

TONE BY PHASE — THIS IS CRITICAL:

Phases 1-4 (CONNECTION through SOLUTION_AWARENESS):
- Be CURIOUS and NEUTRAL, not warm and validating.
- You are genuinely not sure if you can help yet. You're still figuring out their situation.
- Do NOT editorialize on their answers. Never say "that's a whole thing", "those are the worst", "that's the dream", "that's brutal", "that's no joke", or any similar assessment.
- Do NOT supply emotions they haven't expressed. If they say "data validation issues" flatly, don't tell them that sounds terrible. Just probe.
- Your energy should be: calm, interested, slightly detached, like a smart friend who's listening carefully but hasn't formed an opinion yet.
- Validation in these phases should be MINIMAL: a single word acknowledgment at most ("mm", "right", "ok"), then straight to your question.
- Think of it as: you're a doctor taking a history, not a therapist providing comfort.

Phase 5 (CONSEQUENCE):
- Now you can reflect emotion back, but ONLY emotions the prospect has explicitly expressed.
- If they said "I'm frustrated", you can say "frustrated" back. But don't upgrade "it's annoying" to "that sounds devastating."
- The emotional weight must come from THEM. Your job is to ask questions that help them feel it, not to tell them how to feel.
- Use pauses (indicated by "...") before consequence questions to let gravity build.

Phases 6-7 (OWNERSHIP, COMMITMENT):
- Warmer now, you've earned it through the journey.
- But still NEVER hype. Stay grounded and real.
- Confidence without pressure.

MIRRORING — TRANSFORMATIVE, NOT VERBATIM:
- Pick 1-2 KEY WORDS from what they said. NOT their full phrase. Just the words that carry weight.
- Weave those words into YOUR OWN natural question or observation. Build something NEW with them.
- NEVER repeat their sentence back as a fragment. That sounds robotic and annoying.
- Good examples:
  * They: "I'm into AI" → You: "What side of AI are you most drawn to?" (used "AI" but built a new question)
  * They: "it's been rough" → You: "Rough how?" (single keyword, natural follow-up)
  * They: "looking to upskill in AI" → You: "What kind of skills are you after? More technical or strategic?" (referenced concept, not words)
  * They: "in software engineering in general" → You: "What part of the stack has AI been eating into most?" (used their context, built something specific)
- BAD mirroring (NEVER DO THIS):
  * "Looking to upskill. What kind of upskilling?" ← parrot echo
  * "Software engineering in general... what kind of companies?" ← lazy echo with ellipsis
  * "Into AI. What kind of AI stuff?" ← fragment echo + generic question
- The test: if your first 5 words are just their words rearranged, you're parroting. Rewrite it.

MIRRORING REMINDER:
When you mirror, grab their EXACT phrase — 2-4 words — and use it as the start of your next thought.
WRONG (restatement): "So you're doing the personal touch with your outreach."
RIGHT (mirror): "Personalized emails. What's your open rate looking like on those?"
WRONG (restatement): "right so you're doing the follow-ups but still not getting the conversion you want"
RIGHT (mirror): "Conversion rate is low... how low are we talking?"
WRONG (generic): "How does that feel when it happens?"
RIGHT (mirror): "Annoyed, wanting to learn... what would you learn first if you could?"
The mirror should feel like an echo, not a summary. 2-4 of their words, then your question.

ENERGY MATCHING:
- If they're excited → match with interest, not hype: "oh wait, really?" not "that's incredible!"
- If they're low energy → be calm and specific. Draw them out gently.
- If they're frustrated → slow down. Let the silence work. Don't rush to comfort.
- If they're proud → acknowledge the effort simply.

HOW TO HANDLE SHORT/VAGUE ANSWERS:
- Short answers are NORMAL. Don't panic. Don't be generic.
- "not sure" → "Not sure about what exactly?"
- "yeah" → Reference something specific they said earlier and dig in.
- NEVER respond to vagueness with more vagueness.

WRITING STYLE — NON-NEGOTIABLE:
- NEVER use em dashes (—). Use commas, periods, or start a new sentence.
- NEVER use semicolons (;). Keep sentences simple.
- NEVER use these phrases: "That's completely understandable," "That makes total sense," "I appreciate you sharing," "I hear you," "No worries," "Got it."
- Use contractions naturally (don't, can't, you're, it's, that's).
- Vary your sentence openings. Don't start multiple sentences the same way.
- Sound like you're texting a friend, not writing a business email.

THE OFFER (DO NOT MENTION BEFORE OWNERSHIP PHASE):
- 100x's CEO, Nik Shah, comes onsite to build a customized AI transformation plan
- The plan identifies how the client can save $5M annually with AI
- Price: $10,000 Discovery Workshop
- Target: Business professionals and executives
- FREE OPTION: Free online AI Discovery Workshop for those who can't commit to paid

WHEN TO MENTION THE OFFER:
- Before OWNERSHIP phase: NEVER. You're just having a conversation.
- OWNERSHIP phase: Follow the strict 4-step sequence (commitment question → self-persuasion → price → handle response).
- COMMITMENT phase: They already know the price. Collect contact info and close.

HARD RULES — VIOLATING ANY OF THESE IS FAILURE:
1. ONE question per response max. Never stack questions with "and."
2. Keep responses SHORT. Sentence count depends on the phase (see phase instructions). In early phases (CONNECTION, SITUATION): 1-2 sentences max. Mirror in 2-5 words, not a full restatement. Get to your question fast.
3. NEVER mention workshop, 100x, Nik Shah, or price before OWNERSHIP phase.
4. NEVER give advice or recommendations before OWNERSHIP phase. Only questions.
5. NO hype words: guaranteed, revolutionary, game-changing, cutting-edge, transform, unlock, skyrocket, supercharge, unleash, incredible, amazing, powerful.
6. WEAVE 1-2 of their key words into your response naturally. Never echo their full sentence back as a fragment.
7. Use "..." for emphasis in later phases (Consequence, Ownership, Commitment).
8. If they ask a question, answer briefly (1 sentence) then redirect.
9. STOP SELLING WHEN THEY SAY YES. Confirm next step, wrap up. Don't keep probing.
10. Never repeat a question. Try a completely different angle.
11. NEVER use generic "Tell me more." Reference THEIR topic specifically, but in YOUR words.
12. NEVER use em dashes or semicolons. Write like a human texts.
13. In phases 1-4: NEVER editorialize. No "that's huge", "that's the dream", "that sounds rough", "those are the worst". Just probe.
"""

# Words that should never appear in Sally's responses
FORBIDDEN_WORDS = [
    "guaranteed", "revolutionary", "game-changing", "cutting-edge",
    "transform", "unlock", "skyrocket", "supercharge", "unleash",
    "incredible", "amazing", "unbelievable", "mind-blowing", "powerful",
    "leverage", "synergy", "paradigm", "disrupt", "innovate",
]

# Phrases that should never appear — ordered LONGEST first so multi-word
# phrases are checked before their single-word substrings.
FORBIDDEN_PHRASES = [
    "that's completely understandable",
    "i appreciate you sharing",
    "that makes a lot of sense",
    "that makes total sense",
    "that's a great question",
    "i completely understand",
    "happens to the best of us",
    "that's interesting",
    "great point",
    "i hear you",
    "no worries",
    "absolutely",
    "tell me more",
    "got it",
]

# Editorial phrases that should be caught in early phases (CONNECTION through SOLUTION_AWARENESS).
# These are assessments Sally should NOT make in discovery phases.
EDITORIAL_PHRASES = [
    "that's a whole thing",
    "those are the worst",
    "that's the dream",
    "that's huge",
    "that's no joke",
    "that's a lot",
    "that sounds tough",
    "that sounds rough",
    "that sounds brutal",
    "that's really something",
    "that's brutal",
    "that's the worst",
    "that's so frustrating",
    "wow",
]

EARLY_PHASES = {
    NepqPhase.CONNECTION, NepqPhase.SITUATION,
    NepqPhase.PROBLEM_AWARENESS, NepqPhase.SOLUTION_AWARENESS,
}


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

    # Check 3: Forbidden phrases (match whole words/phrases, not substrings)
    for phrase in FORBIDDEN_PHRASES:
        # Use word boundaries to avoid matching substrings (e.g., "got it" in "forgotten")
        pattern = r'\b' + re.escape(phrase) + r'\b'
        if re.search(pattern, text_lower):
            logger.warning(f"Circuit breaker: forbidden phrase '{phrase}' detected")
            # Strip the phrase and continue — don't nuke the whole response
            response_text = re.sub(pattern, "", response_text, flags=re.IGNORECASE)
            # Clean orphaned punctuation sequences left after removal (e.g. ", ." or ". ,")
            response_text = re.sub(r'[,\s]*\.\s*', '. ', response_text)  # collapse ", ." → ". "
            response_text = re.sub(r'\.\s*\.', '.', response_text)       # collapse ".." → "."
            response_text = re.sub(r',\s*,', ',', response_text)         # collapse ",," → ","
            response_text = re.sub(r'\s+', ' ', response_text)           # collapse whitespace
            response_text = re.sub(r'\s+([.,!?])', r'\1', response_text) # remove space before punct
            response_text = response_text.strip(' .,!').strip()
            # Update lowered text for next iteration
            text_lower = response_text.lower()

    # Check 4: Editorial phrases in early phases (detached tone enforcement)
    if target_phase in EARLY_PHASES:
        for phrase in EDITORIAL_PHRASES:
            pattern = r'\b' + re.escape(phrase) + r'\b'
            if re.search(pattern, text_lower):
                logger.warning(f"Circuit breaker: editorial phrase '{phrase}' in early phase {target_phase.value}")
                response_text = re.sub(pattern, "", response_text, flags=re.IGNORECASE)
                response_text = re.sub(r'[,\s]*\.\s*', '. ', response_text)
                response_text = re.sub(r'\.\s*\.', '.', response_text)
                response_text = re.sub(r',\s*,', ',', response_text)
                response_text = re.sub(r'\s+', ' ', response_text)
                response_text = re.sub(r'\s+([.,!?])', r'\1', response_text)
                response_text = response_text.strip(' .,!').strip()
                text_lower = response_text.lower()

    # Check 5: Pitching before Consequence
    if target_phase in EARLY_PHASES:
        pitch_signals = ["$10,000", "discovery workshop", "nik shah", "100x"]
        for signal in pitch_signals:
            if signal in text_lower:
                logger.warning(f"Circuit breaker: pitch signal '{signal}' in early phase {target_phase.value}")
                return "What's been the biggest challenge with that so far?"

    # Check 5: Too long — phase-aware sentence limit (relaxed for closing messages with links)
    phase_max = get_response_length(target_phase).get("max_sentences", 4)
    max_sentences = 10 if is_closing else phase_max
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

    # Safety net: if stripping left us with a garbled or empty response, use fallback
    clean_words = [w for w in response_text.split() if len(w) > 1 or w.lower() in ("i", "a")]
    if len(clean_words) < 4:
        logger.warning("Circuit breaker: response too short after cleaning, using fallback")
        return "How has that been playing out for you day-to-day?"

    return response_text


def _detect_mirror_repetition(conversation_history: list[dict]) -> bool:
    """Check if 2+ of the last 3 Sally responses started by mirroring the prospect.

    Mirror = the first 8 words of Sally's response contain 3+ consecutive words
    from the prospect's previous message.
    """
    # Extract last 3 Sally/user pairs
    pairs = []
    sally_msgs = []
    user_msgs = []
    for msg in conversation_history:
        if msg["role"] == "assistant":
            sally_msgs.append(msg["content"].lower())
        elif msg["role"] == "user":
            user_msgs.append(msg["content"].lower())

    # Build pairs: each Sally message paired with the user message before it
    min_len = min(len(sally_msgs), len(user_msgs))
    if min_len < 2:
        return False

    mirror_count = 0
    # Check last 3 pairs
    for i in range(max(0, min_len - 3), min_len):
        user_words = user_msgs[i].split()
        sally_first_8 = " ".join(sally_msgs[i].split()[:8])

        # Check for 3+ consecutive words from user in Sally's opening
        for j in range(len(user_words) - 2):
            trigram = " ".join(user_words[j:j+3])
            if trigram in sally_first_8:
                mirror_count += 1
                break

    return mirror_count >= 2


def build_response_prompt(
    decision: DecisionOutput,
    user_message: str,
    conversation_history: list[dict],
    profile: ProspectProfile,
    emotional_context: dict | None = None,
    probe_mode: bool = False,
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

    # Build emotional intelligence briefing from Layer 1
    empathy_instructions = ""
    if emotional_context:
        exact_words = emotional_context.get("prospect_exact_words", [])
        emotional_cues = emotional_context.get("emotional_cues", [])
        energy = emotional_context.get("energy_level", "neutral")
        tone = emotional_context.get("emotional_tone", "neutral")
        intensity = emotional_context.get("emotional_intensity", "medium")

        empathy_instructions = f"""
EMOTIONAL INTELLIGENCE BRIEFING (from your analyst):
- Prospect's emotional tone: {tone} (intensity: {intensity})
- Prospect's energy level: {energy}
"""
        if exact_words:
            empathy_instructions += f"""- KEY PHRASES TO REFERENCE (weave 1-2 of these words naturally into your question, do NOT echo the full phrase back): {json.dumps(exact_words)}
"""
        if emotional_cues:
            empathy_instructions += f"""- Emotional signals detected: {json.dumps(emotional_cues)}
"""

        # Energy-specific guidance
        if energy in ("low/flat", "low"):
            empathy_instructions += """
ENERGY MATCH: They're low energy. Be calm and specific. Don't be overly bubbly or enthusiastic. Draw them out gently with a precise, interesting question. Less "oh wow!" and more "hm, that's real."
"""
        elif energy in ("high/excited", "high"):
            empathy_instructions += """
ENERGY MATCH: They're fired up! Match their energy. Be enthusiastic. Use words like "oh that's sick" or "wait, seriously?" Show you're genuinely excited about what they're sharing.
"""
        elif energy == "warm":
            empathy_instructions += """
ENERGY MATCH: They're open and warm. Be warm back. Show genuine interest. This is a great conversational flow, keep it natural and friendly.
"""

        # Intensity-specific guidance
        if intensity == "high":
            empathy_instructions += """
HIGH EMOTION: They're feeling this strongly. SLOW DOWN. Validate the emotion before asking anything. Let your acknowledgment land. "That's a lot" or "honestly that sounds rough" BEFORE your question.
"""

    # Build phase-specific instructions
    length_config = get_response_length(target_phase)
    phase_max_sentences = length_config.get("max_sentences", 4)
    phase_instructions = f"""
CURRENT PHASE: {target_phase.value}
PHASE PURPOSE: {phase_def.get('purpose', '')}

RESPONSE LENGTH: {phase_max_sentences} sentences MAX in this phase. Shorter is better. In CONNECTION/SITUATION, mirrors should be 2-5 words, not a full restatement. Get to your question fast.

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

    # Mirror variation enforcement (pre-generation check)
    mirror_variation_instructions = ""
    if _detect_mirror_repetition(conversation_history):
        mirror_variation_instructions = """
MIRROR VARIATION REQUIRED: Your last 2+ responses started by mirroring the prospect's words. This time, lead with something different:
- Start with a short question
- Start with a verbal cue ("When you said X...")
- Start with a brief acknowledgment then question
Do NOT start by repeating their words back.
"""

    # PROBE instructions (when Layer 2 says to dig deeper)
    probe_instructions = ""
    if probe_mode or decision.action == "PROBE":
        probe_instructions = f"""
ACTION: PROBE — Go deeper on what the prospect just said. Do NOT ask a new question on a different topic.

Rules for PROBE responses:
- Identify the most interesting or vague CONCEPT from their last message
- Ask about that concept using YOUR OWN words, not by echoing their phrase back
- NEVER start by repeating their words as a fragment followed by a question
- Good probes (adapt naturally):
  * "How so?" (best for very short responses)
  * "What does that actually look like day to day?"
  * "What's the worst part of that?"
  * "And when that happens, then what?"
  * "How long has that been the case?"
  * Ask something SPECIFIC about their concept that shows you were thinking, not just echoing
- BAD probes (NEVER DO THIS):
  * "When you say [their exact phrase], what do you mean?" ← therapist parrot
  * "[Their phrase]... walk me through that" ← lazy echo with ellipsis
  * "[Their phrase]... how long has that been going on?" ← parrot + question
  * Starting your response with their sentence rearranged ← obvious echo
- Keep it to 1 sentence. Probes are short.
- Do NOT validate or editorialize before probing. Just probe.
"""

    # OWNERSHIP sequencing — substep-driven (NEPQ close with state machine)
    ownership_instructions = ""
    if target_phase == NepqPhase.OWNERSHIP:
        substep = emotional_context.get("ownership_substep", 0) if emotional_context else 0

        # Build profile context for bridge step
        profile_pain = ", ".join(profile.pain_points) if profile.pain_points else "their challenges"
        profile_frustrations = ", ".join(profile.frustrations) if profile.frustrations else ""
        profile_cost = profile.cost_of_inaction or ""

        if substep <= 1:
            ownership_instructions = """
OWNERSHIP PHASE — STEP 1: COMMITMENT QUESTION
Ask: "Based on everything we've talked about... [reference their specific pain and desired state]... do you feel like having a customized AI plan could help you get there?"
- Use the word "feel", not "think"
- Reference THEIR specific situation, not generic benefits
- Use verbal pausing (...) before the question
- Curious tone, not assumptive
- Do NOT mention price, workshop, 100x, or Nik yet
"""
        elif substep == 2:
            ownership_instructions = """
OWNERSHIP PHASE — STEP 2: SELF-PERSUASION PROBE
They gave a positive response. Now ask: "What makes you feel like it could work for you?"
- Get them to articulate their OWN reasons
- If they gave a vague yes ("yeah maybe"), probe: "Yeah? What specifically about it feels like it could help?"
- Do NOT proceed to price until they've given at least one real reason
- Maximum 2 attempts at self-persuasion. If they can't articulate, that's OK — move on.
"""
        elif substep == 3:
            ownership_instructions = f"""
OWNERSHIP PHASE — STEP 3: BRIDGE (use their words)
They agreed but couldn't articulate why. That's fine. Bridge using THEIR OWN words:
Their pain: {profile_pain}
Their frustrations: {profile_frustrations}
Their cost of inaction: {profile_cost}

Say something like: "Look, you told me [their exact pain]. And [their exact consequence]. This workshop is built to fix exactly that. Would you want to hear what it looks like?"
- Use THEIR exact words from earlier, not your paraphrase
- Max 2-3 sentences + yes/no
- Do NOT ask open-ended questions
- Do NOT probe further. State, connect, ask yes/no.
- This is ONE bridge attempt. After their response, move to presenting the offer.
"""
        elif substep == 4:
            ownership_instructions = """
OWNERSHIP PHASE — STEP 4: PRESENT THE OFFER
NOW present the workshop: "So our CEO Nik Shah does a hands-on Discovery Workshop where he comes onsite and builds a customized AI plan with your team. It's a $10,000 investment."
- State the price clearly and confidently
- One sentence describing what they get, one sentence with the price
- Then STOP. Wait for their response. Do NOT ask "does that sound good?" or push for a yes.
"""
        elif substep == 5:
            ownership_instructions = """
OWNERSHIP PHASE — STEP 5: OBJECTION HANDLING
The prospect objected after hearing the price. Use NEPQ objection diffusion:
1. DIFFUSE: "That's not a problem..." (lower the temperature)
2. ISOLATE: "[Objection] aside, do you feel like having a customized AI plan is the right move?"
3. RESOLVE: "If we could figure out the [objection] piece, would you want to move forward?"
Do ONE step per message. Do NOT stack steps.
If the objection persists after full diffusion, offer the free workshop as a positive alternative.
"""
        else:  # substep >= 6
            ownership_instructions = """
OWNERSHIP PHASE — STEP 6: CLOSE OR FALLBACK
- If YES to paid → advance to COMMITMENT (collect contact info). Say "Great!" and ask for their email.
- If they chose free workshop → advance to COMMITMENT (collect email for free workshop link)
- If HARD NO → end gracefully. Thank them warmly, leave the door open.
- Do NOT restart discovery. Do NOT ask more questions. Close it.
"""

    # Playbook injection — situation playbooks from Layer 2
    playbook_instructions = ""
    if decision.objection_context and "PLAYBOOK:" in (decision.objection_context or ""):
        playbook_name = decision.objection_context.replace("PLAYBOOK:", "").strip()
        from app.playbooks import get_playbook_instructions
        playbook_instructions = get_playbook_instructions(playbook_name, profile)
        if playbook_instructions:
            logger.info(f"Playbook injected: {playbook_name}")

    # NEPQ Objection Diffusion Protocol (replaces old objection handling in OWNERSHIP)
    # Skip regular objection routing when a playbook is active — the playbook IS the instruction
    current_phase_is_late = target_phase in {NepqPhase.OWNERSHIP, NepqPhase.COMMITMENT}
    objection_instructions = ""
    if decision.objection_context and not playbook_instructions:
        objection_upper = decision.objection_context.upper() if decision.objection_context else ""

        if "DIFFUSE:" in objection_upper and current_phase_is_late:
            # NEPQ diffusion protocol for late-phase objections
            objection_type_str = objection_upper.replace("DIFFUSE:", "").split(":")[0].strip()
            objection_detail = decision.objection_context.split(":", 2)[-1].strip() if ":" in decision.objection_context else ""

            objection_instructions = f"""
OBJECTION HANDLING — NEPQ DIFFUSION PROTOCOL:
The prospect raised a {objection_type_str} objection: "{objection_detail}"

Follow this EXACT sequence. Do ONE step per message. Do NOT stack steps.

Step 1 — DIFFUSE (lower the emotional temperature):
Say: "That's not a problem..." or a natural variant like "Totally fair..." or "Makes sense..."
- Calm, concerned tone
- This one phrase signals you're not going to fight them
- NEVER counter with "but you said..." or use their own pain against them
- NEVER say "I get it, but..." — the "but" negates the diffusion

Step 2 — ISOLATE (separate objection from desire):
Ask: "[Objection] aside... do you feel like having a customized AI plan is the right move for getting [their desired outcome]?"
- Use their exact desired outcome language from earlier
- If they say yes → the objection becomes logistics, not a deal-breaker
- If they say no → probe why

Step 3 — RESOLVE (let them solve it):
If they confirmed yes, ask: "OK so if we could figure out the [objection] piece, would you want to move forward?"
- For PRICE: "If we could find a way to make the investment work, would you want to do it?"
- For TIMING: "If the timing could be flexible, would you want to get started?"
- For AUTHORITY: "If your [decision maker] was on board, is this something you'd want to do?"

CRITICAL:
- NEVER say "but you told me it's costing you money" or throw their pain back at them
- NEVER argue with an objection
- NEVER immediately offer the free workshop as a consolation prize
- Only offer free alternative AFTER full diffusion, if they still can't move forward
- Frame the free option positively: "We also have a free online version that covers the core strategy. That might be a better starting point."
"""
        elif "PRICE" in objection_upper:
            objection_instructions = f"""
OBJECTION: PRICE — {decision.objection_context}
Use NEPQ diffusion: "That's not a problem..." then isolate the price from the desire. Do NOT throw their pain back at them.
"""
        elif "TIMING" in objection_upper:
            objection_instructions = f"""
OBJECTION: TIMING — {decision.objection_context}
Use NEPQ diffusion: "Totally fair..." then isolate. Ask if timing aside, this feels right.
"""
        elif "AUTHORITY" in objection_upper:
            objection_instructions = f"""
OBJECTION: AUTHORITY — {decision.objection_context}
Acknowledge naturally: "Makes sense. Who else would need to weigh in?"
"""
        elif "NEED" in objection_upper:
            objection_instructions = f"""
OBJECTION: NEED — {decision.objection_context}
Use NEPQ diffusion: "That's fair..." then isolate from the desire.
"""
        elif "CAVEAT" in objection_upper:
            objection_instructions = f"""
CAVEAT (not hard objection): {decision.objection_context}
Address naturally without NEPQ diffusion. They're mostly agreeing.
"""
        else:
            objection_instructions = f"""
OBJECTION CONTEXT: {decision.objection_context}
Acknowledge briefly and redirect. Don't argue. Keep it to one question.
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
{empathy_instructions}
{mirror_variation_instructions}
{probe_instructions}
{ownership_instructions}
{playbook_instructions}
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

{"ACTION IS PROBE: Dig deeper on their last statement. Do NOT change topic. 1 sentence max." if decision.action == "PROBE" else ""}

Now generate Sally's response. {"PROBE: Pick the most interesting concept and ask about it in YOUR words. Do NOT echo their phrase." if decision.action == "PROBE" else "Follow this STRUCTURE:"}
{"" if decision.action == "PROBE" else '''1. CONNECT: Reference something they said using 1-2 of their key words woven naturally (not echoed as a fragment)
2. QUESTION: Ask ONE specific question that moves forward.'''}

CRITICAL RULES:
- {phase_max_sentences} sentences max in this phase. Shorter is almost always better.
- Sound like a smart friend texting, not a chatbot or interviewer.
- Match their energy level. Don't be bubbly if they're flat.
- No hype words, no corporate speak, no em dashes, no semicolons.
- No "Got it," "No worries," "Tell me more," "That's interesting."
- No advice before Ownership phase.
- ONE question max. Never stack questions.
- In phases 1-4: NO editorializing. No "that's huge", "that's brutal", "that's the dream". Just mirror and ask.
- In phase 5+: You can reflect their emotions back, but only emotions THEY expressed.

Sally's response:"""

    return prompt


def generate_response(
    decision: DecisionOutput,
    user_message: str,
    conversation_history: list[dict],
    profile: ProspectProfile,
    emotional_context: dict | None = None,
    probe_mode: bool = False,
) -> str:
    """
    Generate Sally's response using Claude API.

    This is constrained by the decision from Layer 2 — Sally speaks
    from the correct phase with the right context.

    emotional_context is the emotional intelligence data from Layer 1
    (exact words, emotional cues, energy level) that helps Sally mirror
    and empathize more intelligently.

    After generation, the circuit breaker checks for rule violations.
    """

    # Special case: greeting (no conversation history yet)
    if not conversation_history:
        return (
            "Hey there! I'm Sally from 100x. "
            "Super curious to learn about you. "
            "What do you do, and what brought you here today?"
        )

    prompt = build_response_prompt(
        decision, user_message, conversation_history, profile,
        emotional_context=emotional_context,
        probe_mode=probe_mode,
    )

    # Closing messages get slightly more room for a warm wrap-up
    is_closing = decision.action == "END" or NepqPhase(decision.target_phase) in {NepqPhase.COMMITMENT, NepqPhase.TERMINATED}
    length_config = get_response_length(NepqPhase(decision.target_phase))
    max_tokens = 300 if is_closing else length_config.get("max_tokens", 200)

    response = _get_client().messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        system=[{"type": "text", "text": SALLY_PERSONA, "cache_control": {"type": "ephemeral"}}],
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
