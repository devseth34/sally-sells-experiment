from __future__ import annotations
"""
Sally Sells — Layer 2: Decision Layer (The Manager)

This layer is PURE DETERMINISTIC CODE. No LLM calls.
It takes the structured output from Layer 1 and makes decisions:
- Should we advance to the next phase?
- Should we stay and probe deeper?
- Should we reroute due to an objection?
- Should we trigger Break Glass (escape hatch)?
"""

from app.schemas import NepqPhase
from app.models import (
    ComprehensionOutput,
    DecisionOutput,
    ObjectionType,
    UserIntent,
    ProspectProfile,
)
from app.phase_definitions import (
    get_confidence_threshold,
    get_max_retries,
    get_required_profile_fields,
)

# NEPQ Phase Order (strict sequence)
PHASE_ORDER = [
    NepqPhase.CONNECTION,
    NepqPhase.SITUATION,
    NepqPhase.PROBLEM_AWARENESS,
    NepqPhase.SOLUTION_AWARENESS,
    NepqPhase.CONSEQUENCE,
    NepqPhase.OWNERSHIP,
    NepqPhase.COMMITMENT,
]

# Objection -> Phase routing map (used for early phases only)
OBJECTION_ROUTING = {
    ObjectionType.PRICE: NepqPhase.CONSEQUENCE,
    ObjectionType.TIMING: NepqPhase.PROBLEM_AWARENESS,
    ObjectionType.NEED: NepqPhase.SOLUTION_AWARENESS,
    # AUTHORITY stays in current phase (handled differently)
}

# Late phases where objections are handled IN-PHASE (never reroute backward)
# In OWNERSHIP: Sally handles objections directly using the objection routing patterns
# PRICE -> "Remember what you said about the cost of NOT doing this?"
# TIMING -> "What happens if you wait? You told me..."
# NEED -> "You mentioned wanting X. This is how we get there."
# AUTHORITY -> "Who else needs to be involved?"
LATE_PHASES = {NepqPhase.OWNERSHIP, NepqPhase.COMMITMENT}


def get_next_phase(current_phase: NepqPhase) -> NepqPhase:
    """Get the next phase in the NEPQ sequence."""
    try:
        idx = PHASE_ORDER.index(current_phase)
        if idx < len(PHASE_ORDER) - 1:
            return PHASE_ORDER[idx + 1]
    except ValueError:
        pass
    return NepqPhase.TERMINATED


def check_gap_builder_constraint(
    current_phase: NepqPhase,
    profile: ProspectProfile,
) -> tuple[bool, str]:
    """
    Gap Builder: Ensure required profile fields are filled before
    allowing certain phases to proceed.
    """
    required_fields = get_required_profile_fields(current_phase)
    if not required_fields:
        return True, ""

    missing = []
    profile_dict = profile.model_dump()
    for field in required_fields:
        value = profile_dict.get(field)
        if value is None or value == "" or value == []:
            missing.append(field)

    if missing:
        return False, f"Cannot proceed in {current_phase.value}: missing {', '.join(missing)}"

    return True, ""


