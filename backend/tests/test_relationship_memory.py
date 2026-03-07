"""
Tests for Relationship Memory Intelligence.

Covers:
- Enhanced extraction prompt (relationship_context, emotional_peaks, strategic_notes)
- Relationship memory storage (relationship, emotional_peak, strategy categories)
- Relationship memory loading (new fields returned correctly)
- Relationship memory formatting (relationship section, strategic notes, emotional peaks)
- Reconnect playbook (exists, correct properties)
- Phase skipping for returning visitors (min_turns bypass)
- Reconnect detection (detect_situation fires for returning visitor)
- Layer prompt enhancements (comprehension + response memory blocks)

Run with: cd backend && python -m pytest tests/test_relationship_memory.py -v
"""
import pytest
import os
import json
import time
import uuid

# Set env vars BEFORE any app imports
os.environ["DATABASE_URL"] = "sqlite:///test_relationship.db"
os.environ["ANTHROPIC_API_KEY"] = "test-key"
os.environ["GEMINI_API_KEY"] = "test-key"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-rel-tests"
os.environ["SKIP_SCHEMA_CHECK"] = "true"

from unittest.mock import patch, MagicMock


# ===========================================================================
#  Enhanced Extraction Prompt Tests
# ===========================================================================

class TestEnhancedExtraction:
    """Test that the extraction prompt requests relationship intelligence."""

    def test_extraction_prompt_contains_relationship_context(self):
        """EXTRACTION_PROMPT should include relationship_context fields."""
        from app.memory import EXTRACTION_PROMPT
        assert "relationship_context" in EXTRACTION_PROMPT
        assert "rapport_level" in EXTRACTION_PROMPT
        assert "trust_signals" in EXTRACTION_PROMPT
        assert "humor_moments" in EXTRACTION_PROMPT
        assert "their_language_style" in EXTRACTION_PROMPT
        assert "energy_pattern" in EXTRACTION_PROMPT

    def test_extraction_prompt_contains_emotional_peaks(self):
        """EXTRACTION_PROMPT should include emotional_peaks structure."""
        from app.memory import EXTRACTION_PROMPT
        assert "emotional_peaks" in EXTRACTION_PROMPT
        assert "their_words" in EXTRACTION_PROMPT

    def test_extraction_prompt_contains_strategic_notes(self):
        """EXTRACTION_PROMPT should include strategic_notes fields."""
        from app.memory import EXTRACTION_PROMPT
        assert "strategic_notes" in EXTRACTION_PROMPT
        assert "what_worked" in EXTRACTION_PROMPT
        assert "what_didnt_work" in EXTRACTION_PROMPT
        assert "unfinished_threads" in EXTRACTION_PROMPT
        assert "next_session_strategy" in EXTRACTION_PROMPT
        assert "objection_vulnerability" in EXTRACTION_PROMPT

    def test_extraction_prompt_briefing_friend_tone(self):
        """EXTRACTION_PROMPT should use the 'briefing a friend' framing."""
        from app.memory import EXTRACTION_PROMPT
        assert "friend" in EXTRACTION_PROMPT.lower()


# ===========================================================================
#  Relationship Memory Storage Tests
# ===========================================================================

