from __future__ import annotations
"""
Sally Sells — The NEPQ Engine (Orchestrator)

Orchestrates the three layers:
1. Comprehension (Layer 1) — analyze the user message
2. Decision (Layer 2) — decide what to do
3. Response (Layer 3) — generate Sally's reply
"""

import json
import logging
from typing import Optional

from app.schemas import NepqPhase
from app.models import (
    ComprehensionOutput,
    DecisionOutput,
    ThoughtLog,
    ProspectProfile,
    ObjectionType,
    UserIntent,
)
from app.layers.comprehension import run_comprehension
from app.layers.decision import make_decision
from app.layers.response import generate_response

logger = logging.getLogger("sally.engine")


class SallyEngine:
    """
    The NEPQ Sales Engine.

    Usage:
        result = SallyEngine.process_turn(
            current_phase=NepqPhase.CONNECTION,
            user_message="Hi, I'm the VP of Ops at Acme Realty",
            conversation_history=[...],
            profile_json="{}",
            retry_count=0,
            turn_number=1,
            conversation_start_time=1707400000.0,
        )
    """

    @staticmethod
    def get_greeting() -> str:
        return (
            "Hey there! I'm Sally from 100x. "
            "Super curious to learn about you. "
            "What do you do, and what brought you here today?"
        )

    @staticmethod
    def update_profile(
        profile: ProspectProfile,
        updates: dict,
    ) -> ProspectProfile:
        """
        Apply extracted updates from Layer 1 to the prospect profile.
        Handles list fields (append) vs scalar fields (replace).
        """
        list_fields = {
            "pain_points", "frustrations", "tools_mentioned",
            "success_metrics", "objections_encountered", "objections_resolved",
        }

        profile_dict = profile.model_dump()

        for key, value in updates.items():
            if key not in profile_dict:
                continue

            if key in list_fields:
                existing = profile_dict.get(key, [])
                if isinstance(value, list):
                    for item in value:
                        if item and item not in existing:
                            existing.append(item)
                elif isinstance(value, str) and value:
                    if value not in existing:
                        existing.append(value)
                profile_dict[key] = existing
            else:
                if value is not None and value != "":
                    profile_dict[key] = value

        return ProspectProfile(**profile_dict)

    @staticmethod
    def process_turn(
        current_phase: NepqPhase,
        user_message: str,
        conversation_history: list[dict],
        profile_json: str,
        retry_count: int,
        turn_number: int,
        conversation_start_time: float,
        consecutive_no_new_info: int = 0,
        turns_in_current_phase: int = 0,
        deepest_emotional_depth: str = "surface",
        objection_diffusion_step: int = 0,
    ) -> dict:
        """
        Process a single conversation turn through all three layers.

        Returns:
            {
                "response_text": str,
                "new_phase": str,
                "new_profile_json": str,
                "thought_log_json": str,
                "phase_changed": bool,
                "session_ended": bool,
                "retry_count": int,
                "consecutive_no_new_info": int,
                "turns_in_current_phase": int,
                "deepest_emotional_depth": str,
                "objection_diffusion_step": int,
            }
        """

        # Load profile
        try:
            profile_data = json.loads(profile_json) if profile_json else {}
            profile = ProspectProfile(**profile_data)
        except (json.JSONDecodeError, Exception):
            profile = ProspectProfile()

        # Layer 1: Comprehension
        logger.info(f"[Turn {turn_number}] Layer 1: Analyzing message in {current_phase.value}")
        comprehension = run_comprehension(
            current_phase=current_phase,
            user_message=user_message,
            conversation_history=conversation_history,
            prospect_profile=profile,
        )
        logger.info(f"[Turn {turn_number}] Layer 1 result: intent={comprehension.user_intent}, "
                     f"objection={comprehension.objection_type}, "
                     f"criteria={comprehension.exit_evaluation.criteria_met_count}/{comprehension.exit_evaluation.criteria_total_count}, "
                     f"new_info={comprehension.new_information}")

        # Update profile with Layer 1 extractions
        if comprehension.profile_updates:
            profile = SallyEngine.update_profile(profile, comprehension.profile_updates)
            logger.info(f"[Turn {turn_number}] Profile updated: {list(comprehension.profile_updates.keys())}")

        # Track objections in profile
        if comprehension.objection_type != ObjectionType.NONE:
            objection_text = f"{comprehension.objection_type.value}: {comprehension.objection_detail or 'unspecified'}"
            if objection_text not in profile.objections_encountered:
                profile.objections_encountered.append(objection_text)

        # Repetition detection: track consecutive turns with no new information
        if comprehension.new_information:
            consecutive_no_new_info = 0
        else:
            consecutive_no_new_info += 1

        # Track deepest emotional depth (only upgrades, never downgrades)
        DEPTH_ORDER = {"surface": 0, "moderate": 1, "deep": 2}
        current_depth_level = DEPTH_ORDER.get(comprehension.emotional_depth, 0)
        deepest_level = DEPTH_ORDER.get(deepest_emotional_depth, 0)
        if current_depth_level > deepest_level:
            deepest_emotional_depth = comprehension.emotional_depth

        # Track objection diffusion step
        if comprehension.objection_type != ObjectionType.NONE and current_phase in {NepqPhase.OWNERSHIP, NepqPhase.COMMITMENT}:
            if objection_diffusion_step == 0:
                objection_diffusion_step = 1  # Start diffusion
            elif comprehension.objection_diffusion_status == "repeated":
                objection_diffusion_step = 1  # Restart
        elif comprehension.objection_diffusion_status == "diffused":
            objection_diffusion_step = max(objection_diffusion_step, 1)
        elif comprehension.objection_diffusion_status == "isolated":
            objection_diffusion_step = max(objection_diffusion_step, 2)
        elif comprehension.objection_diffusion_status == "resolved":
            objection_diffusion_step = 3
        # Reset on definitive response
        if comprehension.user_intent == UserIntent.AGREEMENT and objection_diffusion_step > 0:
            objection_diffusion_step = 0

        # Increment turns in current phase
        turns_in_current_phase += 1

        logger.info(f"[Turn {turn_number}] Tracking: new_info={comprehension.new_information}, "
                     f"consecutive_no_new_info={consecutive_no_new_info}, "
                     f"turns_in_phase={turns_in_current_phase}, "
                     f"richness={comprehension.response_richness}, "
                     f"depth={comprehension.emotional_depth}, "
                     f"deepest_depth={deepest_emotional_depth}, "
                     f"diffusion_step={objection_diffusion_step}")

        # Layer 2: Decision
        logger.info(f"[Turn {turn_number}] Layer 2: Making decision...")
        decision = make_decision(
            current_phase=current_phase,
            comprehension=comprehension,
            profile=profile,
            retry_count=retry_count,
            conversation_turn=turn_number,
            conversation_start_time=conversation_start_time,
            consecutive_no_new_info=consecutive_no_new_info,
            turns_in_current_phase=turns_in_current_phase,
            deepest_emotional_depth=deepest_emotional_depth,
            objection_diffusion_step=objection_diffusion_step,
        )
        logger.info(f"[Turn {turn_number}] Layer 2 result: action={decision.action}, "
                     f"target_phase={decision.target_phase}, reason={decision.reason}")

        # Build emotional context from Layer 1 for Layer 3
        # Include exit criteria for OWNERSHIP sequencing
        exit_criteria_for_l3 = {}
        for cid, cresult in comprehension.exit_evaluation.criteria.items():
            exit_criteria_for_l3[cid] = {"met": cresult.met, "evidence": cresult.evidence}

        emotional_context = {
            "prospect_exact_words": comprehension.prospect_exact_words,
            "emotional_cues": comprehension.emotional_cues,
            "energy_level": comprehension.energy_level,
            "emotional_tone": comprehension.emotional_tone,
            "emotional_intensity": comprehension.emotional_intensity,
            "response_richness": comprehension.response_richness,
            "emotional_depth": comprehension.emotional_depth,
            "exit_evaluation_criteria": exit_criteria_for_l3,
        }
        logger.info(f"[Turn {turn_number}] Emotional context: tone={comprehension.emotional_tone}, "
                     f"energy={comprehension.energy_level}, "
                     f"mirror_phrases={comprehension.prospect_exact_words}")

        # Layer 3: Response (with circuit breaker + emotional intelligence)
        is_probe = decision.action == "PROBE"
        logger.info(f"[Turn {turn_number}] Layer 3: Generating response for {decision.target_phase} (probe={is_probe})")
        response_text = generate_response(
            decision=decision,
            user_message=user_message,
            conversation_history=conversation_history,
            profile=profile,
            emotional_context=emotional_context,
            probe_mode=is_probe,
        )
        logger.info(f"[Turn {turn_number}] Layer 3 result: '{response_text[:80]}...'")

        # Build ThoughtLog
        thought_log = ThoughtLog(
            turn_number=turn_number,
            user_message=user_message,
            comprehension=comprehension,
            decision=decision,
            response_phase=decision.target_phase,
            response_text=response_text,
            profile_snapshot=profile.model_dump(),
        )

        # Determine state changes
        new_phase = NepqPhase(decision.target_phase)
        phase_changed = new_phase != current_phase
        session_ended = decision.action == "END" or new_phase == NepqPhase.TERMINATED

        # Reset phase-specific counters on phase change
        if phase_changed:
            turns_in_current_phase = 0
            objection_diffusion_step = 0

        return {
            "response_text": response_text,
            "new_phase": decision.target_phase,
            "new_profile_json": json.dumps(profile.model_dump()),
            "thought_log_json": json.dumps(thought_log.model_dump()),
            "phase_changed": phase_changed,
            "session_ended": session_ended,
            "retry_count": decision.retry_count,
            "consecutive_no_new_info": consecutive_no_new_info,
            "turns_in_current_phase": turns_in_current_phase,
            "deepest_emotional_depth": deepest_emotional_depth,
            "objection_diffusion_step": objection_diffusion_step,
        }
