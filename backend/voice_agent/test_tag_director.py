"""Unit tests for the Haiku tag director.

Mocks `AsyncAnthropic` end-to-end — never hits the real API. Each test
patches `tag_director._client` (or `_get_client`) with a `MagicMock`
whose `messages.create` is an `AsyncMock` returning a controlled
response shape.

Covers all paths from the spec:
    - Success
    - Timeout
    - HTTP error
    - Malformed JSON
    - Code-fenced JSON
    - Trailing prose
    - Hallucinated tag
    - Decoration drift
    - Trivial text short-circuit
    - Empty whitelist short-circuit
    - Empty history rendering
    - Faithfulness allows ellipsis/em-dash/CAPS substitutions
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.voice_agent import tag_director
from backend.voice_agent.tag_director import (
    DirectorResult,
    _decoration_is_faithful,
    _format_history,
    _parse_director_json,
    direct_tags,
)


# ── Test helpers ──────────────────────────────────────────────────────


def _make_response(json_text: str) -> MagicMock:
    """Build a fake Anthropic Messages response object with .content[0].text."""
    block = MagicMock()
    block.text = json_text
    response = MagicMock()
    response.content = [block]
    return response


def _patch_client(monkeypatch, *, side_effect=None, return_value=None) -> AsyncMock:
    """Replace tag_director._client with a fake AsyncAnthropic-like mock.

    Returns the AsyncMock for `messages.create` so tests can assert call counts.
    """
    create_mock = AsyncMock(side_effect=side_effect, return_value=return_value)
    fake_client = MagicMock()
    fake_client.messages.create = create_mock
    monkeypatch.setattr(tag_director, "_client", fake_client)
    return create_mock


@pytest.fixture(autouse=True)
def _reset_client(monkeypatch):
    """Clear the lazy-cached client between tests so each can install its own mock."""
    monkeypatch.setattr(tag_director, "_client", None)
    yield


# ── Constants used across tests ──────────────────────────────────────


LONG_TEXT = (
    "Yeah, I hear you. That sounds really tough to deal with day after day. "
    "Walk me through what happened the most recent time."
)

ALL_TAGS = [
    "[laughs]", "[sighs]", "[exhales]", "[empathetic]", "[curious]",
    "[reassuring]", "[softly]", "[serious]", "[thoughtful]", "[warmly]",
    "[hopeful]", "[concerned]", "[surprised]", "[excited]", "[clears throat]",
    "[breathes in]", "[pauses]",
]


# ── Success path ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_successful_director_call_returns_tags(monkeypatch) -> None:
    decorated = (
        "[sighs] Yeah, I hear you. [empathetic] That sounds really tough to "
        "deal with day after day. Walk me through what happened the most recent time."
    )
    payload = {
        "decorated_text": decorated,
        "tags_used": ["[sighs]", "[empathetic]"],
        "reasoning": "empathic open on PROBLEM_AWARENESS",
    }
    create_mock = _patch_client(
        monkeypatch, return_value=_make_response(json.dumps(payload))
    )

    result = await direct_tags(
        LONG_TEXT,
        phase="PROBLEM_AWARENESS",
        user_emotion="frustrated",
        history=[{"role": "user", "content": "I'm so stuck"}],
        allowed_tags=ALL_TAGS,
    )

    assert result.success is True
    assert result.fallback_reason is None
    assert result.decorated_text == decorated
    assert result.tags_used == ["[sighs]", "[empathetic]"]
    assert result.latency_ms >= 0.0
    create_mock.assert_awaited_once()


# ── Timeout path ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_timeout_returns_fallback(monkeypatch) -> None:
    async def hang(*_args, **_kwargs):
        await asyncio.sleep(10.0)  # exceeds the 50ms timeout below

    _patch_client(monkeypatch, side_effect=hang)

    result = await direct_tags(
        LONG_TEXT,
        phase="PROBLEM_AWARENESS",
        user_emotion="frustrated",
        history=[],
        allowed_tags=ALL_TAGS,
        timeout_s=0.05,
    )

    assert result.success is False
    assert result.fallback_reason == "timeout"
    assert result.decorated_text == LONG_TEXT
    assert result.tags_used == []


# ── HTTP error path ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_http_error_returns_fallback(monkeypatch) -> None:
    _patch_client(monkeypatch, side_effect=ConnectionError("network down"))

    result = await direct_tags(
        LONG_TEXT,
        phase="CONNECTION",
        user_emotion=None,
        history=[],
        allowed_tags=ALL_TAGS,
    )

    assert result.success is False
    assert result.fallback_reason is not None
    assert result.fallback_reason.startswith("http_error")
    assert "ConnectionError" in result.fallback_reason
    assert result.decorated_text == LONG_TEXT


# ── Parse error path ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_malformed_json_returns_fallback(monkeypatch) -> None:
    _patch_client(
        monkeypatch, return_value=_make_response("this is not json at all just prose")
    )

    result = await direct_tags(
        LONG_TEXT,
        phase="CONSEQUENCE",
        user_emotion="sad",
        history=[],
        allowed_tags=ALL_TAGS,
    )

    assert result.success is False
    assert result.fallback_reason == "parse_error"
    assert result.decorated_text == LONG_TEXT


# ── Code-fenced JSON ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_code_fenced_json_parses(monkeypatch) -> None:
    decorated = "[sighs] " + LONG_TEXT
    payload = {"decorated_text": decorated, "tags_used": ["[sighs]"]}
    fenced = "```json\n" + json.dumps(payload) + "\n```"
    _patch_client(monkeypatch, return_value=_make_response(fenced))

    result = await direct_tags(
        LONG_TEXT,
        phase="PROBLEM_AWARENESS",
        user_emotion="frustrated",
        history=[],
        allowed_tags=ALL_TAGS,
    )

    assert result.success is True
    assert result.tags_used == ["[sighs]"]


@pytest.mark.asyncio
async def test_bare_fenced_json_parses(monkeypatch) -> None:
    decorated = "[laughs] " + LONG_TEXT
    payload = {"decorated_text": decorated, "tags_used": ["[laughs]"]}
    fenced = "```\n" + json.dumps(payload) + "\n```"
    _patch_client(monkeypatch, return_value=_make_response(fenced))

    result = await direct_tags(
        LONG_TEXT,
        phase="CONNECTION",
        user_emotion="playful",
        history=[],
        allowed_tags=ALL_TAGS,
    )

    assert result.success is True
    assert result.tags_used == ["[laughs]"]


# ── Trailing prose around JSON ────────────────────────────────────────


@pytest.mark.asyncio
async def test_trailing_prose_around_json_parses(monkeypatch) -> None:
    decorated = "[curious] " + LONG_TEXT
    payload = {"decorated_text": decorated, "tags_used": ["[curious]"]}
    raw = "Here's my decoration:\n" + json.dumps(payload) + "\n\nHope that helps!"
    _patch_client(monkeypatch, return_value=_make_response(raw))

    result = await direct_tags(
        LONG_TEXT,
        phase="SITUATION",
        user_emotion=None,
        history=[],
        allowed_tags=ALL_TAGS,
    )

    assert result.success is True
    assert result.tags_used == ["[curious]"]


# ── Hallucinated tag ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_tag_rejected(monkeypatch) -> None:
    decorated = "[chuckles] " + LONG_TEXT
    payload = {"decorated_text": decorated, "tags_used": ["[chuckles]"]}  # not in whitelist
    _patch_client(monkeypatch, return_value=_make_response(json.dumps(payload)))

    result = await direct_tags(
        LONG_TEXT,
        phase="CONNECTION",
        user_emotion="playful",
        history=[],
        allowed_tags=["[laughs]", "[sighs]"],  # narrow whitelist
    )

    assert result.success is False
    assert result.fallback_reason is not None
    assert result.fallback_reason.startswith("invalid_tags")
    assert "[chuckles]" in result.fallback_reason
    assert result.decorated_text == LONG_TEXT


# ── Decoration drift ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_drift_rejected_when_haiku_rephrases(monkeypatch) -> None:
    # Haiku rephrased "the most recent time" → "the latest occurrence" — drift.
    rephrased = (
        "[sighs] Yeah, I hear you. That sounds really tough to deal with day "
        "after day. Walk me through what happened the latest occurrence."
    )
    payload = {"decorated_text": rephrased, "tags_used": ["[sighs]"]}
    _patch_client(monkeypatch, return_value=_make_response(json.dumps(payload)))

    result = await direct_tags(
        LONG_TEXT,
        phase="PROBLEM_AWARENESS",
        user_emotion="frustrated",
        history=[],
        allowed_tags=ALL_TAGS,
    )

    assert result.success is False
    assert result.fallback_reason == "decoration_drift"
    assert result.decorated_text == LONG_TEXT


# ── Trivial-text short-circuit ────────────────────────────────────────


@pytest.mark.asyncio
async def test_trivial_text_skips_api_call(monkeypatch) -> None:
    create_mock = _patch_client(monkeypatch, return_value=_make_response("{}"))

    result = await direct_tags(
        "Got it.",  # 7 chars, well under 30
        phase="CONNECTION",
        user_emotion=None,
        history=[],
        allowed_tags=ALL_TAGS,
    )

    assert result.success is True
    assert result.fallback_reason is None
    assert result.decorated_text == "Got it."
    assert result.tags_used == []
    create_mock.assert_not_awaited()


# ── Empty whitelist short-circuit ─────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_whitelist_skips_api_call(monkeypatch) -> None:
    create_mock = _patch_client(monkeypatch, return_value=_make_response("{}"))

    result = await direct_tags(
        LONG_TEXT,
        phase="PROBLEM_AWARENESS",
        user_emotion="frustrated",
        history=[],
        allowed_tags=[],
    )

    assert result.success is True
    assert result.decorated_text == LONG_TEXT
    assert result.tags_used == []
    create_mock.assert_not_awaited()


# ── History formatting ────────────────────────────────────────────────


def test_empty_history_renders_placeholder() -> None:
    assert _format_history([]) == "(no prior turns)"


def test_history_renders_role_content_lines() -> None:
    out = _format_history(
        [
            {"role": "user", "content": "I'm stuck"},
            {"role": "assistant", "content": "Tell me more"},
        ]
    )
    assert "user: I'm stuck" in out
    assert "assistant: Tell me more" in out


def test_history_tolerates_malformed_entries() -> None:
    # Should not crash on non-dict entries
    out = _format_history([{"role": "user", "content": "ok"}, "garbage", None])
    assert "user: ok" in out


# ── Faithfulness — allowed substitutions ─────────────────────────────


def test_faithfulness_passes_with_caps_emphasis() -> None:
    # CAPS on a single word for emphasis is licensed by the prompt.
    original = "That sounds really tough I hear you"
    decorated = "That sounds REALLY tough I hear you"
    assert _decoration_is_faithful(original, decorated) is True


def test_faithfulness_passes_with_ellipsis_substitution() -> None:
    original = "That's a lot, walk me through it"
    decorated = "That's a lot... walk me through it"
    assert _decoration_is_faithful(original, decorated) is True


def test_faithfulness_passes_with_em_dash_substitution() -> None:
    original = "I hear you, that sounds tough"
    decorated = "I hear you — that sounds tough"
    assert _decoration_is_faithful(original, decorated) is True


def test_faithfulness_passes_with_tags_stripped() -> None:
    original = "I hear you that sounds tough"
    decorated = "[sighs] I hear you [empathetic] that sounds tough"
    assert _decoration_is_faithful(original, decorated) is True


def test_faithfulness_passes_with_break_stripped() -> None:
    original = "Let me ask you something"
    decorated = 'Let me ask you something <break time="0.5s"/>'
    assert _decoration_is_faithful(original, decorated) is True


def test_faithfulness_fails_on_word_substitution() -> None:
    original = "Walk me through the most recent time"
    decorated = "Walk me through the latest occurrence"
    assert _decoration_is_faithful(original, decorated) is False


def test_faithfulness_fails_on_added_word() -> None:
    original = "I hear you"
    decorated = "I really hear you completely"
    assert _decoration_is_faithful(original, decorated) is False


# ── JSON parser unit tests ────────────────────────────────────────────


def test_parse_returns_none_on_garbage() -> None:
    assert _parse_director_json("not json at all") is None


def test_parse_returns_none_on_empty() -> None:
    assert _parse_director_json("") is None
    assert _parse_director_json("   ") is None


def test_parse_returns_none_on_array() -> None:
    # JSON array, not object — director contract requires an object.
    assert _parse_director_json('[{"x": 1}]') is None


def test_parse_extracts_object_from_prose() -> None:
    raw = 'Some prose. {"decorated_text": "foo", "tags_used": []} and more.'
    parsed = _parse_director_json(raw)
    assert parsed == {"decorated_text": "foo", "tags_used": []}


# ── Missing API key path ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_api_key_falls_back(monkeypatch) -> None:
    # Force lazy init by clearing _client, then unset the env var.
    monkeypatch.setattr(tag_director, "_client", None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    result = await direct_tags(
        LONG_TEXT,
        phase="CONNECTION",
        user_emotion=None,
        history=[],
        allowed_tags=ALL_TAGS,
    )

    assert result.success is False
    assert result.fallback_reason is not None
    assert result.fallback_reason.startswith("client_init")
    assert result.decorated_text == LONG_TEXT
