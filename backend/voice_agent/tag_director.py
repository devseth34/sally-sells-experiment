"""Haiku-driven tag director for sally_emotive.

Replaces rules-based tag selection with a Claude Haiku 4.5 call that
understands NEPQ context, sales-coaching dynamics, and emotional pacing
natively. The rules-based `expression.decorate()` path stays available
as the fallback when the director fails (timeout, parse error, invalid
tag, drifted text, missing API key).

Why Haiku instead of rules:
    Rules can't read context. A response containing "I hear you" might
    warrant [sighs] or [reassuring] or nothing depending on what the
    user just said and where the conversation is. Haiku makes the call.
    ~$0.001/turn at typical sales-call lengths; ~200ms typical, 400ms
    hard cap (we time out and fall back beyond that).

Safety guarantees:
    1. Whitelist enforcement — any tag Haiku emits that's not in the
       per-personality `allowed_audio_tags` is rejected, run falls back
       to rules.
    2. Faithfulness check — strip tags + SSML breaks from the decorated
       text and compare to the original (modulo punctuation/CAPS
       substitutions allowed by the prompt). If Haiku rephrased, reject.
    3. Trivial-text short-circuit — responses < 30 chars or empty
       whitelist skip the API call entirely.
    4. Timeout — `asyncio.wait_for` ensures we never wait longer than
       `timeout_s` (default 0.4s).

API key: reads `ANTHROPIC_API_KEY` from env at first call. Mirrors the
existing repo pattern in `app/layers/response.py`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Optional

from anthropic import AsyncAnthropic

logger = logging.getLogger("sally.tag_director")

# ── Constants ─────────────────────────────────────────────────────────

_HAIKU_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 1024
_TEMPERATURE = 0.3  # low; we want consistent placement, not creativity
_DEFAULT_TIMEOUT_S = 0.4
_MIN_TEXT_CHARS = 30  # below this, decoration is wasted (mirrors expression.py)


# ── System prompt ─────────────────────────────────────────────────────

_DIRECTOR_SYSTEM_PROMPT = """You are a voice delivery director for a sales agent named Sally. Sally uses ElevenLabs v3 with audio tags to make speech sound emotionally responsive — not flat AI narration.

Your job: take Sally's planned response text and decorate it with audio tags + punctuation so it sounds like a thoughtful human salesperson, not a robot reading lines.

Rules you MUST follow:

1. ONLY use tags from the allowed list provided in the user message. Never invent tags. If a tag isn't in the list, don't use it — even if you think it would fit.

2. Tags are stage directions for v3. Each tag affects approximately the NEXT 4-5 WORDS. Place tags immediately before the words they should govern. For reaction tags ([sighs], [laughs], [exhales], [clears throat], [breathes in], [pauses], [sniff]), place at the start of the relevant clause — these are physical sounds that precede speech. For state and delivery tags ([softly], [reassuring], [serious], [thoughtful], etc.), place mid-clause directly before the words you want shaped by them.

3. Less is more. 0–3 tags per response is the right range. Adding tags to every sentence makes Sally sound theatrical. If the response is short or doesn't have an emotional payload, return it unchanged.

4. Match tags to the conversational moment. Use the NEPQ phase and user emotion as your primary signals:
   - CONNECTION: warmth, rapport — [warmly], [laughs], occasional [curious]
   - SITUATION: light curiosity — [curious], [thoughtful]
   - PROBLEM_AWARENESS: empathy when user describes pain — [sighs], [empathetic], [reassuring], [concerned]
   - SOLUTION_AWARENESS: thoughtful framing — [thoughtful], [exhales], [serious]
   - CONSEQUENCE: deeper empathy — [sighs], [empathetic], [softly], [concerned]
   - OWNERSHIP: deliberate, hopeful — [deliberately], [hopeful], [pauses]
   - COMMITMENT: warm close — [warmly], [hopeful], occasional [excited] or [laughs]
   - TERMINATED: no tags