class TestRelationshipMemoryStorage:
    """Test storing relationship intelligence in the database."""

    @pytest.fixture
    def db_setup(self):
        """Set up a SQLite DB for testing."""
        import app.database as db_module
        db_module.DATABASE_URL = "sqlite:///test_relationship.db"
        db_module._engine = None
        db_module._SessionLocal = None

        from app.database import Base, _get_engine, _get_session_local
        engine = _get_engine()
        Base.metadata.create_all(bind=engine)
        session_maker = _get_session_local()

        yield session_maker

        Base.metadata.drop_all(bind=engine)
        db_module._engine = None
        db_module._SessionLocal = None
        try:
            os.remove("test_relationship.db")
        except OSError:
            pass

    def _full_extraction(self):
        """Helper: return a full extraction dict with all relationship fields."""
        return {
            "identity": {"name": "Alex", "role": "VP Sales", "company": "TechCorp", "industry": "SaaS"},
            "situation": {
                "team_size": "12",
                "tools_mentioned": ["Apollo", "Salesforce"],
                "workflow_description": "outbound sales",
                "desired_state": "automate follow-ups",
            },
            "pain_points": ["manual follow-ups waste 10hrs/week", "team morale dropping"],
            "objection_history": ["PRICE: said $10k is too much for their budget"],
            "relationship_context": {
                "rapport_level": "warm",
                "trust_signals": ["admitted they felt overwhelmed managing 3 people"],
                "resistance_signals": ["deflected when asked about budget"],
                "personal_details": ["just moved to Austin", "has two kids"],
                "humor_moments": ["joked about their CRM being held together with duct tape"],
                "their_language_style": "casual, uses humor, short answers",
                "energy_pattern": "started low but warmed up significantly",
            },
            "emotional_peaks": [
                {
                    "moment": "discussing team burnout",
                    "emotion": "frustrated",
                    "their_words": "I can't keep asking my team to do more with less",
                    "phase": "PROBLEM_AWARENESS",
                },
                {
                    "moment": "hearing about automation possibilities",
                    "emotion": "excited",
                    "their_words": "wait, so it could actually handle the follow-up emails?",
                    "phase": "SOLUTION_AWARENESS",
                },
            ],
            "strategic_notes": {
                "what_worked": "asking about team impact got them emotional and engaged",
                "what_didnt_work": "talking about ROI numbers — they glazed over",
                "unfinished_threads": ["wanted to discuss invoicing automation", "mentioned a board meeting next month"],
                "next_session_strategy": "Start by asking about the board meeting. They were close — lead with team impact, not ROI.",
                "objection_vulnerability": "price objection was soft — they acknowledged the ROI but said timing was bad",
            },
            "session_summary": "Alex runs sales at TechCorp. He's drowning in manual follow-ups and knows AI could help but balked at $10k.",
            "conversation_outcome": "abandoned_late",
            "final_phase": "OWNERSHIP",
        }

    def test_store_relationship_context(self, db_setup):
        """Relationship context fields should be stored as memory facts."""
        from app.memory import store_memory, load_visitor_memory

        visitor_id = str(uuid.uuid4())
        store_memory(db_setup, "SESSION-1", visitor_id, self._full_extraction())

        db = db_setup()
        try:
            memory = load_visitor_memory(db, visitor_id)
            assert memory["has_memory"] is True
            rel = memory.get("relationship", {})
            assert rel.get("rapport_level") == "warm"
            assert rel.get("their_language_style") == "casual, uses humor, short answers"
            assert rel.get("energy_pattern") == "started low but warmed up significantly"
            assert len(rel.get("trust_signals", [])) >= 1
            assert len(rel.get("personal_details", [])) >= 2
            assert len(rel.get("humor_moments", [])) >= 1
            assert len(rel.get("resistance_signals", [])) >= 1
        finally:
            db.close()

    def test_store_emotional_peaks(self, db_setup):
        """Emotional peaks should be stored and loaded as structured dicts."""
        from app.memory import store_memory, load_visitor_memory

        visitor_id = str(uuid.uuid4())
        store_memory(db_setup, "SESSION-1", visitor_id, self._full_extraction())

        db = db_setup()
        try:
            memory = load_visitor_memory(db, visitor_id)
            peaks = memory.get("emotional_peaks", [])
            assert len(peaks) == 2
            assert peaks[0]["emotion"] in ("frustrated", "excited")
            assert "their_words" in peaks[0]
        finally:
            db.close()

    def test_store_strategic_notes(self, db_setup):
        """Strategic notes should be stored and loaded correctly."""
        from app.memory import store_memory, load_visitor_memory

        visitor_id = str(uuid.uuid4())
        store_memory(db_setup, "SESSION-1", visitor_id, self._full_extraction())

        db = db_setup()
        try:
            memory = load_visitor_memory(db, visitor_id)
            strat = memory.get("strategic_notes", {})
            assert "what_worked" in strat
            assert "what_didnt_work" in strat
            assert "next_session_strategy" in strat
            assert "objection_vulnerability" in strat

            threads = memory.get("unfinished_threads", [])
            assert len(threads) >= 2
            assert any("invoicing" in t for t in threads)
        finally:
            db.close()

    def test_store_desired_state_from_situation(self, db_setup):
        """desired_state should be read from inside situation object."""
        from app.memory import store_memory, load_visitor_memory

        visitor_id = str(uuid.uuid4())
        store_memory(db_setup, "SESSION-1", visitor_id, self._full_extraction())

        db = db_setup()
        try:
            memory = load_visitor_memory(db, visitor_id)
            assert memory["situation"].get("desired_state") == "automate follow-ups"
        finally:
            db.close()


