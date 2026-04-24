"""Smoke test for generate_response_stream.

Exercises Claude token streaming + per-sentence circuit breaker end-
to-end without touching the full engine or the voice pipeline. Prints
each emitted sentence with a timestamp offset so the streaming effect
is visible (first-sentence first-frame should land ~1-2 s after the
Anthropic call starts, not after the full response is generated).

Usage (from repo backend/):
    python test_stream_response.py
    python test_stream_response.py --prompt "what does 100x do?"
    python test_stream_response.py --phase SITUATION --prompt "I work in mortgage"
"""

from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app.layers.response import generate_response_stream  # noqa: E402
from app.models import DecisionOutput, ProspectProfile  # noqa: E402
from app.schemas import NepqPhase  # noqa: E402


async def run(user_message: str, phase: NepqPhase) -> None:
    decision = DecisionOutput(
        action="PROBE",
        target_phase=phase.value,
        reason="stream smoke test",
        probe_target="role_shared",
    )
    profile = ProspectProfile()
    conversation_history = [
        {
            "role": "assistant",
            "content": (
                "Hey there! I'm Sally from 100x. Super curious to learn about you. "
                "What brought you here today?"
            ),
        },
    ]
    emotional_context = {
        "prospect_exact_words": [user_message.lower()],
        "emotional_cues": [],
        "energy_level": "neutral",
        "emotional_tone": "curious",
        "emotional_intensity": "medium",
        "missing_criteria": ["role_shared"],
        "missing_info": [],
        "response_richness": "moderate",
    }

    # Direct chunk-level timing first — prove the Anthropic SDK is
    # actually streaming token deltas vs returning a buffered response.
    print(f"User: {user_message}")
    print(f"Phase: {phase.value}")
    print("\n=== CHUNK-LEVEL timing (direct from AsyncAnthropic) ===")
    from app.layers.response import _get_async_client, SALLY_PERSONA, build_response_prompt
    prompt = build_response_prompt(
        decision, user_message, conversation_history, profile,
        emotional_context=emotional_context, probe_mode=True,
    )
    t_direct = time.monotonic()
    chunk_count = 0
    total_chars = 0
    async with _get_async_client().messages.stream(
        model="claude-sonnet-4-20250514",
        max_tokens=200,
        system=[{"type": "text", "text": SALLY_PERSONA, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": prompt}],
    ) as direct_stream:
        async for chunk in direct_stream.text_stream:
            elapsed = (time.monotonic() - t_direct) * 1000
            chunk_count += 1
            total_chars += len(chunk)
            print(f"  [+{elapsed:6.0f}ms]  chunk#{chunk_count:>3} ({len(chunk):>3}ch): {chunk!r}")
    print(f"  TOTAL: {chunk_count} chunks, {total_chars} chars, {(time.monotonic() - t_direct)*1000:.0f}ms\n")

    print("=== SENTENCE-LEVEL via generate_response_stream ===")
    t0 = time.monotonic()
    emitted: list[str] = []
    async for sentence in generate_response_stream(
        decision,
        user_message,
        conversation_history,
        profile,
        emotional_context=emotional_context,
        probe_mode=True,
    ):
        elapsed_ms = (time.monotonic() - t0) * 1000
        print(f"  [+{elapsed_ms:6.0f}ms]  {sentence}")
        emitted.append(sentence)
    total_ms = (time.monotonic() - t0) * 1000
    print(f"\nTotal stream duration: {total_ms:.0f}ms")
    print(f"Sentences emitted: {len(emitted)}")
    print(f"Full response: {' '.join(emitted)}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stream-response smoke test")
    ap.add_argument("--prompt", default="What is 100x and who is Nik Shah?")
    ap.add_argument(
        "--phase",
        default="CONNECTION",
        choices=[p.value for p in NepqPhase],
    )
    args = ap.parse_args()
    asyncio.run(run(args.prompt, NepqPhase(args.phase)))


if __name__ == "__main__":
    main()
