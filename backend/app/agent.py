from .schemas import NepqPhase

# NEPQ Phase Order (the strict sequence)
PHASE_ORDER = [
    NepqPhase.CONNECTION,
    NepqPhase.SITUATION,
    NepqPhase.PROBLEM_AWARENESS,
    NepqPhase.SOLUTION_AWARENESS,
    NepqPhase.CONSEQUENCE,
    NepqPhase.OWNERSHIP,
    NepqPhase.COMMITMENT,
]


class SallyEngine:
    """The NEPQ State Machine Engine."""

    @staticmethod
    def get_greeting() -> str:
        return (
            "Hi there! I'm Sally from 100x. Thanks for taking the time to chat today. "
            "I'd love to learn more about you and what brings you here. "
            "What's your role, and what got you interested in exploring AI solutions?"
        )

    @staticmethod
    def get_next_phase(current_phase: NepqPhase) -> NepqPhase:
        if current_phase == NepqPhase.COMMITMENT:
            return NepqPhase.TERMINATED
        if current_phase == NepqPhase.TERMINATED:
            return NepqPhase.TERMINATED
        try:
            current_index = PHASE_ORDER.index(current_phase)
            if current_index < len(PHASE_ORDER) - 1:
                return PHASE_ORDER[current_index + 1]
        except ValueError:
            pass
        return NepqPhase.TERMINATED

    @staticmethod
    def should_transition(current_phase: NepqPhase, message_count_in_phase: int) -> bool:
        return message_count_in_phase >= 2

    @staticmethod
    def generate_response(current_phase: NepqPhase, user_message: str) -> str:
        responses = {
            NepqPhase.CONNECTION: "That's great to hear! Tell me more about what your team is currently working on?",
            NepqPhase.SITUATION: "I see. How has that been working out for you? Any challenges?",
            NepqPhase.PROBLEM_AWARENESS: "That sounds frustrating. If you could fix this, what would it look like?",
            NepqPhase.SOLUTION_AWARENESS: "That's a compelling vision. What's the cost of NOT solving this?",
            NepqPhase.CONSEQUENCE: "Those are significant stakes. What's your timeline for making a decision?",
            NepqPhase.OWNERSHIP: "Based on everything, I think our $10,000 Discovery Workshop would be perfect. Ready to move forward?",
            NepqPhase.COMMITMENT: "Excellent! I'll send over the details. Thank you!",
            NepqPhase.TERMINATED: "Thank you for the conversation!",
        }
        return responses.get(current_phase, "Tell me more about that.")