"""Text-mode REPL for the Sally engine — exercise L1+L2+L3 + circuit
breaker without Deepgram/Cartesia/LiveKit. Lets you verify response
behavior (brand-question handling, fallback variance, persona
adherence) when voice testing isn't convenient.

Run from the backend/ directory:
    cd backend && python chat_repl.py
"""
from __future__ import annotations

import time
from pathlib import Path

from dotenv import load_dotenv

# Worker normally pulls .env via database.py's import side-effect.
# This REPL skips the FastAPI / database path, so load .env explicitly
# from the repo root (parent of backend/).
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app.agent import SallyEngine  # noqa: E402 — must follow load_dotenv
from app.schemas import NepqPhase  # noqa: E402

OPENER = (
    "Hey there! I'm Sally from 100x. Super curious to learn about you. "
    "What brought you here today?"
)


def main() -> None:
    phase = NepqPhase.CONNECTION
    history: list[dict] = [{"role": "assistant", "content": OPENER}]
    profile_json = "{}"
    turn_number = 1
    consecutive_no_new_info = 0
    turns_in_current_phase = 0
    deepest_emotional_depth = "surface"
    objection_diffusion_step = 0
    ownership_substep = 0
    conversation_start = time.time()

    print("=" * 60)
    print("Text-mode Sally  (no voice pipeline — same engine as voice runner)")
    print("Commands: /phase, /reset, /quit")
    print("=" * 60)
    print(f"\nSally: {OPENER}\n  [phase: {phase.value}]\n")

    while True:
        try:
            user = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[exit]")
            return
        if not user:
            continue
        if user in ("/quit", "/exit"):
            return
        if user == "/phase":
            print(f"  [phase: {phase.value}, turn: {turn_number}]\n")
            continue
        if user == "/reset":
            phase = NepqPhase.CONNECTION
            history = [{"role": "assistant", "content": OPENER}]
            profile_json = "{}"
            turn_number = 1
            consecutive_no_new_info = 0
            turns_in_current_phase = 0
            deepest_emotional_depth = "surface"
            objection_diffusion_step = 0
            ownership_substep = 0
            conversation_start = time.time()
            print(f"\n[session reset]\nSally: {OPENER}\n  [phase: {phase.value}]\n")
            continue

        result = SallyEngine.process_turn(
            current_phase=phase,
            user_message=user,
            conversation_history=history,
            profile_json=profile_json,
            retry_count=0,
            turn_number=turn_number,
            conversation_start_time=conversation_start,
            consecutive_no_new_info=consecutive_no_new_info,
            turns_in_current_phase=turns_in_current_phase,
            deepest_emotional_depth=deepest_emotional_depth,
            objection_diffusion_step=objection_diffusion_step,
            ownership_substep=ownership_substep,
            arm_key="sally_nepq",
        )

        response_text = result["response_text"]
        new_phase = NepqPhase(result["new_phase"])
        phase_changed = result["phase_changed"]

        print(f"\nSally: {response_text}")
        if phase_changed:
            print(f"  [→ phase advanced: {phase.value} → {new_phase.value}]")
        print(f"  [phase: {new_phase.value}, turn: {turn_number}]\n")

        history.append({"role": "user", "content": user})
        history.append({"role": "assistant", "content": response_text})

        phase = new_phase
        profile_json = result["new_profile_json"]
        consecutive_no_new_info = result["consecutive_no_new_info"]
        turns_in_current_phase = result["turns_in_current_phase"]
        deepest_emotional_depth = result["deepest_emotional_depth"]
        objection_diffusion_step = result["objection_diffusion_step"]
        ownership_substep = result["ownership_substep"]
        turn_number += 1

        if result.get("session_ended"):
            print("  [session ended]\n")
            return


if __name__ == "__main__":
    main()
