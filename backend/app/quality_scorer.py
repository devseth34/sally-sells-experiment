from __future__ import annotations
"""
Sally Sells — Post-Conversation Quality Scorer (Feature C)

Async post-conversation evaluation that scores how well Sally performed.
Runs AFTER a conversation ends (not in the hot path).

Dimensions scored:
1. Mirroring — Did Sally use the exact phrases Layer 1 extracted?
2. Energy Matching — Did Sally's energy align with prospect signals?
3. Structure — Did Mirror → Validate → Question pattern hold?
4. Emotional Arc — Was the emotional progression coherent across phases?
"""

import json
import os
import logging
from anthropic import Anthropic

# dotenv is loaded once in database.py (first import in main.py)

from app.models import ConversationQualityScore

logger = logging.getLogger("sally.quality")

# Lazy client
_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        # load_dotenv removed - database.py handles this
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not found. Set it in your .env file or environment variables.")
        _client = Anthropic(api_key=api_key)
    return _client


QUALITY_SCORER_PROMPT = """You are a conversation quality auditor for an AI sales agent named "Sally." You are given the full conversation transcript along with Sally's internal thought logs (which contain what her analyst extracted at each turn: exact phrases to mirror, emotional cues, energy levels).

Your job is to score how well Sally executed on 4 dimensions. Be SPECIFIC and EVIDENCE-BASED in your scoring.

DIMENSION 1: MIRRORING (0-100)
Did Sally actually use the prospect's exact words/phrases that her analyst flagged for mirroring?
- For each turn, check: did the thought log flag specific phrases? Did Sally's response include those exact words?
- 90-100: Sally mirrored flagged phrases in almost every response
- 70-89: Sally mirrored most flagged phrases, missed a few
- 50-69: Hit or miss, about half the time
- Below 50: Rarely used the prospect's actual words

DIMENSION 2: ENERGY MATCHING (0-100)
Did Sally's tone and energy match what the analyst detected?
- If analyst said "high/excited" → was Sally enthusiastic? Or flat?
- If analyst said "low/flat" → was Sally calm and gentle? Or annoyingly peppy?
- 90-100: Perfect energy match throughout
- 70-89: Mostly matched, a few mismatches
- 50-69: Inconsistent matching
- Below 50: Frequently mismatched

DIMENSION 3: STRUCTURE (0-100)
Did Sally follow the Mirror → Validate → Question pattern?
- Mirror: Does the response start by reflecting the prospect's words?
- Validate: Is there emotional acknowledgment before the question?
- Question: Does the response end with ONE clear question (not stacked)?
- 90-100: Clear structure in almost every response
- 70-89: Structure present in most responses
- 50-69: Structure is loose or inconsistent
- Below 50: No clear structure

DIMENSION 4: EMOTIONAL ARC (0-100)
Was the emotional progression coherent across the conversation?
- Did Sally appropriately deepen emotional engagement through the phases?
- Did the conversation feel like a natural progression, not robotic phase-jumping?
- Were phase transitions smooth (connected to what was just discussed)?
- 90-100: Beautiful emotional arc, natural progression
- 70-89: Generally coherent, minor bumps
- 50-69: Some awkward jumps or flat spots
- Below 50: Disjointed or emotionally flat

Return your assessment as a JSON object with this EXACT structure:
{
    "mirroring_score": <0-100>,
    "mirroring_details": "<specific examples of hits and misses>",
    "energy_matching_score": <0-100>,
    "energy_matching_details": "<specific examples>",
    "structure_score": <0-100>,
    "structure_details": "<per-turn notes on structure adherence>",
    "emotional_arc_score": <0-100>,
    "emotional_arc_details": "<how emotions progressed>",
    "overall_score": <0-100>,
    "recommendations": ["<specific improvement 1>", "<specific improvement 2>", ...]
}

The overall_score should be a weighted average: Mirroring 30%, Energy 20%, Structure 25%, Emotional Arc 25%.

Return ONLY the JSON object. No markdown, no explanation."""


def score_conversation(
    messages: list[dict],
    thought_logs: list[dict],
) -> ConversationQualityScore:
    """
    Score a completed conversation's quality.

    Args:
        messages: List of {role, content, phase} dicts for the full conversation
        thought_logs: List of thought log dicts from the session

    Returns:
        ConversationQualityScore with per-dimension scores and recommendations
    """

    # Build transcript
    transcript_lines = []
    for msg in messages:
        role_label = "Sally" if msg.get("role") == "assistant" else "Prospect"
        phase = msg.get("phase", "?")
        transcript_lines.append(f"[{phase}] {role_label}: {msg.get('content', '')}")
    transcript = "\n".join(transcript_lines)

    # Build thought log summary (extract key fields per turn)
    thought_summary_lines = []
    for log in thought_logs:
        turn = log.get("turn_number", "?")
        comp = log.get("comprehension", {})
        exact_words = comp.get("prospect_exact_words", [])
        emotional_cues = comp.get("emotional_cues", [])
        energy = comp.get("energy_level", "?")
        tone = comp.get("emotional_tone", "?")
        new_info = comp.get("new_information", True)
        response_text = log.get("response_text", "")

        thought_summary_lines.append(
            f"Turn {turn}:\n"
            f"  Analyst flagged phrases to mirror: {json.dumps(exact_words)}\n"
            f"  Emotional cues: {json.dumps(emotional_cues)}\n"
            f"  Energy: {energy}, Tone: {tone}, New info: {new_info}\n"
            f"  Sally said: \"{response_text[:200]}...\"\n"
        )
    thought_summary = "\n".join(thought_summary_lines)

    prompt = f"""Score this completed sales conversation.

FULL TRANSCRIPT:
{transcript}

SALLY'S INTERNAL THOUGHT LOGS (per-turn analyst extractions):
{thought_summary}

Produce the quality score JSON."""

    try:
        response = _get_client().messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1500,
            system=[{"type": "text", "text": QUALITY_SCORER_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
        )

        raw_text = response.content[0].text.strip()

        # Clean potential markdown wrapping
        if raw_text.startswith("```"):
            raw_text = raw_text.split("\n", 1)[1]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]
            raw_text = raw_text.strip()

        data = json.loads(raw_text)

        return ConversationQualityScore(
            mirroring_score=data.get("mirroring_score", 0),
            mirroring_details=data.get("mirroring_details", ""),
            energy_matching_score=data.get("energy_matching_score", 0),
            energy_matching_details=data.get("energy_matching_details", ""),
            structure_score=data.get("structure_score", 0),
            structure_details=data.get("structure_details", ""),
            emotional_arc_score=data.get("emotional_arc_score", 0),
            emotional_arc_details=data.get("emotional_arc_details", ""),
            overall_score=data.get("overall_score", 0),
            recommendations=data.get("recommendations", []),
        )

    except Exception as e:
        logger.error(f"Quality scoring failed: {e}")
        return ConversationQualityScore(
            mirroring_score=0,
            mirroring_details=f"Scoring failed: {e}",
            energy_matching_score=0,
            energy_matching_details="",
            structure_score=0,
            structure_details="",
            emotional_arc_score=0,
            emotional_arc_details="",
            overall_score=0,
            recommendations=["Quality scoring encountered an error"],
        )