# ===========================================================================
#  Relationship Memory Loading Tests
# ===========================================================================

class TestRelationshipMemoryLoading:
    """Test loading relationship memory returns new fields."""

    @pytest.fixture
    def db_setup(self):
        import app.database as db_module
        db_module.DATABASE_URL = "sqlite:///test_relationship.db"
        db_module._engine = None
        db_module._SessionLocal = None

        from app.database import Base, _get_engine, _get_session_local
        engine = _get_engine()
        Base.metadata.create_all(bind=engine)
        session_maker = _get_session_local()

        yield session_maker

        Base.metadata.drop_all(bind=engine)
        db_module._engine = None
        db_module._SessionLocal = None
        try:
            os.remove("test_relationship.db")
        except OSError:
            pass

    def test_empty_memory_has_graceful_defaults(self, db_setup):
        """Loading memory for unknown visitor returns has_memory=False."""
        from app.memory import load_visitor_memory
        db = db_setup()
        try:
            memory = load_visitor_memory(db, "nonexistent-visitor")
            assert memory["has_memory"] is False
        finally:
            db.close()

    def test_old_extraction_without_new_fields(self, db_setup):
        """Old-style extraction (no relationship fields) should still load gracefully."""
        from app.memory import store_memory, load_visitor_memory

        visitor_id = str(uuid.uuid4())
        old_extraction = {
            "identity": {"name": "OldBob", "role": "Manager"},
            "situation": {"team_size": "5"},
            "pain_points": ["slow processes"],
            "objection_history": [],
            "emotional_signals": ["seemed interested"],
            "session_summary": "Bob is a manager dealing with slow processes.",
            "conversation_outcome": "abandoned_early",
            "final_phase": "SITUATION",
        }

        store_memory(db_setup, "SESSION-OLD", visitor_id, old_extraction)

        db = db_setup()
        try:
            memory = load_visitor_memory(db, visitor_id)
            assert memory["has_memory"] is True
            assert memory["identity"]["name"] == "OldBob"
            # New fields should be empty but present
            assert memory.get("relationship") == {}
            assert memory.get("emotional_peaks") == []
            assert memory.get("strategic_notes") == {}
            assert memory.get("unfinished_threads") == []
        finally:
            db.close()


# ===========================================================================
#  Relationship Memory Formatting Tests
# ===========================================================================

