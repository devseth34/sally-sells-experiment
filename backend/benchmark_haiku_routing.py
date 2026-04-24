"""Benchmark Haiku-routed PROBE vs Sonnet baseline on the same prompt.

Runs 3 trials per model to smooth jitter. Reports engine time and the
actual response text so we can eyeball quality. The routing helper is
imported directly so this test stays aligned with production.

Usage:
    cd backend && python benchmark_haiku_routing.py
"""

from __future__ import annotations

import asyncio
import statistics
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app.layers.response import (  # noqa: E402
    _MODEL_HAIKU,
    _MODEL_SONNET,
    SALLY_PERSONA,
    _get_async_client,
    build_response_prompt,
)
from app.models import DecisionOutput, ProspectProfile  # noqa: E402
from app.schemas import NepqPhase  # noqa: E402


PROMPTS = [
    "I work in mortgage, doing about 40 deals a month.",
    "I'm a loan officer at a regional bank.",
    "what is 100x?",
]


async def one_call(model: str, prompt: str) -> tuple[float, str]:
    decision = DecisionOutput(
        action="PROBE",
        target_phase=NepqPhase.CONNECTION.value,
        reason="benchmark",
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
        "prospect_exact_words": [prompt.lower()],
        "emotional_cues": [],
        "energy_level": "neutral",
        "emotional_tone": "curious",
        "emotional_intensity": "medium",
        "missing_criteria": ["role_shared"],
        "missing_info": [],
        "response_richness": "moderate",
    }
    built_prompt = build_response_prompt(
        decision, prompt, conversation_history, profile,
        emotional_context=emotional_context, probe_mode=True,
    )
    t0 = time.monotonic()
    response = await _get_async_client().messages.create(
        model=model,
        max_tokens=100,
        system=[{"type": "text", "text": SALLY_PERSONA, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": built_prompt}],
    )
    ms = (time.monotonic() - t0) * 1000
    text = response.content[0].text.strip()
    return ms, text


async def trial_model(model: str, label: str) -> None:
    print(f"\n=== {label}  ({model}) ===")
    all_ms: list[float] = []
    for prompt in PROMPTS:
        print(f"\n  user: {prompt}")
        timings: list[float] = []
        for i in range(3):
            ms, text = await one_call(model, prompt)
            timings.append(ms)
            all_ms.append(ms)
            print(f"    trial {i + 1}: {ms:6.0f}ms  -> {text!r}")
        p50 = statistics.median(timings)
        mean = statistics.mean(timings)
        print(f"    >>> prompt p50={p50:.0f}ms  mean={mean:.0f}ms")
    print(f"\n  ALL TRIALS: n={len(all_ms)}  p50={statistics.median(all_ms):.0f}ms  mean={statistics.mean(all_ms):.0f}ms  min={min(all_ms):.0f}ms  max={max(all_ms):.0f}ms")


async def main() -> None:
    # Warm the cache once so subsequent calls are comparable (both
    # models hit the same cache key because the system prompt is the
    # same; the first call pays the caching fee).
    print("Warming cache...", flush=True)
    await one_call(_MODEL_SONNET, "warmup")
    await one_call(_MODEL_HAIKU, "warmup")

    await trial_model(_MODEL_SONNET, "SONNET BASELINE")
    await trial_model(_MODEL_HAIKU, "HAIKU ROUTED")


if __name__ == "__main__":
    asyncio.run(main())
