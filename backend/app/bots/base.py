"""
Base class for control bots (Hank, Ivy).

Enhanced from the original single-prompt approach to include:
- Turn tracking for conversation pacing
- Memory context injection for returning visitors
- Basic profile extraction so bots can personalize
- Conversation history management (cap at 20 messages for context window efficiency)
- Link injection (same pattern as Sally)
"""
from __future__ import annotations

import os
import re
import json
import logging
from anthropic import Anthropic

logger = logging.getLogger("sally.bots")

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
    """Enhanced base class for Hank and Ivy."""

    name: str = "base"
    display_name: str = "Bot"
    system_prompt: str = ""

    def get_greeting(self) -> str:
        raise NotImplementedError

    def _build_turn_context(self, conversation_history: list[dict]) -> str:
        """Build turn-awareness context for the system prompt."""
        turn_count = sum(1 for m in conversation_history if m.get("role") == "user")
        total_messages = len(conversation_history)

        # Extract basic profile from conversation
        profile_hints = self._extract_profile_hints(conversation_history)

        context = f"\nCONVERSATION STATE:"
        context += f"\n- This is turn {turn_count} of the conversation ({total_messages} total messages)."

        if profile_hints:
            context += f"\n- What you know about them so far: {json.dumps(profile_hints)}"

        # Pacing guidance
        if turn_count <= 2:
            context += "\n- PACING: Early conversation. Focus on understanding who they are and what they need."
        elif turn_count <= 6:
            context += "\n- PACING: Mid conversation. You should have enough context to be specific and personalized."
        elif turn_count <= 12:
            context += "\n- PACING: Late conversation. If you haven't discussed the workshop/price yet, it's time."
        else:
            context += "\n- PACING: Extended conversation. Wrap up. Either close or offer the free alternative."

        return context

    def _extract_profile_hints(self, conversation_history: list[dict]) -> dict:
        """Extract basic profile info from conversation history for personalization."""
        hints = {}
        user_messages = [m["content"] for m in conversation_history if m.get("role") == "user"]
        full_text = " ".join(user_messages).lower()

        # Very basic extraction — enough for personalization, not a full NLP pipeline
        # The LLM does the real work; this just helps with pacing decisions
        if any(word in full_text for word in ["ceo", "founder", "vp", "director", "manager", "lead", "head of"]):
            hints["has_role"] = True
        if any(word in full_text for word in ["company", "startup", "firm", "agency", "team of"]):
            hints["has_company"] = True
        if any(word in full_text for word in ["expensive", "afford", "budget", "cost", "price", "too much"]):
            hints["price_concern"] = True
        if any(word in full_text for word in ["not sure", "maybe later", "think about", "need time"]):
            hints["hesitant"] = True
        if any(word in full_text for word in ["interested", "sounds good", "tell me more", "how do i"]):
            hints["interested"] = True
        if any(word in full_text for word in ["@", "email", "my email"]):
            hints["shared_email"] = True

        return hints

    def respond(
        self,
        user_message: str,
        conversation_history: list[dict],
        memory_context: str = "",
        session_id: str = "",
        channel: str = "web",
    ) -> dict:
        """
        Generate a response using a single Claude API call.
        Enhanced with turn tracking, memory context, and conversation capping.
        """
        # Cap conversation history for context window efficiency
        if len(conversation_history) > 20:
            conversation_history = conversation_history[-20:]

        # Build enhanced system prompt
        turn_context = self._build_turn_context(conversation_history)
        system = self.system_prompt + turn_context

        # Inject memory context for returning visitors
        if memory_context:
            system += f"\n\n{memory_context}"
            system += "\nUSE THIS MEMORY NATURALLY. Reference prior conversations when relevant. Never say 'I remember' or 'from last time' — just know it and use it."

        # Build messages array for Claude
        # NOTE: conversation_history already includes the current user_message
        # (appended in main.py before calling route_message), so we do NOT
        # append user_message again — that would create consecutive user turns
        # which violates the Claude API alternating-roles requirement.
        messages = []
        for msg in conversation_history:
            role = "user" if msg["role"] == "user" else "assistant"
            messages.append({"role": role, "content": msg["content"]})

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

        # Link injection — same pattern as Sally's main.py
        response_text = self._inject_links(response_text, session_id=session_id, arm=self.name, channel=channel)

        # Detect session end
        session_ended = self._should_end(user_message, response_text, len(conversation_history))

        return {
            "response_text": response_text,
            "new_phase": "CONVERSATION",
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

    def _inject_links(self, response_text: str, session_id: str = "", arm: str = "", channel: str = "web") -> str:
        """Handle link placeholders and fix hallucinated URLs."""
        text_lower = response_text.lower()

        # Strip hallucinated Calendly URLs
        if "calendly.com" in text_lower:
            response_text = re.sub(r'https?://calendly\.com/\S+', '', response_text)
            response_text = re.sub(r'\s+', ' ', response_text).strip()

        # Fix TidyCal URLs
        tidycal_path = os.getenv("TIDYCAL_PATH", "")
        if tidycal_path and "tidycal.com" in text_lower:
            tidycal_url = f"https://tidycal.com/{tidycal_path}"
            response_text = re.sub(r'https?://tidycal\.com/\S+', tidycal_url, response_text)

        # Replace [INVITATION_LINK] placeholder with tracked invitation URL
        if "[INVITATION_LINK]" in response_text and session_id:
            from app.invitation import build_invitation_url
            invitation_url = build_invitation_url(
                session_id=session_id,
                arm=arm or self.name,
                channel=channel,
            )
            response_text = response_text.replace("[INVITATION_LINK]", invitation_url)

        return response_text

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