class TestRelationshipMemoryFormatting:
    """Test the prompt formatting includes relationship intelligence."""

    def test_format_includes_relationship_section(self):
        """format_memory_for_prompt should include relationship details."""
        from app.memory import format_memory_for_prompt
        memory = {
            "has_memory": True,
            "total_prior_sessions": 2,
            "identity": {"name": "Alex", "role": "VP Sales"},
            "situation": {},
            "pain_points": ["manual follow-ups"],
            "objection_history": [],
            "emotional_signals": [],
            "relationship": {
                "rapport_level": "warm",
                "their_language_style": "casual, uses humor",
                "energy_pattern": "started low, warmed up",
                "personal_details": ["just moved to Austin"],
                "humor_moments": ["joked about CRM"],
                "trust_signals": ["admitted feeling overwhelmed"],
            },
            "emotional_peaks": [],
            "strategic_notes": {},
            "unfinished_threads": [],
            "session_summaries": [],
        }
        result = format_memory_for_prompt(memory)
        assert "YOUR RELATIONSHIP WITH THEM" in result
        assert "warm" in result
        assert "casual, uses humor" in result
        assert "Austin" in result
        assert "joked about CRM" in result

    def test_format_includes_emotional_peaks(self):
        """format_memory_for_prompt should include emotional peaks."""
        from app.memory import format_memory_for_prompt
        memory = {
            "has_memory": True,
            "total_prior_sessions": 1,
            "identity": {"name": "Alex"},
            "situation": {},
            "pain_points": [],
            "objection_history": [],
            "emotional_signals": [],
            "relationship": {},
            "emotional_peaks": [
                {
                    "moment": "discussing burnout",
                    "emotion": "frustrated",
                    "their_words": "I can't keep doing this",
                },
            ],
            "strategic_notes": {},
            "unfinished_threads": [],
            "session_summaries": [],
        }
        result = format_memory_for_prompt(memory)
        assert "EMOTIONAL MOMENTS" in result
        assert "discussing burnout" in result
        assert "frustrated" in result

    def test_format_includes_strategic_notes(self):
        """format_memory_for_prompt should include strategic intelligence."""
        from app.memory import format_memory_for_prompt
        memory = {
            "has_memory": True,
            "total_prior_sessions": 1,
            "identity": {"name": "Alex"},
            "situation": {},
            "pain_points": [],
            "objection_history": [],
            "emotional_signals": [],
            "relationship": {},
            "emotional_peaks": [],
            "strategic_notes": {
                "what_worked": "asking about team impact",
                "what_didnt_work": "talking about ROI numbers",
                "next_session_strategy": "Start by asking about the board meeting",
                "objection_vulnerability": "price objection was soft",
            },
            "unfinished_threads": ["invoicing automation"],
            "session_summaries": [],
        }
        result = format_memory_for_prompt(memory)
        assert "STRATEGIC INTELLIGENCE" in result
        assert "asking about team impact" in result
        assert "RECOMMENDED APPROACH" in result
        assert "invoicing automation" in result

    def test_format_closing_instruction(self):
        """format_memory_for_prompt should end with the 'friend' instruction."""
        from app.memory import format_memory_for_prompt
        memory = {
            "has_memory": True,
            "total_prior_sessions": 1,
            "identity": {"name": "Alex"},
            "situation": {},
            "pain_points": [],
            "objection_history": [],
            "emotional_signals": [],
            "relationship": {},
            "emotional_peaks": [],
            "strategic_notes": {},
            "unfinished_threads": [],
            "session_summaries": [],
        }
        result = format_memory_for_prompt(memory)
        assert "KNOW this person" in result
        assert "friend" in result.lower()

    def test_format_empty_memory_returns_empty(self):
        """No memory should return empty string."""
        from app.memory import format_memory_for_prompt
        assert format_memory_for_prompt({"has_memory": False}) == ""

    def test_format_you_know_this_person_header(self):
        """Header should say 'YOU KNOW THIS PERSON'."""
        from app.memory import format_memory_for_prompt
        memory = {
            "has_memory": True,
            "total_prior_sessions": 3,
            "identity": {"name": "Alex"},
            "situation": {},
            "pain_points": [],
            "objection_history": [],
            "emotional_signals": [],
            "relationship": {},
            "emotional_peaks": [],
            "strategic_notes": {},
            "unfinished_threads": [],
            "session_summaries": [],
        }
        result = format_memory_for_prompt(memory)
        assert "YOU KNOW THIS PERSON" in result
        assert "3 time(s)" in result


# ===========================================================================
#  Reconnect Playbook Tests
# ===========================================================================

class TestReconnectPlaybook:
    """Test the relationship_reconnect playbook."""

    def test_playbook_exists(self):
        """relationship_reconnect should be in PLAYBOOKS dict."""
        from app.playbooks import PLAYBOOKS
        assert "relationship_reconnect" in PLAYBOOKS

    def test_playbook_properties(self):
        """Playbook should have correct max_consecutive_uses and overrides_action."""
        from app.playbooks import PLAYBOOKS
        pb = PLAYBOOKS["relationship_reconnect"]
        assert pb["max_consecutive_uses"] == 1
        assert pb["overrides_action"] is True

    def test_playbook_instruction_content(self):
        """Playbook instruction should guide warm reconnection."""
        from app.playbooks import PLAYBOOKS
        instruction = PLAYBOOKS["relationship_reconnect"]["instruction"]
        assert "reconnect" in instruction.lower() or "RETURNING" in instruction
        # Should NOT encourage listing everything you remember
        assert "list out everything" in instruction.lower() or "DO NOT" in instruction


