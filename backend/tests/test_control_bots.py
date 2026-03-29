"""Tests for Hank/Ivy control bot conversation flow."""
import pytest
from unittest.mock import patch, MagicMock
from app.bots.hank import HankBot
from app.bots.ivy import IvyBot


def _mock_claude_response(text: str):
    """Build a mock Anthropic messages.create response."""
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text=text)]
    return mock_resp


@pytest.fixture
def mock_anthropic():
    with patch("app.bots.base.get_client") as mock_get:
        mock_client = MagicMock()
        mock_get.return_value = mock_client
        yield mock_client


class TestHankBot:
    def test_respond_first_turn_no_fallback(self, mock_anthropic):
        """First user message after greeting must not hit fallback."""
        mock_anthropic.messages.create.return_value = _mock_claude_response(
            "Great to hear you're a loan officer! How many loans are you closing monthly?"
        )
        hank = HankBot()
        # Simulate conversation_history as main.py builds it:
        # greeting (assistant) + first user message
        history = [
            {"role": "assistant", "content": hank.get_greeting()},
            {"role": "user", "content": "I am a loan officer"},
        ]
        result = hank.respond("I am a loan officer", history)

        assert "Could you tell me more" not in result["response_text"]
        # Verify the API was actually called (not skipped)
        mock_anthropic.messages.create.assert_called_once()
        # Verify first message in the call was role=user
        call_kwargs = mock_anthropic.messages.create.call_args
        messages_sent = call_kwargs.kwargs.get("messages") or call_kwargs[1].get("messages")
        assert messages_sent[0]["role"] == "user", \
            f"First message role was '{messages_sent[0]['role']}', expected 'user'"

    def test_respond_multi_turn(self, mock_anthropic):
        """Multi-turn conversation maintains alternating roles."""
        mock_anthropic.messages.create.return_value = _mock_claude_response(
            "That's incredible volume! AI could add 3-4 extra closings per month."
        )
        hank = HankBot()
        history = [
            {"role": "assistant", "content": hank.get_greeting()},
            {"role": "user", "content": "I'm a broker"},
            {"role": "assistant", "content": "Awesome! How many loans monthly?"},
            {"role": "user", "content": "About 20"},
        ]
        result = hank.respond("About 20", history)
        assert "Could you tell me more" not in result["response_text"]

        call_kwargs = mock_anthropic.messages.create.call_args
        messages_sent = call_kwargs.kwargs.get("messages") or call_kwargs[1].get("messages")
        # Verify alternating roles
        for i in range(1, len(messages_sent)):
            assert messages_sent[i]["role"] != messages_sent[i - 1]["role"], \
                f"Consecutive same role at index {i}: {messages_sent[i]['role']}"


class TestIvyBot:
    def test_respond_first_turn_no_fallback(self, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_claude_response(
            "The 100x AI Academy is a training program for mortgage professionals."
        )
        ivy = IvyBot()
        history = [
            {"role": "assistant", "content": ivy.get_greeting()},
            {"role": "user", "content": "What is this?"},
        ]
        result = ivy.respond("What is this?", history)
        assert "Could you tell me more" not in result["response_text"]
        mock_anthropic.messages.create.assert_called_once()

        call_kwargs = mock_anthropic.messages.create.call_args
        messages_sent = call_kwargs.kwargs.get("messages") or call_kwargs[1].get("messages")
        assert messages_sent[0]["role"] == "user", \
            f"First message role was '{messages_sent[0]['role']}', expected 'user'"


class TestExitDetection:
    def test_explicit_exit_phrases(self, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_claude_response("Thanks!")
        hank = HankBot()
        history = [
            {"role": "assistant", "content": hank.get_greeting()},
            {"role": "user", "content": "done"},
        ]
        result = hank.respond("done", history)
        assert result["session_ended"] is True

    def test_normal_message_no_exit(self, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_claude_response("Tell me more!")
        hank = HankBot()
        history = [
            {"role": "assistant", "content": hank.get_greeting()},
            {"role": "user", "content": "I close 10 loans a month"},
        ]
        result = hank.respond("I close 10 loans a month", history)
        assert result["session_ended"] is False

    def test_product_rejection_not_exit(self, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_claude_response("I hear you, but...")
        hank = HankBot()
        history = [
            {"role": "assistant", "content": hank.get_greeting()},
            {"role": "user", "content": "not interested"},
        ]
        result = hank.respond("not interested", history)
        assert result["session_ended"] is False, "Product rejection should NOT end session"

    def test_exit_with_punctuation(self, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_claude_response("Bye!")
        hank = HankBot()
        history = [
            {"role": "assistant", "content": hank.get_greeting()},
            {"role": "user", "content": "goodbye!"},
        ]
        result = hank.respond("goodbye!", history)
        assert result["session_ended"] is True

    def test_exit_phrase_in_sentence(self, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_claude_response("Ok!")
        hank = HankBot()
        history = [
            {"role": "assistant", "content": hank.get_greeting()},
            {"role": "user", "content": "I'm done"},
        ]
        result = hank.respond("I'm done", history)
        assert result["session_ended"] is True