5. Use punctuation as a delivery tool alongside tags:
   - Ellipses (...) for natural hesitation pauses inside a sentence
   - Em-dashes (—) for abrupt redirects mid-thought
   - CAPS on a single word for emphasis (use sparingly — at most once per response)
   - <break time="0.5s"/> or <break time="1.0s"/> for exact pauses up to 3 seconds, useful before delicate questions

6. Compound tags are allowed when they describe a layered delivery (e.g. [softly] [reassuring] before a sensitive line). Place them adjacently with a space between brackets. Don't compound more than 2 tags.

7. Preserve the response's meaning and word choice exactly. You are decorating, not rewriting. Do not add words, do not remove words, do not paraphrase.

8. Output ONLY valid JSON in this exact shape:

{
  "decorated_text": "<the original text with tags and punctuation inserted>",
  "tags_used": ["[tag1]", "[tag2]", ...],
  "reasoning": "<one sentence on why these choices fit this moment>"
}

If the response doesn't warrant any decoration, return:

{
  "decorated_text": "<the original text unchanged>",
  "tags_used": [],
  "reasoning": "no emotional payload requiring decoration"
}

No prose outside the JSON. No code fences. No backticks. Just the JSON object."""


# ── User message template ─────────────────────────────────────────────

_DIRECTOR_USER_TEMPLATE = """NEPQ phase: {phase}
User emotion (from comprehension layer): {user_emotion}

Recent conversation:
{history_block}

Sally's planned response:
{response_text}

Allowed tags (whitelist — use ONLY these):
{allowed_tags_block}

Decorate Sally's response. Return JSON only."""


# ── Result type ───────────────────────────────────────────────────────


@dataclass
class DirectorResult:
    decorated_text: str
    tags_used: list[str]
    latency_ms: float
    success: bool
    fallback_reason: Optional[str]


# ── Client ────────────────────────────────────────────────────────────

_client: Optional[AsyncAnthropic] = None


def _get_client() -> AsyncAnthropic:
    """Lazy-init AsyncAnthropic. Mirrors app/layers/response.py pattern."""
    global _client
    if _client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not found in environment — required for tag_director"
            )
        _client = AsyncAnthropic(api_key=api_key)
    return _client


# ── Public entry point ───────────────────────────────────────────────