# ===========================================================================
#  Phase Skipping Tests
# ===========================================================================

class TestPhaseSkipping:
    """Test that returning visitors can bypass min_turns in early phases."""

    def _make_comprehension(self, all_met=False):
        """Helper: build a minimal ComprehensionOutput with proper model types."""
        from app.models import ComprehensionOutput, PhaseExitEvaluation, CriterionResult, UserIntent, ObjectionType

        criteria = {
            "test_1": CriterionResult(met=all_met, evidence="test evidence" if all_met else None),
            "test_2": CriterionResult(met=all_met, evidence="test evidence" if all_met else None),
            "test_3": CriterionResult(met=all_met, evidence="test evidence" if all_met else None),
        }

        exit_eval = PhaseExitEvaluation(
            criteria=criteria,
            reasoning="All met" if all_met else "Not all met",
            missing_info=[] if all_met else ["test_1", "test_2"],
        )

        return ComprehensionOutput(
            user_intent=UserIntent.DIRECT_ANSWER,
            emotional_tone="engaged",
            emotional_intensity="medium",
            objection_type=ObjectionType.NONE,
            exit_evaluation=exit_eval,
            response_richness="moderate",
            emotional_depth="surface",
            summary="Test comprehension output",
        )

    def _make_profile(self):
        """Helper: build a minimal ProspectProfile."""
        from app.models import ProspectProfile
        return ProspectProfile()

    def test_min_turns_bypassed_for_returning_visitor_connection(self):
        """Returning visitor in CONNECTION should bypass min_turns check."""
        from app.layers.decision import make_decision
        from app.schemas import NepqPhase

        comp = self._make_comprehension(all_met=True)
        profile = self._make_profile()

        result = make_decision(
            current_phase=NepqPhase.CONNECTION,
            comprehension=comp,
            profile=profile,
            retry_count=0,
            conversation_turn=1,
            conversation_start_time=time.time(),
            turns_in_current_phase=0,  # Below min_turns
            memory_context="YOU KNOW THIS PERSON — you've chatted 2 time(s) before.",
        )
        # Should NOT be held by min_turns — should advance or proceed to exit criteria
        assert "Minimum turns not reached" not in result.reason

    def test_min_turns_enforced_for_new_visitor(self):
        """New visitor (no memory_context) in CONNECTION should be held by min_turns."""
        from app.layers.decision import make_decision
        from app.schemas import NepqPhase

        comp = self._make_comprehension(all_met=True)
        profile = self._make_profile()

        result = make_decision(
            current_phase=NepqPhase.CONNECTION,
            comprehension=comp,
            profile=profile,
            retry_count=0,
            conversation_turn=1,
            conversation_start_time=time.time(),
            turns_in_current_phase=0,  # Below min_turns
            memory_context="",  # No memory
        )
        # Should be held by min_turns
        assert "Minimum turns not reached" in result.reason

    def test_min_turns_enforced_for_returning_visitor_late_phase(self):
        """Returning visitor in CONSEQUENCE should still be held by min_turns."""
        from app.layers.decision import make_decision
        from app.schemas import NepqPhase

        comp = self._make_comprehension(all_met=False)
        profile = self._make_profile()

        result = make_decision(
            current_phase=NepqPhase.CONSEQUENCE,
            comprehension=comp,
            profile=profile,
            retry_count=0,
            conversation_turn=5,
            conversation_start_time=time.time(),
            turns_in_current_phase=0,  # Below min_turns
            memory_context="YOU KNOW THIS PERSON — you've chatted 2 time(s) before.",
        )
        # Late phases should still enforce min_turns even for returning visitors
        assert "Minimum turns not reached" in result.reason


# ===========================================================================
#  Reconnect Detection Tests
# ===========================================================================

