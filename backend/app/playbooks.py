"""
Sally Sells — Situation Playbooks

Named playbooks that Layer 2 selects based on detected micro-situations.
Layer 3 injects the playbook instructions into the prompt, overriding default
phase behavior for that turn.

Each playbook contains:
- instruction: Full text injected into Layer 3 prompt (with {template} vars)
- max_consecutive_uses: Prevent same playbook looping
- overrides_action: Whether to override Layer 2's action to STAY
- requires_profile_fields (optional): Profile fields needed for templating
"""

import json
from typing import Optional


PLAYBOOKS = {
    "confusion_recovery": {
        "instruction": """CONFUSION RECOVERY PROTOCOL:
The prospect is confused about what you're saying or asking. This is YOUR fault, not theirs.

DO:
1. Apologize briefly: "Sorry, let me be clearer."
2. State your value proposition in ONE simple sentence tied to their specific pain: "{pain_summary}"
3. Ask a simple yes/no question: "Is that something you'd want?"

DO NOT:
- Ask "what part are you losing me on?" (puts burden on them)
- Restart discovery questions (you already know their situation)
- Ask any open-ended questions
- Give a long explanation

Maximum 2 sentences + 1 yes/no question. Be direct and simple.

Example: "Sorry, let me be clearer. We help people like you fix {pain_summary} with a customized AI plan. Is that something you'd want to explore?" """,
        "max_consecutive_uses": 2,
        "overrides_action": True,
    },

    "bridge_with_their_words": {
        "instruction": """BRIDGE PROTOCOL — USE THEIR EXACT WORDS:
The prospect agreed the solution feels right but could not articulate why. That is OK.
Do NOT ask more open-ended questions. Instead, bridge using THEIR OWN words from earlier.

Their pain points: {pain_points}
Their frustrations: {frustrations}
Their cost of inaction: {cost_of_inaction}

Say something like: "Look, you told me {first_pain}. And you said {consequence}. This workshop is built to fix exactly that. Would you want to hear what it looks like?"

RULES:
- Use THEIR exact words, not your paraphrase
- Maximum 2-3 sentences
- End with a simple yes/no question
- Do NOT ask "what makes you feel..." or any open-ended question
- Do NOT probe further. State, connect, ask yes/no.
- This is your ONE bridge attempt. After their response, move to presenting the offer regardless.""",
        "max_consecutive_uses": 1,
        "overrides_action": True,
        "requires_profile_fields": ["pain_points"],
    },

    "resolve_and_close": {
        "instruction": """RESOLVE AND CLOSE:
The prospect confirmed they still want this despite the objection. Now close it.

Ask: "If we could figure out the {objection_type} piece, would you want to move forward?"

Specific framings:
- For PRICE: "If we could find a way to make the investment work, would you want to do it?"
- For TIMING: "If the timing could be flexible, would you want to get started?"
- For AUTHORITY: "If your decision maker was on board, is this something you'd want to do?"

If they say yes → move to collect contact info (COMMITMENT phase).
Do NOT restart discovery. Do NOT ask more exploratory questions.
One question. Wait for their answer.""",
        "max_consecutive_uses": 1,
        "overrides_action": False,
    },

    "graceful_alternative": {
        "instruction": """GRACEFUL ALTERNATIVE — FREE WORKSHOP OFFER:
The prospect raised the same objection again after you already tried to diffuse it. Do NOT re-diffuse.

Offer the free workshop as a POSITIVE option (not consolation):
"We also have a free online version of the workshop that covers the AI foundations. Might be a better starting point for you. Want me to send you the link?"

RULES:
- Frame it positively, not as "since you can't afford the paid one..."
- One offer, zero pressure
- If they say yes → advance to COMMITMENT to collect email
- If they say no → end gracefully. Thank them warmly. Leave the door open.""",
        "max_consecutive_uses": 1,
        "overrides_action": True,
    },

    "dont_oversell": {
        "instruction": """DON'T OVERSELL — PROSPECT IS READY:
The prospect just signaled they're ready to act. They said something like "I need to do something" or "what do I need to do" or "I can't keep going like this."

DO NOT ask more questions. They're already there.

Present the offer directly and clearly:
"So our CEO Nik Shah does a hands-on Discovery Workshop where he comes onsite and builds a customized AI plan with your team. It's a $10,000 investment."

Then STOP. Wait for their response. Do not push, do not probe, do not ask "does that sound good?"
They told you they're ready. Respect that by being direct.""",
        "max_consecutive_uses": 1,
        "overrides_action": True,
    },

    "graceful_exit": {
        "instruction": """GRACEFUL EXIT — RESPECT THE NO:
The prospect gave a clear, hard no. Respect it immediately. No pushback. No last-ditch effort.

1. Acknowledge warmly: "Totally fair. Thanks for the honest conversation, {prospect_name}."
2. Offer ONE resource with zero pressure: "If you ever want to explore AI strategy, we have a free online workshop. Happy to send the link if you're interested."
3. End the session warmly.

Do NOT:
- Try to re-sell or re-frame
- Ask "are you sure?" or "what would change your mind?"
- Express disappointment
- Use their pain against them""",
        "max_consecutive_uses": 1,
        "overrides_action": True,
    },

    "energy_shift": {
        "instruction": """ENERGY SHIFT — PROSPECT DISENGAGING:
The prospect has been giving thin, low-energy responses for multiple turns. The current approach isn't working.

1. Briefly acknowledge the dynamic: "I know I'm asking a lot of questions."
2. Share a genuine, brief observation about their situation (1 sentence max)
3. Ask ONE question that's easier or more personal to answer

Example: "I know I'm asking a lot of questions. From what you've described, it sounds like your team is carrying a lot. What's the one thing that would make your day noticeably easier?"

Reset the conversational dynamic. Don't keep drilling with the same type of questions.""",
        "max_consecutive_uses": 1,
        "overrides_action": False,
    },

    "specific_probe": {
        "instruction": """SPECIFIC PROBE — GO DEEPER ON LIVED EXPERIENCE:
The prospect gave a thin, surface-level response in a critical phase. Generic probes aren't working.

1. Pick the most vague or abstract word from their response
2. Ask about their LIVED EXPERIENCE, not hypotheticals
3. Use time-anchored questions: "When was the last time that happened?" or "What did that look like last week?"

WRONG: "How does that play out?" (too abstract)
WRONG: "Tell me more about that" (too generic)
RIGHT: "When was the last time that happened?"
RIGHT: "What did that look like on your last project?"
RIGHT: "Walk me through what happened the most recent time."

One specific question. No preamble.""",
        "max_consecutive_uses": 2,
        "overrides_action": False,
    },

    "ownership_ceiling": {
        "instruction": """OWNERSHIP HARD CEILING — TIME TO WRAP UP:
You have spent too many turns in OWNERSHIP. It is time to close this gracefully.

Offer the free workshop ONE TIME:
"Look, I think there's a lot of value here for you. We also run a free online AI Discovery Workshop that covers the core strategy. Want me to send you the link?"

If they say yes → advance to COMMITMENT (collect email).
If they say no → end gracefully: "No problem at all. It was great chatting with you. If anything changes, you know where to find us."

Do NOT:
- Ask more probing questions
- Restart discovery
- Re-explain the situation
- Make more than ONE offer

One offer, then close.""",
        "max_consecutive_uses": 1,
        "overrides_action": True,
    },
}


