"""
Sally Sells — Phase Definitions & Exit Criteria

Each phase has:
- A description of its purpose
- Specific exit criteria that Layer 1 evaluates
- The confidence threshold required to advance
- Questions Sally should be asking in this phase
- What information she's trying to extract

PACING PRINCIPLE: Don't rush, don't drag. Each phase needs its job DONE
before moving on. But once you have what you need, advance immediately.
A great NEPQ conversation is 10-18 turns total.
"""

from app.schemas import NepqPhase

PHASE_DEFINITIONS = {
    NepqPhase.CONNECTION: {
        "purpose": "Build rapport and understand who they are. Get their role, company context, and why they're here. 2-3 turns is fine.",
        "exit_criteria": [
            "Prospect has shared their role or job title",
            "Prospect has shared what their company does or their industry",
            "Prospect has given a reason they're interested in AI (even vague is fine)",
        ],
        "confidence_threshold": 65,
        "sally_objectives": [
            "Learn the prospect's name, role, and company",
            "Understand what brought them to explore AI",
            "Build warm rapport but don't waste time on small talk",
            "If they give you role + company + reason in one message, that's enough to move on",
        ],
        "extraction_targets": ["name", "role", "company", "industry"],
        "max_retries": 3,
        "question_patterns": [
            "What do you do, and what got you curious about AI?",
            "Tell me a bit about your company. What space are you in?",
            "What sparked the interest in looking at AI right now?",
        ],
    },

    NepqPhase.SITUATION: {
        "purpose": "Map their current operations. Understand what they do day-to-day so you can ask smart problem questions. 2-3 turns.",
        "exit_criteria": [
            "Prospect has described their current workflow, process, or day-to-day work",
            "Prospect has mentioned something concrete: team size, tools, processes, or specific tasks",
            "Sally has enough operational detail to ask specific problem-awareness questions",
        ],
        "confidence_threshold": 65,
        "sally_objectives": [
            "Get a clear picture of their daily operations",
            "Understand team structure, tools, or processes they use",
            "Ask follow-ups that reference what they just told you",
            "Don't accept vague answers. Push gently for specifics: 'Walk me through what that looks like day to day'",
        ],
        "extraction_targets": ["current_state", "team_size", "tools_mentioned"],
        "max_retries": 3,
        "question_patterns": [
            "Walk me through what a typical week looks like for you in terms of [their area].",
            "How does your team currently handle [their process]?",
            "What tools or systems are you using for that right now?",
        ],
    },

    NepqPhase.PROBLEM_AWARENESS: {
        "purpose": "Surface a REAL pain point that the prospect states in their own words. This is the emotional core of NEPQ. Don't rush it. 2-3 turns.",
        "exit_criteria": [
            "Prospect has articulated at least one SPECIFIC pain point or frustration in their own words",
            "The pain is real and current, not hypothetical",
            "The pain was stated by the prospect, NOT suggested by Sally",
        ],
        "confidence_threshold": 65,
        "sally_objectives": [
            "Help the prospect discover and articulate their pain themselves",
            "Ask questions that connect to THEIR specific situation, not generic ones",
            "Use what you learned in Situation to ask targeted questions: 'You mentioned your team of 6 handles X manually. How has that been scaling?'",
            "Let them feel the frustration. Don't rush past it.",
            "Once they name a real, specific pain, you can move on. Don't over-dig.",
        ],
        "extraction_targets": ["pain_points", "frustrations"],
        "max_retries": 4,
        "question_patterns": [
            "You mentioned [specific thing from Situation]. What's the hardest part about that?",
            "When things go wrong with [their process], what does that look like?",
            "What's the most frustrating part of your day right now?",
        ],
    },

    NepqPhase.SOLUTION_AWARENESS: {
        "purpose": "Get them to paint a picture of their ideal future. Create the GAP between where they are and where they want to be. 2-3 turns.",
        "exit_criteria": [
            "Prospect has described what success or improvement would look like for them",
            "There is a clear contrast between their current pain and their desired state",
            "The prospect feels the gap between where they are and where they want to be",
        ],
        "confidence_threshold": 65,
        "sally_objectives": [
            "Get them to describe their ideal outcome in concrete terms",
            "Reference their pain point: 'You said [pain]. If that was fixed, what would your day look like?'",
            "Build the emotional gap: make them feel the distance between now and their ideal",
            "Even a simple desired state is enough if it clearly contrasts with their current pain",
        ],
        "extraction_targets": ["desired_state", "success_metrics"],
        "max_retries": 3,
        "question_patterns": [
            "You mentioned [their pain]. If you could wave a magic wand, what would that look like instead?",
            "If that was working perfectly, what would change for you day to day?",
            "What would success actually look like for your team on this?",
        ],
    },

    NepqPhase.CONSEQUENCE: {
        "purpose": "Make the cost of inaction REAL and PERSONAL. What happens if they don't fix this? This creates the urgency that makes the pitch land. 2-4 turns.",
        "exit_criteria": [
            "Prospect has acknowledged a tangible cost of NOT solving this (money, time, clients, career, stress)",
            "The cost feels personal and real to THEM, not hypothetical",
            "There is urgency: they understand that waiting has a price",
        ],
        "confidence_threshold": 70,
        "sally_objectives": [
            "Help them quantify (even roughly) what doing nothing costs them",
            "Connect it to something personal: revenue, clients, career growth, burnout, competitive risk",
            "Reference THEIR pain and desired state: 'You said you're losing X because of Y. If nothing changes in 6 months...'",
            "Don't force specific numbers. 'A lot' or 'it would be bad' counts if they feel it",
            "This is where urgency is built. Take your time here.",
        ],
        "extraction_targets": ["cost_of_inaction", "timeline_pressure", "competitive_risk"],
        "max_retries": 4,
        "question_patterns": [
            "If nothing changes in the next 6 months, what does that actually look like for you?",
            "You mentioned [their pain]. What's that costing you right now, even roughly?",
            "How does staying on this path affect you beyond just the business side?",
        ],
    },

    NepqPhase.OWNERSHIP: {
        "purpose": "Present the $10,000 Discovery Workshop. Handle objections with NEPQ techniques. If they still say no, offer the free workshop. Only advance when they say yes.",
        "exit_criteria": [
            "The $10,000 price has been clearly stated to the prospect",
            "Prospect has given a definitive response: yes to paid, yes to free, or hard no",
            "Any objections have been addressed at least once using NEPQ technique",
        ],
        "confidence_threshold": 65,
        "sally_objectives": [
            "Present the workshop naturally by connecting it to THEIR specific situation",
            "State the price clearly: 'It's a $10,000 investment'",
            "OBJECTION HANDLING (NEPQ style):",
            "  PRICE: 'I get it. But you told me [cost of inaction]. How much is that costing you each month you wait?'",
            "  TIMING: 'You mentioned [their problem]. What happens if you wait another 6 months?'",
            "  NEED: 'You said you wanted [desired state]. Right now you're dealing with [pain]. This is designed to close that exact gap.'",
            "  AUTHORITY: 'Makes sense. Who else would need to weigh in?'",
            "If they've objected twice and still say no: offer the free online AI Discovery Workshop",
            "Say: 'No worries at all. We also run a free online AI Discovery Workshop. Want me to send you the link?'",
            "Only advance to COMMITMENT when they give a clear yes (to paid OR free)",
        ],
        "extraction_targets": ["decision_authority", "decision_timeline", "budget_signals"],
        "max_retries": 6,
        "question_patterns": [
            "Based on everything you've shared... our CEO Nik Shah does a hands-on Discovery Workshop where he comes onsite and builds a customized AI plan for your team. It's a $10,000 investment. Does that feel like something worth exploring?",
            "Who else would need to be involved in a decision like this?",
            "No worries at all. We also run a free online AI Discovery Workshop. Want me to send you the link?",
        ],
    },

    NepqPhase.COMMITMENT: {
        "purpose": "Close. Collect email + phone. Send the appropriate link (payment or booking). Done.",
        "exit_criteria": [
            "Prospect has given a positive signal (yes, sure, sounds good, etc.)",
            "Email address has been collected",
            "Phone number has been collected",
            "Payment or booking link has been sent",
            "OR prospect has given a definitive no (end gracefully)",
        ],
        "confidence_threshold": 70,
        "sally_objectives": [
            "If YES to paid: collect email, then phone, then send [PAYMENT_LINK]",
            "If YES to free: collect email, then phone, then send the TidyCal booking link",
            "Once you have email + phone: send the link and close warmly",
            "If hard no: thank them, leave the door open, end gracefully",
        ],
        "extraction_targets": ["email", "phone"],
        "max_retries": 5,
        "question_patterns": [
            "Great! What's the best email to send the details to?",
            "And what's the best number to reach you at?",
            "Here's the link to secure your spot: [PAYMENT_LINK]",
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
