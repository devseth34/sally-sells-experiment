"""
Sally Sells — Phase Definitions & Exit Criteria

Each phase has:
- A description of its purpose
- Specific exit criteria that Layer 1 evaluates
- The confidence threshold required to advance
- Questions Sally should be asking in this phase
- What information she's trying to extract
"""

from app.schemas import NepqPhase

PHASE_DEFINITIONS = {
    NepqPhase.CONNECTION: {
        "purpose": "Build rapport and establish context. Understand who the prospect is and why they're here.",
        "exit_criteria": [
            "Prospect has shared their role or title",
            "Prospect has given context about their company or industry",
            "Prospect has engaged conversationally (not just 'hi' or one-word answers)",
        ],
        "confidence_threshold": 65,
        "sally_objectives": [
            "Learn the prospect's name, role, and company",
            "Understand what brought them to explore AI solutions",
            "Create a warm, non-salesy first impression",
        ],
        "extraction_targets": ["name", "role", "company", "industry"],
        "max_retries": 4,
        "question_patterns": [
            "What's your role, and what got you interested in exploring AI solutions?",
            "Tell me a bit about your company — what space are you in?",
            "What prompted you to look into this now?",
        ],
    },

    NepqPhase.SITUATION: {
        "purpose": "Understand the prospect's current operational state. What are they doing today? Spend 2-3 turns here to get a solid picture.",
        "exit_criteria": [
            "Prospect has described their current workflow or process",
            "Prospect has mentioned specific tools, methods, or team structure",
            "Sally has a clear picture of the status quo",
        ],
        "confidence_threshold": 65,
        "sally_objectives": [
            "Map out how they currently handle the area AI could improve",
            "Understand team size, tools, and manual processes",
            "Get concrete details, not vague descriptions",
            "Ask context-aware follow-ups based on what they've shared (e.g. if they mention a team, ask about roles or how work is split)",
        ],
        "extraction_targets": ["current_state", "team_size", "tools_mentioned"],
        "max_retries": 3,
        "question_patterns": [
            "Walk me through how your team currently handles [their area]...",
            "What does a typical week look like for you in terms of [their process]?",
            "How many people are involved in that process right now?",
        ],
    },

    NepqPhase.PROBLEM_AWARENESS: {
        "purpose": "Surface dissatisfaction with the status quo. The prospect must acknowledge specific gaps or frustrations.",
        "exit_criteria": [
            "Prospect has articulated at least one specific pain point or frustration",
            "The pain point was stated by the prospect, not suggested by Sally",
            "Prospect acknowledges this is a real problem, not hypothetical",
        ],
        "confidence_threshold": 65,
        "sally_objectives": [
            "Help the prospect recognize what's not working",
            "Get them to say the problem in their own words",
            "Do NOT suggest problems — ask directed questions that reference their specific situation (e.g. 'You mentioned your team handles X manually — how has that been scaling?')",
            "Once they name ONE real pain point, that's enough — move on",
        ],
        "extraction_targets": ["pain_points", "frustrations"],
        "max_retries": 3,
        "question_patterns": [
            "How has that been working out? Any areas where it falls short?",
            "What's the most frustrating part of that process?",
            "If you could wave a magic wand and fix one thing about how that works today, what would it be?",
        ],
    },

    NepqPhase.SOLUTION_AWARENESS: {
        "purpose": "Explore what 'better' looks like. The prospect articulates their desired future state.",
        "exit_criteria": [
            "Prospect has described what success would look like",
            "Prospect has mentioned specific outcomes or metrics they'd want",
            "There is a clear contrast between current state and desired state",
        ],
        "confidence_threshold": 65,
        "sally_objectives": [
            "Get the prospect to paint a picture of their ideal outcome",
            "Help them articulate measurable success criteria",
            "Build the 'gap' between where they are and where they want to be",
            "Reference the pain points they mentioned earlier — connect the dots for them",
        ],
        "extraction_targets": ["desired_state", "success_metrics"],
        "max_retries": 3,
        "question_patterns": [
            "If this was working perfectly, what would that look like for you?",
            "What would need to be true for you to feel like this problem was solved?",
            "How would you measure success if you fixed this?",
        ],
    },

    NepqPhase.CONSEQUENCE: {
        "purpose": "Quantify the cost of inaction. The prospect must recognize the stakes of NOT solving this.",
        "exit_criteria": [
            "Prospect has acknowledged a quantifiable cost (money, time, or risk)",
            "Prospect recognizes the consequences of continuing as-is",
            "There is urgency — the prospect understands waiting has a price",
        ],
        "confidence_threshold": 80,
        "sally_objectives": [
            "Help them calculate what inaction costs ($/month, hours/week, competitive risk)",
            "Make the invisible cost visible",
            "Do NOT pitch yet — just help them see the stakes",
        ],
        "extraction_targets": ["cost_of_inaction", "timeline_pressure", "competitive_risk"],
        "max_retries": 5,
        "required_profile_fields": ["current_state", "desired_state"],
        "question_patterns": [
            "What's this costing you right now — in time, money, or missed opportunities?",
            "If nothing changes in the next 6-12 months, what does that look like?",
            "How does this compare to what your competitors are doing?",
        ],
    },

    NepqPhase.OWNERSHIP: {
        "purpose": "The prospect owns the decision. Present the $10,000 Discovery Workshop with clear pricing so there are no surprises.",
        "exit_criteria": [
            "Prospect has expressed personal intent to solve this (not just 'someone should')",
            "The $10,000 price has been clearly stated to the prospect",
            "Decision-making authority is clarified OR prospect indicates they have influence",
        ],
        "confidence_threshold": 70,
        "sally_objectives": [
            "Shift from 'this is a problem' to 'I need to solve this'",
            "Introduce the Discovery Workshop: Nik Shah comes onsite to build a customized AI plan",
            "State the price clearly: 'It's a $10,000 investment' — no hiding the cost",
            "Briefly confirm decision authority — one question max",
        ],
        "extraction_targets": ["decision_authority", "decision_timeline", "budget_signals"],
        "max_retries": 3,
        "question_patterns": [
            "Based on what you've told me... our CEO Nik Shah actually does a hands-on Discovery Workshop where he comes onsite and builds out a customized AI plan for your team. It's a $10,000 investment. Does that sound like something worth exploring?",
            "Who else would need to be involved in a decision like this?",
            "If you found the right solution, how quickly would you want to move?",
        ],
    },

    NepqPhase.COMMITMENT: {
        "purpose": "Close to next step. Present the $10,000 Discovery Workshop, secure commitment, and collect contact info (email + phone) before ending.",
        "exit_criteria": [
            "Prospect has given any positive signal: 'yes', 'sure', 'I'd be open to that', 'sounds good', 'not opposed', 'let's do it'",
            "Email address has been collected",
            "Phone number has been collected",
            "OR prospect has given a definitive no (end gracefully without collecting info)",
        ],
        "confidence_threshold": 70,
        "sally_objectives": [
            "Present the offer naturally: Nik Shah, CEO of 100x, comes onsite to build a customized AI plan",
            "Use the NEPQ commitment question: 'Do you feel like this could be the answer for you?'",
            "If they say YES: confirm, then collect email and phone — 'What's the best email to send the details to?'",
            "After email: 'And what's the best number to reach you at?'",
            "Once you have both: confirm next steps and close warmly",
            "If no: thank them, leave the door open, end gracefully",
        ],
        "extraction_targets": ["email", "phone"],
        "max_retries": 5,
        "question_patterns": [
            "Based on everything we've discussed... do you feel like our Discovery Workshop could be the answer for you?",
            "What's the best email to send the details over to?",
            "And what's the best number to reach you at for scheduling?",
            "I'll get that over to you right away. Thanks so much for your time today — looking forward to it.",
        ],
    },
}


def get_phase_definition(phase: NepqPhase) -> dict:
    """Get the full definition for a phase."""
    return PHASE_DEFINITIONS.get(phase, {})


def get_confidence_threshold(phase: NepqPhase) -> int:
    """Get the confidence threshold needed to advance past this phase."""
    defn = PHASE_DEFINITIONS.get(phase, {})
    return defn.get("confidence_threshold", 75)


def get_max_retries(phase: NepqPhase) -> int:
    """Get the maximum retries before Break Glass triggers."""
    defn = PHASE_DEFINITIONS.get(phase, {})
    return defn.get("max_retries", 4)


def get_required_profile_fields(phase: NepqPhase) -> list:
    """Get profile fields that MUST be filled before this phase can generate responses."""
    defn = PHASE_DEFINITIONS.get(phase, {})
    return defn.get("required_profile_fields", [])