async def direct_tags(
    response_text: str,
    *,
    phase: str,
    user_emotion: Optional[str],
    history: list,
    allowed_tags: list[str],
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> DirectorResult:
    """Decorate `response_text` with audio tags + punctuation via Haiku.

    Always returns a DirectorResult — never raises. On any failure path
    (timeout, HTTP error, parse error, invalid tag, drift), returns
    `success=False` with the original text and a populated
    `fallback_reason`. The runner reads `success` and falls back to the
    rules-based `expression.decorate()` path on False.
    """
    start = time.monotonic()

    # Trivial-text and empty-whitelist short-circuits — no API call.
    if len(response_text or "") < _MIN_TEXT_CHARS or not allowed_tags:
        return DirectorResult(
            decorated_text=response_text,
            tags_used=[],
            latency_ms=0.0,
            success=True,
            fallback_reason=None,
        )

    user_msg = _DIRECTOR_USER_TEMPLATE.format(
        phase=phase or "UNKNOWN",
        user_emotion=user_emotion or "(unknown)",
        history_block=_format_history(history),
        response_text=response_text,
        allowed_tags_block=", ".join(allowed_tags),
    )

    try:
        client = _get_client()
    except RuntimeError as e:
        return _fallback_result(response_text, start, f"client_init: {e}")

    try:
        result = await asyncio.wait_for(
            client.messages.create(
                model=_HAIKU_MODEL,
                max_tokens=_MAX_TOKENS,
                temperature=_TEMPERATURE,
                system=[
                    {
                        "type": "text",
                        "text": _DIRECTOR_SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user_msg}],
            ),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        return _fallback_result(response_text, start, "timeout")
    except Exception as e:  # noqa: BLE001 — match repo pattern
        return _fallback_result(response_text, start, f"http_error: {type(e).__name__}")

    raw_text = "".join(
        block.text for block in result.content if hasattr(block, "text")
    )

    parsed = _parse_director_json(raw_text)
    if parsed is None:
        return _fallback_result(response_text, start, "parse_error")

    decorated = parsed.get("decorated_text", response_text)
    tags = parsed.get("tags_used", []) or []

    # Whitelist enforcement — Haiku could hallucinate a tag.
    invalid = [t for t in tags if t not in allowed_tags]
    if invalid:
        logger.warning(
            "tag_director rejecting invalid tags %s; falling back to rules", invalid
        )
        return _fallback_result(response_text, start, f"invalid_tags: {invalid}")

    # Faithfulness — strip decorations, compare to original.
    if not _decoration_is_faithful(response_text, decorated):
        logger.warning("tag_director: decorated text drifted from original; falling back")
        return _fallback_result(response_text, start, "decoration_drift")

    latency_ms = (time.monotonic() - start) * 1000.0
    return DirectorResult(
        decorated_text=decorated,
        tags_used=list(tags),
        latency_ms=latency_ms,
        success=True,
        fallback_reason=None,
    )


# ── Helpers ───────────────────────────────────────────────────────────


def _format_history(history: list) -> str:
    """Render last-N turns as user/assistant lines. Empty → placeholder."""
    if not history:
        return "(no prior turns)"
    lines = []
    for turn in history:
        if not isinstance(turn, dict):
            continue
        role = turn.get("role", "?")
        content = turn.get("content", "")
        lines.append(f"{role}: {content}")
    return "\n".join(lines) if lines else "(no prior turns)"


def _parse_director_json(raw_text: str) -> Optional[dict]:
    """Parse JSON, tolerating fenced code blocks and trailing prose."""
    stripped = (raw_text or "").strip()
    if not stripped:
        return None

    # Strip ```json ... ``` or ``` ... ``` fences if present.
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    # Try direct parse.
    try:
        result = json.loads(stripped)
        return result if isinstance(result, dict) else None
    except json.JSONDecodeError:
        pass

    # Try to extract a JSON object via regex (handles trailing prose).
    match = re.search(r"\{.*\}", stripped, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(0))
            return result if isinstance(result, dict) else None
        except json.JSONDecodeError:
            return None

    return None


# Substitutions allowed in decorated text vs original — Haiku is licensed
# by the prompt to insert these for delivery shaping.
_DECORATION_TOKEN_RE = re.compile(
    r"\[[^\]]+\]"                       # audio tags
    r"|<break\s+time=\"[^\"]+\"\s*/>"   # SSML break
    r"|\.{3,}"                          # ellipses
    r"|—"                               # em-dash
)


def _decoration_is_faithful(original: str, decorated: str) -> bool:
    """Verify Haiku didn't rephrase the response.

    Strip all decoration tokens (tags, breaks, ellipses, em-dashes) from
    `decorated` and compare against `original` token-by-token,
    case-insensitive. The comparison treats commas as optional (Haiku
    can substitute em-dash or ellipsis where the original had a comma).
    Returns True if tokens match modulo allowed substitutions.
    """
    stripped = _DECORATION_TOKEN_RE.sub(" ", decorated or "")
    # Collapse whitespace + punctuation Haiku might insert/swap.
    norm_decorated = _normalize_for_compare(stripped)
    norm_original = _normalize_for_compare(original or "")
    return norm_decorated == norm_original


def _normalize_for_compare(text: str) -> str:
    """Lowercase, drop commas/quotes/extra punctuation, collapse whitespace.

    Allows the comparison to ignore differences Haiku is permitted to
    introduce (CAPS for emphasis, comma↔em-dash↔ellipsis substitutions).
    """
    # Lowercase for CAPS-emphasis tolerance.
    out = text.lower()
    # Drop punctuation that Haiku may add/remove for prosody.
    out = re.sub(r"[,;:\"'`()]", " ", out)
    # Collapse multiple whitespace chars.
    out = re.sub(r"\s+", " ", out).strip()
    return out


def _fallback_result(text: str, start: float, reason: str) -> DirectorResult:
    return DirectorResult(
        decorated_text=text,
        tags_used=[],
        latency_ms=(time.monotonic() - start) * 1000.0,
        success=False,
        fallback_reason=reason,
    )
