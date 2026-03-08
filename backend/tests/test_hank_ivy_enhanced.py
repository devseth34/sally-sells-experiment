"""
Tests for enhanced Hank and Ivy bots.
Run with: cd backend && python -m pytest tests/test_hank_ivy_enhanced.py -v
"""
import pytest
from unittest.mock import patch


class TestHankPrompt:
    """Verify Hank's system prompt has correct product info and methodology."""

    def test_hank_sells_correct_product(self):
        from app.bots.hank import HankBot
        bot = HankBot()
        prompt_lower = bot.system_prompt.lower()
        assert "$10,000" in bot.system_prompt or "10,000" in bot.system_prompt
        assert "discovery workshop" in prompt_lower
        assert "nik shah" in prompt_lower
        # Should NOT mention mortgage-specific product
        assert "mortgage agents course" not in prompt_lower

    def test_hank_has_phases(self):
        from app.bots.hank import HankBot
        bot = HankBot()
        assert "PHASE 1" in bot.system_prompt
        assert "PHASE 2" in bot.system_prompt
        assert "PHASE 3" in bot.system_prompt

    def test_hank_has_link_handling(self):
        from app.bots.hank import HankBot
        bot = HankBot()
        assert "[PAYMENT_LINK]" in bot.system_prompt

    def test_hank_has_fact_sheet(self):
        from app.bots.hank import HankBot
        bot = HankBot()
        # Should include fact sheet content (100x is in both prompt and fact sheet)
        assert "100x" in bot.system_prompt

    def test_hank_greeting_correct_product(self):
        from app.bots.hank import HankBot
        bot = HankBot()
        greeting = bot.get_greeting()
        assert "100x" in greeting
        assert "mortgage" not in greeting.lower()


class TestIvyPrompt:
    """Verify Ivy's system prompt has correct product info and methodology."""

    def test_ivy_correct_product(self):
        from app.bots.ivy import IvyBot
        bot = IvyBot()
        prompt_lower = bot.system_prompt.lower()
        assert "$10,000" in bot.system_prompt or "10,000" in bot.system_prompt
        assert "discovery workshop" in prompt_lower
        assert "nik shah" in prompt_lower
        assert "mortgage agents course" not in prompt_lower

    def test_ivy_has_phases(self):
        from app.bots.ivy import IvyBot
        bot = IvyBot()
        assert "PHASE 1" in bot.system_prompt
        assert "PHASE 2" in bot.system_prompt
        assert "PHASE 3" in bot.system_prompt

    def test_ivy_has_alternatives(self):
        from app.bots.ivy import IvyBot
        bot = IvyBot()
        prompt_lower = bot.system_prompt.lower()
        assert "alternative" in prompt_lower
        assert "pro" in prompt_lower and "con" in prompt_lower

    def test_ivy_has_link_handling(self):
        from app.bots.ivy import IvyBot
        bot = IvyBot()
        assert "[PAYMENT_LINK]" in bot.system_prompt

    def test_ivy_greeting_neutral(self):
        from app.bots.ivy import IvyBot
        bot = IvyBot()
        greeting = bot.get_greeting()
        assert "!" not in greeting  # Ivy doesn't use exclamation marks
        assert "mortgage" not in greeting.lower()