class TestReconnectDetection:
    """Test that detect_situation fires relationship_reconnect for returning visitors."""

    def _make_exit_eval(self):
        """Helper: build a minimal PhaseExitEvaluation."""
        from app.models import PhaseExitEvaluation
        return PhaseExitEvaluation(
            criteria={},
            reasoning="No criteria evaluated yet",
            missing_info=[],
        )

    def _make_comprehension(self, intent="DIRECT_ANSWER", tone="engaged", intensity="medium"):
        """Helper: build a minimal ComprehensionOutput."""
        from app.models import ComprehensionOutput, UserIntent, ObjectionType
        return ComprehensionOutput(
            user_intent=UserIntent(intent),
            emotional_tone=tone,
            emotional_intensity=intensity,
            objection_type=ObjectionType.NONE,
            exit_evaluation=self._make_exit_eval(),
            response_richness="moderate",
            emotional_depth="surface",
            summary="Test comprehension output",
        )

    def test_reconnect_fires_for_returning_visitor_first_turn(self):
        """detect_situation should return 'relationship_reconnect' on first turn with memory."""
        from app.layers.decision import detect_situation
        from app.schemas import NepqPhase
        from app.models import DecisionOutput, ProspectProfile

        comp = self._make_comprehension()
        decision = DecisionOutput(
            action="STAY",
            target_phase="CONNECTION",
            reason="Min turns",
            retry_count=0,
        )
        profile = ProspectProfile()

        result = detect_situation(
            comprehension=comp,
            decision=decision,
            current_phase=NepqPhase.CONNECTION,
            profile=profile,
            turns_in_current_phase=1,
            memory_context="YOU KNOW THIS PERSON",
        )
        assert result == "relationship_reconnect"

    def test_reconnect_does_not_fire_without_memory(self):
        """detect_situation should NOT fire reconnect for new visitors."""
        from app.layers.decision import detect_situation
        from app.schemas import NepqPhase
        from app.models import DecisionOutput, ProspectProfile

        comp = self._make_comprehension(tone="neutral", intensity="low")
        decision = DecisionOutput(
            action="STAY",
            target_phase="CONNECTION",
            reason="Min turns",
            retry_count=0,
        )
        profile = ProspectProfile()

        result = detect_situation(
            comprehension=comp,
            decision=decision,
            current_phase=NepqPhase.CONNECTION,
            profile=profile,
            turns_in_current_phase=1,
            memory_context="",  # No memory
        )
        assert result != "relationship_reconnect"

    def test_reconnect_does_not_fire_in_later_phases(self):
        """detect_situation should NOT fire reconnect outside CONNECTION."""
        from app.layers.decision import detect_situation
        from app.schemas import NepqPhase
        from app.models import DecisionOutput, ProspectProfile

        comp = self._make_comprehension()
        decision = DecisionOutput(
            action="STAY",
            target_phase="SITUATION",
            reason="ongoing",
            retry_count=0,
        )
        profile = ProspectProfile()

        result = detect_situation(
            comprehension=comp,
            decision=decision,
            current_phase=NepqPhase.SITUATION,
            profile=profile,
            turns_in_current_phase=1,
            memory_context="YOU KNOW THIS PERSON",
        )
        assert result != "relationship_reconnect"


# ===========================================================================
#  Layer Prompt Enhancement Tests
# ===========================================================================

class TestLayerPromptEnhancements:
    """Test that comprehension and response prompts contain relationship-aware instructions."""

    def test_comprehension_prompt_has_emotional_continuity(self):
        """Layer 1 memory injection should mention emotional continuity."""
        import inspect
        from app.layers.comprehension import build_comprehension_prompt
        source = inspect.getsource(build_comprehension_prompt)
        assert "EMOTIONAL CONTINUITY" in source

    def test_comprehension_prompt_has_profile_update_rules(self):
        """Layer 1 memory injection should mention profile update rules."""
        import inspect
        from app.layers.comprehension import build_comprehension_prompt
        source = inspect.getsource(build_comprehension_prompt)
        assert "PROFILE UPDATES" in source

    def test_response_prompt_has_relationship_instructions(self):
        """Layer 3 memory injection should have relationship-aware instructions."""
        import inspect
        from app.layers.response import build_response_prompt
        source = inspect.getsource(build_response_prompt)
        assert "RETURNING VISITOR" in source
        assert "KNOWS this person" in source or "KNOW this person" in source

    def test_response_prompt_has_do_dont_guidance(self):
        """Layer 3 memory injection should include DO/DON'T guidance."""
        import inspect
        from app.layers.response import build_response_prompt
        source = inspect.getsource(build_response_prompt)
        assert "DO NOT" in source or "DO:" in source
