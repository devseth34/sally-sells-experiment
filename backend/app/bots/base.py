"""
Base class for control bots (Hank, Ivy).
Uses the same lazy Anthropic client pattern as response.py.

Control bots are intentionally simpler than Sally's three-layer engine:
single-prompt Claude calls with no structured phase gates.
"""
from __future__ import annotations

import os
import logging
from anthropic import Anthropic

logger = logging.getLogger("sally.bots")

# Reuse the same lazy client pattern from response.py
_client: Anthropic | None = None


def get_client() -> Anthropic:
    global _client
    if _client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not found.")
        _client = Anthropic(api_key=api_key)
    return _client


class ControlBot:
    """Base class for Hank and Ivy. Single-prompt, no phase gates."""

    name: str = "base"
    display_name: str = "Bot"
    system_prompt: str = ""

    def get_greeting(self) -> str:
        raise NotImplementedError

    def respond(
        self,
        user_message: str,
        conversation_history: list[dict],
        memory_context: str = "",
    ) -> dict:
        """
        Generate a response using a single Claude API call.

        Returns dict matching SallyEngine.process_turn() output shape
        so main.py can handle all bots uniformly.
        """
        # Build messages array for Claude
        # NOTE: conversation_history already includes the current user_message
        # (appended in main.py before calling route_message), so we do NOT
        # append user_message again — that would create consecutive user turns
        # which violates the Claude API alternating-roles requirement.
        messages = []
        for msg in conversation_history:
            role = "user" if msg["role"] == "user" else "assistant"
            messages.append({"role": role, "content": msg["content"]})

        system = self.system_prompt
        if memory_context:
            system = f"{self.system_prompt}\n\n{memory_context}"

        try:
            response = get_client().messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                system=system,
                messages=messages,
            )
            response_text = response.content[0].text.strip()
        except Exception as e:
            logger.error(f"[{self.name}] API error: {e}")
            response_text = self._fallback_response()

        # Strip quotation marks (same as response.py pattern)
        if response_text.startswith('"') and response_text.endswith('"'):
            response_text = response_text[1:-1]

        # Detect session end (simple heuristic for control bots)
        session_ended = self._should_end(user_message, response_text, len(conversation_history))

        return {
            "response_text": response_text,
            "new_phase": "CONVERSATION",  # Control bots don't have NEPQ phases
            "new_profile_json": "{}",
            "thought_log_json": "{}",
            "phase_changed": False,
            "session_ended": session_ended,
            "retry_count": 0,
            "consecutive_no_new_info": 0,
            "turns_in_current_phase": 0,
            "deepest_emotional_depth": "surface",
            "objection_diffusion_step": 0,
            "ownership_substep": 0,
        }

    def _should_end(self, user_message: str, bot_response: str, history_length: int) -> bool:
        """
        End-detection for control bots. Very conservative — only ends when
        the user explicitly asks to END THE CONVERSATION, not when they
        express disinterest in the product (that's just an objection to handle).

        Sally has her own sophisticated end logic in Layer 2.
        """
        # Safety cap only: prevent truly runaway sessions (100 messages = ~50 exchanges)
        if history_length > 100:
            return True

        # Never auto-end based on message content — the user controls when
        # the conversation ends via the UI "New Session" button or by
        # closing the tab. Phrases like "not interested" or "no thanks"
        # are product objections, not conversation-exit signals.
        return False

    def _fallback_response(self) -> str:
        return "Could you tell me more about what you're thinking?"