def get_playbook_instructions(playbook_name: str, profile) -> str:
    """
    Get formatted playbook instructions with profile data templated in.

    Args:
        playbook_name: Name of the playbook (key in PLAYBOOKS dict)
        profile: ProspectProfile instance for templating

    Returns:
        Formatted instruction string ready for Layer 3 prompt injection,
        or empty string if playbook not found.
    """
    playbook = PLAYBOOKS.get(playbook_name)
    if not playbook:
        return ""

    instruction = playbook["instruction"]

    # Build template variables from profile
    pain_points = profile.pain_points if profile.pain_points else ["their challenges"]
    frustrations = profile.frustrations if profile.frustrations else []
    cost_of_inaction = profile.cost_of_inaction or "what it's costing them"
    first_pain = pain_points[0] if pain_points else "their situation"
    pain_summary = first_pain
    consequence = cost_of_inaction if cost_of_inaction != "what it's costing them" else (
        frustrations[0] if frustrations else "the impact on their work"
    )
    prospect_name = profile.name or ""

    # Collect objection info
    objection_type = "price"
    if profile.objections_encountered:
        last_objection = profile.objections_encountered[-1]
        if "TIMING" in last_objection:
            objection_type = "timing"
        elif "AUTHORITY" in last_objection:
            objection_type = "authority"
        elif "NEED" in last_objection:
            objection_type = "need"

    # Template substitution
    try:
        instruction = instruction.format(
            pain_points=json.dumps(pain_points),
            frustrations=json.dumps(frustrations),
            cost_of_inaction=cost_of_inaction,
            first_pain=first_pain,
            pain_summary=pain_summary,
            consequence=consequence,
            prospect_name=prospect_name,
            objection_type=objection_type,
        )
    except (KeyError, IndexError):
        # If any template variable is missing, return raw instruction
        pass

    return f"""
SITUATION DETECTED: {playbook_name}
EXECUTE PLAYBOOK: {playbook_name}

{instruction}

These instructions OVERRIDE your default phase behavior for this turn only.
Follow them exactly."""