def make_decision(
    current_phase: NepqPhase,
    comprehension: ComprehensionOutput,
    profile: ProspectProfile,
    retry_count: int,
    conversation_turn: int,
    conversation_start_time: float,
) -> DecisionOutput:
    """
    The core decision function. Pure logic, no LLM.

    Decision priority:
    1. Check for session end conditions (time limit, explicit goodbye)
    2. Check for objections -> reroute if needed (but NOT in late phases)
    3. Check exit criteria -> advance if met
    4. Check retry count -> Break Glass if exceeded
    5. Default: stay in current phase
    """
    import time

    # 1. Session time limit (30 minutes)
    elapsed_seconds = time.time() - conversation_start_time
    if elapsed_seconds > 1800:
        return DecisionOutput(
            action="END",
            target_phase=current_phase.value,
            reason=f"Session exceeded 30-minute limit ({elapsed_seconds:.0f}s elapsed)",
            retry_count=retry_count,
        )

    # 2. Already terminated
    if current_phase == NepqPhase.TERMINATED:
        return DecisionOutput(
            action="END",
            target_phase=NepqPhase.TERMINATED.value,
            reason="Session already terminated",
            retry_count=retry_count,
        )

    # 3. Objection routing
    if comprehension.objection_type != ObjectionType.NONE:
        objection = comprehension.objection_type

        # Agreements with caveats are NOT hard objections
        user_is_agreeing = comprehension.user_intent in (
            UserIntent.AGREEMENT,
            UserIntent.DIRECT_ANSWER,
        )

        if user_is_agreeing:
            return DecisionOutput(
                action="STAY",
                target_phase=current_phase.value,
                reason=f"User is agreeing with a caveat ({objection.value}: '{comprehension.objection_detail}'). Staying to address it naturally.",
                objection_context=f"CAVEAT (not hard objection): {comprehension.objection_detail}",
                retry_count=retry_count,
            )

        # In late phases, NEVER reroute backward
        if current_phase in LATE_PHASES:
            return DecisionOutput(
                action="STAY",
                target_phase=current_phase.value,
                reason=f"{objection.value} objection in {current_phase.value}. Handling in-phase (too late to reroute).",
                objection_context=f"{objection.value}: {comprehension.objection_detail}",
                retry_count=retry_count,
            )

        if objection == ObjectionType.AUTHORITY:
            return DecisionOutput(
                action="STAY",
                target_phase=current_phase.value,
                reason=f"Authority objection detected: '{comprehension.objection_detail}'. Staying to clarify decision process.",
                objection_context=f"AUTHORITY: {comprehension.objection_detail}",
                retry_count=retry_count,
            )

        target_phase = OBJECTION_ROUTING.get(objection)
        if target_phase:
            try:
                current_idx = PHASE_ORDER.index(current_phase)
                target_idx = PHASE_ORDER.index(target_phase)
                if current_idx > target_idx:
                    return DecisionOutput(
                        action="REROUTE",
                        target_phase=target_phase.value,
                        reason=f"{objection.value} objection detected: '{comprehension.objection_detail}'. Routing back to {target_phase.value}.",
                        objection_context=f"{objection.value}: {comprehension.objection_detail}",
                        retry_count=0,
                    )
            except ValueError:
                pass

    # 4. Gap Builder constraint check
    gap_ok, gap_reason = check_gap_builder_constraint(current_phase, profile)
    if not gap_ok:
        return DecisionOutput(
            action="STAY",
            target_phase=current_phase.value,
            reason=f"Gap Builder constraint: {gap_reason}",
            retry_count=retry_count,
        )

    # 5. Exit criteria evaluation
    confidence = comprehension.exit_evaluation.confidence
    threshold = get_confidence_threshold(current_phase)

    if confidence >= threshold:
        next_phase = get_next_phase(current_phase)
        if next_phase == NepqPhase.TERMINATED:
            # Before ending: check if we collected contact info
            has_positive_signal = comprehension.user_intent in (
                UserIntent.AGREEMENT, UserIntent.DIRECT_ANSWER
            )
            missing_contact = []
            if not profile.email:
                missing_contact.append("email")
            if not profile.phone:
                missing_contact.append("phone")

            if missing_contact and has_positive_signal:
                return DecisionOutput(
                    action="STAY",
                    target_phase=current_phase.value,
                    reason=f"Prospect committed but still need: {', '.join(missing_contact)}. Collecting contact info before closing.",
                    retry_count=retry_count,
                )

            return DecisionOutput(
                action="END",
                target_phase=NepqPhase.TERMINATED.value,
                reason=f"Commitment phase complete (confidence {confidence}% >= {threshold}%). Session ending.",
                retry_count=retry_count,
            )

        # Before advancing, check Gap Builder for the NEXT phase
        next_gap_ok, next_gap_reason = check_gap_builder_constraint(next_phase, profile)
        if not next_gap_ok:
            return DecisionOutput(
                action="STAY",
                target_phase=current_phase.value,
                reason=f"Exit criteria met ({confidence}%) but next phase blocked: {next_gap_reason}. Staying to gather more info.",
                retry_count=retry_count,
            )

        return DecisionOutput(
            action="ADVANCE",
            target_phase=next_phase.value,
            reason=f"Exit criteria met: confidence {confidence}% >= threshold {threshold}%. Advancing to {next_phase.value}.",
            retry_count=0,
        )

    # 6. Break Glass check
    max_retries = get_max_retries(current_phase)
    if retry_count >= max_retries:
        # Only force-advance if we're reasonably close to the threshold (75%+)
        # This prevents premature advancement when we haven't gathered enough info
        if confidence >= threshold * 0.75:
            next_phase = get_next_phase(current_phase)
            return DecisionOutput(
                action="ADVANCE",
                target_phase=next_phase.value,
                reason=f"Break Glass: {retry_count} retries exceeded max {max_retries}. Confidence {confidence}% is above minimum {int(threshold * 0.75)}%. Force-advancing.",
                retry_count=0,
            )
        elif retry_count >= max_retries + 2:
            # Hard ceiling: if we're WAY over retries, force-advance anyway to prevent infinite loops
            next_phase = get_next_phase(current_phase)
            return DecisionOutput(
                action="ADVANCE",
                target_phase=next_phase.value,
                reason=f"Hard ceiling: {retry_count} retries, well past max {max_retries}. Force-advancing to prevent stall.",
                retry_count=0,
            )
        else:
            return DecisionOutput(
                action="BREAK_GLASS",
                target_phase=current_phase.value,
                reason=f"Break Glass: {retry_count} retries, confidence only {confidence}% (need {int(threshold * 0.75)}% min). Trying a different angle.",
                retry_count=retry_count + 1,
            )

    # 7. Default: Stay in current phase
    return DecisionOutput(
        action="STAY",
        target_phase=current_phase.value,
        reason=f"Exit criteria not yet met: confidence {confidence}% < threshold {threshold}%. Missing: {comprehension.exit_evaluation.missing_info}",
        retry_count=retry_count + 1,
    )
