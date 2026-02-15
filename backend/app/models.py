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


class CriterionResult(BaseModel):
    """Result for a single exit criterion evaluated by Layer 1."""
    met: bool = Field(..., description="Whether this criterion has been satisfied")
    evidence: Optional[str] = Field(None, description="Specific evidence from the conversation supporting this assessment")


class PhaseExitEvaluation(BaseModel):
    """Output from Layer 1: checklist-based evaluation of phase exit criteria.

    Each criterion is a boolean check with evidence. Layer 2 counts booleans
    deterministically — no subjective confidence scores in the transition path.
    """
    criteria: dict[str, CriterionResult] = Field(
        default_factory=dict,
        description="Per-criterion boolean evaluation: {criterion_id: {met: bool, evidence: str}}"
    )
    reasoning: str = Field(..., description="Brief reasoning about overall phase progress")
    missing_info: List[str] = Field(default_factory=list, description="What still needs to be uncovered in this phase")

    @property
    def criteria_met_count(self) -> int:
        """How many criteria are currently met."""
        return sum(1 for c in self.criteria.values() if c.met)

    @property
    def criteria_total_count(self) -> int:
        """Total number of criteria being evaluated."""
        return len(self.criteria)

    @property
    def all_met(self) -> bool:
        """Whether ALL criteria are met."""
        return self.criteria_total_count > 0 and self.criteria_met_count == self.criteria_total_count

    @property
    def fraction_met(self) -> float:
        """Fraction of criteria met (0.0 to 1.0)."""
        if self.criteria_total_count == 0:
            return 0.0
        return self.criteria_met_count / self.criteria_total_count


class ComprehensionOutput(BaseModel):
    """
    Complete output from Layer 1 (Comprehension Layer).
    This is what the Analyst produces after examining each user message.
    """
    user_intent: UserIntent
    emotional_tone: str = Field(..., description="e.g. engaged, skeptical, frustrated, defensive, excited")
    emotional_intensity: str = Field(default="medium", description="low, medium, or high — how strongly they're feeling it")

    objection_type: ObjectionType = ObjectionType.NONE
    objection_detail: Optional[str] = None

    profile_updates: dict = Field(default_factory=dict, description="Key-value pairs to update on ProspectProfile")

    exit_evaluation: PhaseExitEvaluation

    # Empathy & mirroring intelligence
    prospect_exact_words: List[str] = Field(default_factory=list, description="2-3 exact phrases/sentences from the prospect worth mirroring back")
    emotional_cues: List[str] = Field(default_factory=list, description="Specific emotional signals detected: frustration, pride, excitement, anxiety, etc. with context")
    energy_level: str = Field(default="neutral", description="The prospect's conversational energy: low/flat, neutral, warm, high/excited")

    # Response quality signals
    response_richness: str = Field(default="moderate", description="thin (1-5 words, filler, vague) | moderate (real sentence, some specifics) | rich (multi-sentence, vivid detail, emotional language)")
    emotional_depth: str = Field(default="surface", description="surface (factual, no emotion) | moderate (expressed feeling) | deep (vulnerability, fear, personal stakes)")

    # Repetition detection (Feature B)
    new_information: bool = Field(default=True, description="Whether this turn contains substantive NEW information not already in the prospect profile")

    # Objection diffusion tracking
    objection_diffusion_status: str = Field(default="not_applicable", description="not_applicable | diffused | isolated | resolved | repeated")

    summary: str = Field(..., description="One-sentence summary of what happened this turn")


class DecisionOutput(BaseModel):
    """
    Output from Layer 2 (Decision Layer).
    Deterministic code produces this based on Layer 1's output.
    """
    action: str = Field(..., description="ADVANCE, STAY, PROBE, REROUTE, BREAK_GLASS, END")
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


class ConversationQualityScore(BaseModel):
    """
    Post-conversation quality evaluation (Feature C).
    Scores how well Sally performed across key dimensions.
    """
    mirroring_score: int = Field(0, ge=0, le=100, description="Did Sally mirror the extracted phrases from Layer 1?")
    mirroring_details: str = Field("", description="Specific examples of mirroring hits and misses")

    energy_matching_score: int = Field(0, ge=0, le=100, description="Did Sally's energy match the prospect's energy signals?")
    energy_matching_details: str = Field("", description="Specific examples of energy alignment or mismatch")

    structure_score: int = Field(0, ge=0, le=100, description="Did Mirror -> Validate -> Question structure hold?")
    structure_details: str = Field("", description="Per-turn assessment of structure adherence")

    emotional_arc_score: int = Field(0, ge=0, le=100, description="Was the emotional arc coherent across phases?")
    emotional_arc_details: str = Field("", description="How emotions progressed through the conversation")

    overall_score: int = Field(0, ge=0, le=100, description="Weighted overall quality score")
    recommendations: List[str] = Field(default_factory=list, description="Specific improvements for future conversations")
