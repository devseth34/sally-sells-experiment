from __future__ import annotations
"""
Sally Sells — Prospect Profile & Thought Log Models

These are the structured data models that persist across the conversation.
The ProspectProfile is Sally's "notepad" — it accumulates facts extracted
from each message so she can reference them later.

The ThoughtLog is Sally's "inner monologue" — logged for every turn
so you can debug exactly why she made each decision.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from enum import Enum


class ObjectionType(str, Enum):
    PRICE = "PRICE"
    TIMING = "TIMING"
    AUTHORITY = "AUTHORITY"
    NEED = "NEED"
    NONE = "NONE"


class UserIntent(str, Enum):
    DIRECT_ANSWER = "DIRECT_ANSWER"
    DEFLECTION = "DEFLECTION"
    QUESTION = "QUESTION"
    OBJECTION = "OBJECTION"
    SMALL_TALK = "SMALL_TALK"
    AGREEMENT = "AGREEMENT"
    PUSHBACK = "PUSHBACK"


class ProspectProfile(BaseModel):
    """
    Accumulated understanding of the prospect.
    Updated by Layer 1 (Comprehension) after every message.
    Consumed by Layer 3 (Response) to personalize Sally's replies.
    """
    # Connection phase extractions
    name: Optional[str] = None
    role: Optional[str] = None
    company: Optional[str] = None
    industry: Optional[str] = None

    # Situation phase extractions
    current_state: Optional[str] = None
    team_size: Optional[str] = None
    tools_mentioned: List[str] = Field(default_factory=list)

    # Problem Awareness extractions
    pain_points: List[str] = Field(default_factory=list)
    frustrations: List[str] = Field(default_factory=list)

    # Solution Awareness extractions
    desired_state: Optional[str] = None
    success_metrics: List[str] = Field(default_factory=list)

    # Consequence extractions
    cost_of_inaction: Optional[str] = None
    timeline_pressure: Optional[str] = None
    competitive_risk: Optional[str] = None

    # Ownership extractions
    decision_authority: Optional[str] = None
    decision_timeline: Optional[str] = None
    budget_signals: Optional[str] = None

    # Contact info (collected at close)
    email: Optional[str] = None
    phone: Optional[str] = None

    # Objection tracking
    objections_encountered: List[str] = Field(default_factory=list)
    objections_resolved: List[str] = Field(default_factory=list)


class PhaseExitEvaluation(BaseModel):
    """Output from Layer 1: how well the current phase's exit criteria are met."""
    confidence: int = Field(..., ge=0, le=100, description="0-100 confidence that exit criteria are satisfied")
    reasoning: str = Field(..., description="Why this confidence level")
    key_evidence: List[str] = Field(default_factory=list, description="Specific things the prospect said that support this score")
    missing_info: List[str] = Field(default_factory=list, description="What still needs to be uncovered in this phase")


class ComprehensionOutput(BaseModel):
    """
    Complete output from Layer 1 (Comprehension Layer).
    This is what the Analyst produces after examining each user message.
    """
    user_intent: UserIntent
    emotional_tone: str = Field(..., description="e.g. engaged, skeptical, frustrated, defensive, excited")

    objection_type: ObjectionType = ObjectionType.NONE
    objection_detail: Optional[str] = None

    profile_updates: dict = Field(default_factory=dict, description="Key-value pairs to update on ProspectProfile")

    exit_evaluation: PhaseExitEvaluation

    summary: str = Field(..., description="One-sentence summary of what happened this turn")


class DecisionOutput(BaseModel):
    """
    Output from Layer 2 (Decision Layer).
    Deterministic code produces this based on Layer 1's output.
    """
    action: str = Field(..., description="ADVANCE, STAY, REROUTE, BREAK_GLASS, END")
    target_phase: str = Field(..., description="The phase Sally should be in for her response")
    reason: str = Field(..., description="Human-readable explanation of the decision")
    objection_context: Optional[str] = None
    retry_count: int = 0


class ThoughtLog(BaseModel):
    """
    Sally's inner monologue for a single turn.
    Logged to the database for debugging and optimization.
    """
    turn_number: int
    user_message: str

    comprehension: ComprehensionOutput
    decision: DecisionOutput

    response_phase: str
    response_text: str

    profile_snapshot: dict
