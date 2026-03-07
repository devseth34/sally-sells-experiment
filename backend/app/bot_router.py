"""
Bot Router — Routes messages to Sally, Hank, or Ivy based on session arm assignment.

Sally uses the existing three-layer engine (agent.py).
Hank and Ivy use simple single-prompt Claude calls (bots/).
"""
import logging
from app.schemas import NepqPhase, BotArm
from app.agent import SallyEngine
from app.bots.hank import HankBot
from app.bots.ivy import IvyBot

logger = logging.getLogger("sally.router")

# Singleton bot instances
_hank = HankBot()
_ivy = IvyBot()

# Map of arm → display name
BOT_DISPLAY_NAMES = {
    BotArm.SALLY_NEPQ: "Sally",
    BotArm.HANK_HYPES: "Hank",
    BotArm.IVY_INFORMS: "Ivy",
}


def get_greeting(arm: BotArm) -> str:
    """Get the opening greeting for the assigned bot."""
    if arm == BotArm.SALLY_NEPQ:
        return SallyEngine.get_greeting()
    elif arm == BotArm.HANK_HYPES:
        return _hank.get_greeting()
    elif arm == BotArm.IVY_INFORMS:
        return _ivy.get_greeting()
    else:
        raise ValueError(f"Unknown arm: {arm}")


def route_message(
    arm: BotArm,
    user_message: str,
    conversation_history: list[dict],
    memory_context: str = "",
    # Sally-specific params (ignored for Hank/Ivy):
    current_phase: NepqPhase = NepqPhase.CONNECTION,
    profile_json: str = "{}",
    retry_count: int = 0,
    turn_number: int = 0,
    conversation_start_time: float = 0,
    consecutive_no_new_info: int = 0,
    turns_in_current_phase: int = 0,
    deepest_emotional_depth: str = "surface",
    objection_diffusion_step: int = 0,
    ownership_substep: int = 0,
) -> dict:
    """
    Route a message to the correct bot.

    Returns a dict with the same shape regardless of bot, so main.py
    can handle all three uniformly.
    """
    logger.info(f"[Router] Routing to {arm.value}")

    if arm == BotArm.SALLY_NEPQ:
        # Sally uses the full three-layer engine — pass everything through
        return SallyEngine.process_turn(
            current_phase=current_phase,
            user_message=user_message,
            conversation_history=conversation_history,
            profile_json=profile_json,
            retry_count=retry_count,
            turn_number=turn_number,
            conversation_start_time=conversation_start_time,
            consecutive_no_new_info=consecutive_no_new_info,
            turns_in_current_phase=turns_in_current_phase,
            deepest_emotional_depth=deepest_emotional_depth,
            objection_diffusion_step=objection_diffusion_step,
            ownership_substep=ownership_substep,
            memory_context=memory_context,
        )

    elif arm == BotArm.HANK_HYPES:
        return _hank.respond(user_message, conversation_history, memory_context=memory_context)

    elif arm == BotArm.IVY_INFORMS:
        return _ivy.respond(user_message, conversation_history, memory_context=memory_context)

    else:
        raise ValueError(f"Unknown arm: {arm}")