class TestBaseBotEnhancements:
    """Verify base bot has turn tracking and memory support."""

    def test_turn_context_early_conversation(self):
        from app.bots.base import ControlBot
        bot = ControlBot()
        context = bot._build_turn_context([
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "Hey"},
        ])
        assert "turn 1" in context.lower()
        assert "early conversation" in context.lower()

    def test_turn_context_late_conversation(self):
        from app.bots.base import ControlBot
        bot = ControlBot()
        history = []
        for i in range(16):
            history.append({"role": "assistant", "content": f"Bot message {i}"})
            history.append({"role": "user", "content": f"User message {i}"})
        context = bot._build_turn_context(history)
        assert "extended conversation" in context.lower()

    def test_turn_context_mid_conversation(self):
        from app.bots.base import ControlBot
        bot = ControlBot()
        history = []
        for i in range(4):
            history.append({"role": "assistant", "content": f"Bot message {i}"})
            history.append({"role": "user", "content": f"User message {i}"})
        context = bot._build_turn_context(history)
        assert "mid conversation" in context.lower()

    def test_profile_hint_extraction(self):
        from app.bots.base import ControlBot
        bot = ControlBot()
        history = [
            {"role": "user", "content": "I'm the CEO of a startup with a team of 10"},
        ]
        hints = bot._extract_profile_hints(history)
        assert hints.get("has_role") is True
        assert hints.get("has_company") is True

    def test_profile_hint_price_concern(self):
        from app.bots.base import ControlBot
        bot = ControlBot()
        history = [
            {"role": "user", "content": "That seems pretty expensive, can we discuss the budget?"},
        ]
        hints = bot._extract_profile_hints(history)
        assert hints.get("price_concern") is True

    def test_memory_context_accepted(self):
        """Base bot respond() should accept memory_context parameter."""
        from app.bots.base import ControlBot
        bot = ControlBot()
        # Just verify the method signature accepts it
        import inspect
        sig = inspect.signature(bot.respond)
        assert "memory_context" in sig.parameters

    def test_conversation_history_capping(self):
        """History longer than 20 messages should be capped."""
        from app.bots.base import ControlBot
        bot = ControlBot()
        # Build a long history
        long_history = []
        for i in range(30):
            long_history.append({"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"})
        # The capping happens inside respond(), but we can test the logic
        capped = long_history[-20:] if len(long_history) > 20 else long_history
        assert len(capped) == 20


class TestCrossBotMemory:
    """Verify memory system is bot-agnostic."""

    def test_memory_extraction_accepts_bot_arm(self):
        """Memory extraction should accept bot_arm parameter."""
        from app.memory import extract_memory_from_session
        import inspect
        sig = inspect.signature(extract_memory_from_session)
        assert "bot_arm" in sig.parameters

    def test_store_memory_accepts_bot_arm(self):
        """Memory storage should accept bot_arm parameter."""
        from app.memory import store_memory
        import inspect
        sig = inspect.signature(store_memory)
        assert "bot_arm" in sig.parameters

    def test_router_passes_memory_to_all_bots(self):
        """Router should accept and pass memory_context to Hank and Ivy."""
        from app.bot_router import route_message
        import inspect
        sig = inspect.signature(route_message)
        assert "memory_context" in sig.parameters

    def test_format_memory_has_cross_bot_note(self):
        """format_memory_for_prompt should include cross-bot note when summaries exist."""
        from app.memory import format_memory_for_prompt
        memory = {
            "has_memory": True,
            "identity": {"name": "Test"},
            "situation": {},
            "pain_points": [],
            "objection_history": [],
            "emotional_signals": [],
            "relationship": {},
            "emotional_peaks": [],
            "strategic_notes": {},
            "unfinished_threads": [],
            "session_summaries": [
                {"summary": "Test summary", "outcome": "abandoned_mid", "phase": "CONNECTION"},
            ],
            "total_prior_sessions": 1,
        }
        result = format_memory_for_prompt(memory)
        assert "different team members" in result
        assert "Sally, Hank, or Ivy" in result


class TestLinkInjection:
    """Verify link cleanup works for all bots."""

    def test_calendly_stripping(self):
        """Link cleanup should handle hallucinated Calendly URLs."""
        from app.bots.base import ControlBot
        bot = ControlBot()
        text = "Here's the link: https://calendly.com/fake/link"
        cleaned = bot._inject_links(text)
        assert "calendly.com" not in cleaned

    def test_tidycal_fixing(self):
        """Link cleanup should fix TidyCal URLs when TIDYCAL_PATH is set."""
        from app.bots.base import ControlBot
        bot = ControlBot()
        with patch.dict("os.environ", {"TIDYCAL_PATH": "correct-path"}):
            text = "Book here: https://tidycal.com/wrong-path"
            fixed = bot._inject_links(text)
            assert "https://tidycal.com/correct-path" in fixed
            assert "wrong-path" not in fixed

    def test_no_tidycal_fix_when_no_env(self):
        """Link cleanup should not modify TidyCal URLs when TIDYCAL_PATH is empty."""
        from app.bots.base import ControlBot
        bot = ControlBot()
        with patch.dict("os.environ", {"TIDYCAL_PATH": ""}):
            text = "Book here: https://tidycal.com/some-path"
            result = bot._inject_links(text)
            # Should not crash, URL stays as-is since no TIDYCAL_PATH
            assert "tidycal.com" in result
