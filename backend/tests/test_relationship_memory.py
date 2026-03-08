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


# ===========================================================================
#  Session Count Alias Tests
# ===========================================================================

class TestSessionCountAlias:
    """Test that load_visitor_memory returns session_count alias."""

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

    def test_session_count_alias_exists(self, db_setup):
        """load_visitor_memory should return both session_count and total_prior_sessions."""
        from app.memory import store_memory, load_visitor_memory

        visitor_id = str(uuid.uuid4())
        extraction = {
            "identity": {"name": "Alex"},
            "situation": {},
            "pain_points": [],
            "objection_history": [],
            "session_summary": "First chat with Alex.",
            "conversation_outcome": "completed_free",
            "final_phase": "COMMITMENT",
        }
        store_memory(db_setup, "SESSION-1", visitor_id, extraction)

        db = db_setup()
        try:
            memory = load_visitor_memory(db, visitor_id)
            assert "session_count" in memory
            assert "total_prior_sessions" in memory
            assert memory["session_count"] == memory["total_prior_sessions"]
            assert memory["session_count"] == 1
        finally:
            db.close()

    def test_session_count_increments(self, db_setup):
        """session_count should increase with each stored session."""
        from app.memory import store_memory, load_visitor_memory

        visitor_id = str(uuid.uuid4())
        for i in range(3):
            extraction = {
                "identity": {"name": "Alex"},
                "situation": {},
                "pain_points": [],
                "objection_history": [],
                "session_summary": f"Chat #{i+1}",
                "conversation_outcome": "completed_free",
                "final_phase": "COMMITMENT",
            }
            store_memory(db_setup, f"SESSION-{i+1}", visitor_id, extraction)

        db = db_setup()
        try:
            memory = load_visitor_memory(db, visitor_id)
            assert memory["session_count"] == 3
        finally:
            db.close()


# ===========================================================================
#  Recent Conversation Context Tests
# ===========================================================================

class TestRecentConversationContext:
    """Test loading actual messages from prior sessions."""

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

    def _create_session_with_messages(self, db, visitor_id, session_id, messages, status="completed"):
        """Helper: create a DBSession with messages."""
        from app.database import DBSession, DBMessage
        now = time.time()

        db_session = DBSession(
            id=session_id,
            status=status,
            current_phase="SITUATION",
            start_time=now - 600,
            end_time=now,
            visitor_id=visitor_id,
            assigned_arm="sally_nepq",
        )
        db.add(db_session)

        for i, (role, content) in enumerate(messages):
            db.add(DBMessage(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role=role,
                content=content,
                timestamp=now - 600 + i * 10,
                phase="CONNECTION",
            ))
        db.commit()

    def test_empty_for_new_visitor(self, db_setup):
        """Should return empty string for visitor with no prior sessions."""
        from app.memory import load_recent_conversation_context
        db = db_setup()
        try:
            result = load_recent_conversation_context(db, "nonexistent-visitor")
            assert result == ""
        finally:
            db.close()

    def test_loads_messages_from_completed_session(self, db_setup):
        """Should return formatted messages from the most recent completed session."""
        from app.memory import load_recent_conversation_context
        db = db_setup()
        try:
            visitor_id = str(uuid.uuid4())
            self._create_session_with_messages(db, visitor_id, "SESS-1", [
                ("assistant", "Hey there! I'm Sally."),
                ("user", "Hi, I'm Dev, a software engineer."),
                ("assistant", "Nice to meet you, Dev!"),
            ])

            result = load_recent_conversation_context(db, visitor_id)
            assert "LAST CONVERSATION" in result
            assert "Sally: Hey there! I'm Sally." in result
            assert "Prospect: Hi, I'm Dev, a software engineer." in result
            assert "Sally: Nice to meet you, Dev!" in result
        finally:
            db.close()

    def test_respects_message_limit(self, db_setup):
        """Should only include the last 20 messages."""
        from app.memory import load_recent_conversation_context
        db = db_setup()
        try:
            visitor_id = str(uuid.uuid4())
            messages = []
            for i in range(30):
                role = "assistant" if i % 2 == 0 else "user"
                messages.append((role, f"Message {i}"))
            self._create_session_with_messages(db, visitor_id, "SESS-1", messages)

            result = load_recent_conversation_context(db, visitor_id)
            # Should NOT include early messages (0-9), only 10-29
            assert "Message 0" not in result
            assert "Message 29" in result
            assert "Message 10" in result
        finally:
            db.close()

    def test_includes_session_outcome(self, db_setup):
        """Should include session outcome in the header."""
        from app.memory import load_recent_conversation_context
        db = db_setup()
        try:
            visitor_id = str(uuid.uuid4())
            self._create_session_with_messages(db, visitor_id, "SESS-1", [
                ("assistant", "Hello!"),
                ("user", "Hi!"),
            ], status="abandoned")

            result = load_recent_conversation_context(db, visitor_id)
            assert "abandoned" in result
        finally:
            db.close()

    def test_falls_back_to_active_sessions(self, db_setup):
        """Should fall back to active sessions when no completed/abandoned sessions exist."""
        from app.memory import load_recent_conversation_context
        db = db_setup()
        try:
            visitor_id = str(uuid.uuid4())
            self._create_session_with_messages(db, visitor_id, "SESS-1", [
                ("assistant", "Hello!"),
                ("user", "Hi!"),
            ], status="active")

            result = load_recent_conversation_context(db, visitor_id)
            # Should find the active session as fallback
            assert "Hello!" in result
            assert "Hi!" in result
        finally:
            db.close()


# ===========================================================================
#  Enriched Profile Seeding Tests
# ===========================================================================

class TestEnrichedProfileSeeding:
    """Test that _seed_profile_from_memory includes all relevant fields."""

    def test_seeds_all_situation_fields(self):
        """Should seed desired_state, workflow_description from situation."""
        from app.main import _seed_profile_from_memory
        memory = {
            "has_memory": True,
            "identity": {"name": "Dev", "role": "Engineer", "company": "Acme", "industry": "Tech"},
            "situation": {
                "team_size": "5",
                "tools_mentioned": ["Python", "Docker"],
                "workflow_description": "CI/CD pipeline management",
                "desired_state": "automate deployments",
            },
            "pain_points": ["manual deployments take too long"],
            "objection_history": [],
        }
        result = json.loads(_seed_profile_from_memory(memory))
        assert result["name"] == "Dev"
        assert result["desired_state"] == "automate deployments"
        assert result["workflow_description"] == "CI/CD pipeline management"
        assert result["tools_mentioned"] == ["Python", "Docker"]

    def test_seeds_frustrations_from_pain_points(self):
        """Should seed pain_points into both pain_points and frustrations."""
        from app.main import _seed_profile_from_memory
        memory = {
            "has_memory": True,
            "identity": {"name": "Dev"},
            "situation": {},
            "pain_points": ["slow builds", "flaky tests"],
            "objection_history": [],
        }
        result = json.loads(_seed_profile_from_memory(memory))
        assert result["pain_points"] == ["slow builds", "flaky tests"]
        assert result["frustrations"] == ["slow builds", "flaky tests"]

    def test_seeds_objection_history(self):
        """Should seed objection_history when present."""
        from app.main import _seed_profile_from_memory
        memory = {
            "has_memory": True,
            "identity": {"name": "Dev"},
            "situation": {},
            "pain_points": [],
            "objection_history": ["PRICE: too expensive for a startup"],
        }
        result = json.loads(_seed_profile_from_memory(memory))
        assert result["objection_history"] == ["PRICE: too expensive for a startup"]

    def test_empty_memory_returns_empty_json(self):
        """Should return '{}' for no memory."""
        from app.main import _seed_profile_from_memory
        result = _seed_profile_from_memory({"has_memory": False})
        assert result == "{}"


# ===========================================================================
#  Greeting Robustness Tests
# ===========================================================================

class TestRecentContextActiveFallback:
    """Test that load_recent_conversation_context falls back to active sessions."""

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

    def _create_session_with_messages(self, db, visitor_id, session_id, messages, status="active"):
        """Helper: create a DBSession with messages."""
        from app.database import DBSession, DBMessage
        now = time.time()

        db_session = DBSession(
            id=session_id,
            status=status,
            current_phase="SITUATION",
            start_time=now - 600,
            end_time=now if status != "active" else None,
            visitor_id=visitor_id,
            assigned_arm="sally_nepq",
        )
        db.add(db_session)

        for i, (role, content) in enumerate(messages):
            db.add(DBMessage(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role=role,
                content=content,
                timestamp=now - 600 + i * 10,
                phase="CONNECTION",
            ))
        db.commit()

    def test_loads_from_active_session_when_no_ended_exists(self, db_setup):
        """Should fall back to active session messages when no completed/abandoned session exists."""
        from app.memory import load_recent_conversation_context
        db = db_setup()
        try:
            visitor_id = str(uuid.uuid4())
            self._create_session_with_messages(db, visitor_id, "SESS-ACTIVE", [
                ("assistant", "Hey! I'm Sally."),
                ("user", "Hey, I'm dev."),
            ], status="active")

            result = load_recent_conversation_context(db, visitor_id)
            assert "Sally: Hey! I'm Sally." in result
            assert "Prospect: Hey, I'm dev." in result
        finally:
            db.close()

    def test_prefers_ended_session_over_active(self, db_setup):
        """Should prefer completed/abandoned sessions over active ones."""
        from app.memory import load_recent_conversation_context
        db = db_setup()
        try:
            visitor_id = str(uuid.uuid4())
            # Create an active session
            self._create_session_with_messages(db, visitor_id, "SESS-ACTIVE", [
                ("assistant", "Active greeting"),
                ("user", "Active reply"),
            ], status="active")
            # Create a completed session
            self._create_session_with_messages(db, visitor_id, "SESS-DONE", [
                ("assistant", "Completed greeting"),
                ("user", "Completed reply"),
            ], status="completed")

            result = load_recent_conversation_context(db, visitor_id)
            assert "Completed greeting" in result
            assert "Active greeting" not in result
        finally:
            db.close()


class TestProfileFallback:
    """Test fallback to prospect_profile when memory_facts haven't been extracted yet."""

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

    def test_fallback_builds_memory_from_profile(self, db_setup):
        """When no memory_facts exist, should build memory from last session's prospect_profile."""
        from app.database import DBSession
        db = db_setup()
        try:
            now = time.time()
            # Create a completed session with a prospect profile but NO memory_facts
            db.add(DBSession(
                id="PREV-SESS",
                status="completed",
                current_phase="COMMITMENT",
                start_time=now - 600,
                end_time=now - 60,
                visitor_id="vis-test",
                assigned_arm="sally_nepq",
                prospect_profile=json.dumps({
                    "name": "Dev",
                    "role": "Engineer",
                    "company": "Acme",
                    "pain_points": ["slow builds"],
                }),
            ))
            db.commit()

            # Load memory — no facts exist
            from app.memory import load_visitor_memory
            memory = load_visitor_memory(db, "vis-test")
            assert memory.get("has_memory") is False  # No memory_facts or summaries

            # Now simulate what create_session does: check for fallback
            from sqlalchemy import or_ as _or
            prev = (
                db.query(DBSession)
                .filter(
                    DBSession.visitor_id == "vis-test",
                    DBSession.status.in_(["completed", "abandoned"]),
                )
                .order_by(DBSession.end_time.desc())
                .first()
            )
            assert prev is not None
            profile_data = json.loads(prev.prospect_profile)
            assert profile_data["name"] == "Dev"
            assert profile_data["pain_points"] == ["slow builds"]
        finally:
            db.close()

    def test_fallback_also_checks_active_sessions(self, db_setup):
        """When no ended sessions exist, fallback should check active sessions with profiles."""
        from app.database import DBSession
        db = db_setup()
        try:
            now = time.time()
            # Create an active session with a populated profile
            db.add(DBSession(
                id="ACTIVE-SESS",
                status="active",
                current_phase="SITUATION",
                start_time=now - 300,
                visitor_id="vis-test-2",
                assigned_arm="sally_nepq",
                prospect_profile=json.dumps({
                    "name": "Alex",
                    "role": "Manager",
                }),
            ))
            db.commit()

            # The session is active — shouldn't appear in completed/abandoned query
            from sqlalchemy import or_ as _or
            ended = (
                db.query(DBSession)
                .filter(
                    DBSession.visitor_id == "vis-test-2",
                    DBSession.status.in_(["completed", "abandoned"]),
                )
                .first()
            )
            assert ended is None

            # But should appear when we check for any session with a profile
            any_session = (
                db.query(DBSession)
                .filter(
                    DBSession.visitor_id == "vis-test-2",
                    DBSession.prospect_profile.isnot(None),
                    DBSession.prospect_profile != "{}",
                )
                .order_by(DBSession.start_time.desc())
                .first()
            )
            assert any_session is not None
            profile_data = json.loads(any_session.prospect_profile)
            assert profile_data["name"] == "Alex"
        finally:
            db.close()


class TestGreetingRobustness:
    """Test that greeting generator handles edge cases gracefully."""

    def test_old_format_memory_no_crash(self):
        """Old-format memory (missing relationship/peaks/strategy) should not crash."""
        from app.main import _generate_memory_greeting
        from app.schemas import BotArm

        # Old-style memory dict (before relationship memory upgrade)
        old_memory = {
            "has_memory": True,
            "identity": {"name": "OldBob", "role": "Manager"},
            "situation": {"team_size": "5"},
            "session_summaries": [
                {"summary": "Bob asked about AI", "outcome": "abandoned_early", "phase": "SITUATION"}
            ],
            "total_prior_sessions": 1,
            # Missing: relationship, emotional_peaks, strategic_notes, unfinished_threads, pain_points, session_count
        }

        # Should not raise an error — Hank template should work
        result = _generate_memory_greeting(BotArm.HANK_HYPES, old_memory)
        assert result is not None
        assert "OldBob" in result

    def test_greeting_uses_session_count_alias(self):
        """Greeting should correctly use session_count from memory."""
        from app.main import _generate_memory_greeting
        from app.schemas import BotArm

        memory = {
            "has_memory": True,
            "identity": {"name": "Dev"},
            "session_summaries": [],
            "total_prior_sessions": 3,
            "session_count": 3,
            "relationship": {},
            "emotional_peaks": [],
            "strategic_notes": {},
            "unfinished_threads": [],
            "pain_points": [],
        }

        # Ivy template just needs name
        result = _generate_memory_greeting(BotArm.IVY_INFORMS, memory)
        assert result is not None
        assert "Dev" in result


# ===========================================================================
#  Greeting From Recent Context Tests (Race Condition Fix)
# ===========================================================================

class TestExtractNameFromContext:
    """Test _extract_name_from_context name extraction from conversation text."""

    def test_extract_name_from_self_intro_im(self):
        """Should extract name from 'I'm Dev' pattern."""
        from app.main import _extract_name_from_context
        context = "Prospect: Hi, I'm Dev, a software engineer."
        assert _extract_name_from_context(context) == "Dev"

    def test_extract_name_from_self_intro_im_no_apostrophe(self):
        """Should extract name from 'im Dev' pattern (no apostrophe)."""
        from app.main import _extract_name_from_context
        context = "Prospect: hey sally im John nice to meet you"
        assert _extract_name_from_context(context) == "John"

    def test_extract_name_from_my_name_is(self):
        """Should extract name from 'my name is' pattern."""
        from app.main import _extract_name_from_context
        context = "Prospect: Hello! My name is Sarah and I'm looking for help."
        assert _extract_name_from_context(context) == "Sarah"

    def test_extract_name_from_sally_addressing(self):
        """Should extract name from Sally addressing the prospect."""
        from app.main import _extract_name_from_context
        context = "Sally: Nice to meet you, Alex! Tell me more about your work."
        assert _extract_name_from_context(context) == "Alex"

    def test_extract_name_filters_common_words(self):
        """Should not extract common words like 'there' as names."""
        from app.main import _extract_name_from_context
        context = "Sally: Hey there! Welcome to 100x."
        assert _extract_name_from_context(context) is None

    def test_extract_name_returns_none_for_no_match(self):
        """Should return None when no name pattern is found."""
        from app.main import _extract_name_from_context
        context = "Sally: Welcome to 100x!\nProspect: Tell me about the program."
        assert _extract_name_from_context(context) is None


class TestGenerateGreetingFromContext:
    """Test _generate_greeting_from_context for generating greetings from raw conversation."""

    @patch("app.bots.base.get_client")
    def test_sally_generates_greeting_from_context(self, mock_get_client):
        """Sally should generate greeting via Claude from recent_context."""
        from app.main import _generate_greeting_from_context
        from app.schemas import BotArm

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Hey Dev! How's the engineering work going?")]
        mock_get_client.return_value.messages.create.return_value = mock_response

        result = _generate_greeting_from_context(
            BotArm.SALLY_NEPQ,
            "LAST CONVERSATION (ended: completed, reached: SITUATION):\n"
            "Sally: Hey there!\nProspect: Hi, I'm Dev, a software engineer.\n"
            "Sally: Nice to meet you, Dev!"
        )
        assert result is not None
        assert "Dev" in result
        mock_get_client.return_value.messages.create.assert_called_once()

    def test_hank_generates_template_greeting_from_context(self):
        """Hank should use template greeting with name extracted from context."""
        from app.main import _generate_greeting_from_context
        from app.schemas import BotArm

        result = _generate_greeting_from_context(
            BotArm.HANK_HYPES,
            "LAST CONVERSATION (ended: completed, reached: SITUATION):\n"
            "Prospect: Hi, I'm Alex."
        )
        assert result is not None
        assert "Alex" in result

    def test_ivy_generates_template_greeting_from_context(self):
        """Ivy should use template greeting with name extracted from context."""
        from app.main import _generate_greeting_from_context
        from app.schemas import BotArm

        result = _generate_greeting_from_context(
            BotArm.IVY_INFORMS,
            "LAST CONVERSATION:\nProspect: Hello! My name is Sarah."
        )
        assert result is not None
        assert "Sarah" in result

    def test_returns_none_when_no_name_extractable_hank(self):
        """Should return None for control bots when no name can be extracted."""
        from app.main import _generate_greeting_from_context
        from app.schemas import BotArm

        result = _generate_greeting_from_context(
            BotArm.HANK_HYPES,
            "LAST CONVERSATION:\nSally: Welcome!\nProspect: Tell me about it."
        )
        assert result is None

    @patch("app.bots.base.get_client")
    def test_sally_api_error_falls_back_to_template_with_name(self, mock_get_client):
        """On Claude API failure, should fall back to template with extracted name."""
        from app.main import _generate_greeting_from_context
        from app.schemas import BotArm

        mock_get_client.return_value.messages.create.side_effect = Exception("API error")

        result = _generate_greeting_from_context(
            BotArm.SALLY_NEPQ,
            "Prospect: Hi, I'm Dev, a software engineer."
        )
        # Should fall back to template with extracted name
        assert result is not None
        assert "Dev" in result

    @patch("app.bots.base.get_client")
    def test_sally_api_error_no_name_returns_none(self, mock_get_client):
        """On Claude API failure with no extractable name, should return None."""
        from app.main import _generate_greeting_from_context
        from app.schemas import BotArm

        mock_get_client.return_value.messages.create.side_effect = Exception("API error")

        result = _generate_greeting_from_context(
            BotArm.SALLY_NEPQ,
            "Sally: Welcome!\nProspect: Tell me about the program."
        )
        # No name to extract — should return None
        assert result is None


class TestGreetingMemoryContextIntegration:
    """Test that _generate_memory_greeting uses recent_context as fallback."""

    @patch("app.bots.base.get_client")
    def test_uses_context_fallback_when_no_memory(self, mock_get_client):
        """Should use recent_context to generate greeting when has_memory is False."""
        from app.main import _generate_memory_greeting
        from app.schemas import BotArm

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Hey Dev! Good to see you again.")]
        mock_get_client.return_value.messages.create.return_value = mock_response

        empty_memory = {"has_memory": False}
        recent_ctx = (
            "LAST CONVERSATION (ended: completed, reached: SITUATION):\n"
            "Sally: Hey there!\nProspect: Hi, I'm Dev.\nSally: Nice to meet you, Dev!"
        )

        result = _generate_memory_greeting(BotArm.SALLY_NEPQ, empty_memory, recent_context=recent_ctx)
        assert result is not None
        # Claude API should have been called
        mock_get_client.return_value.messages.create.assert_called_once()

    def test_returns_none_when_no_memory_and_no_context(self):
        """Should return None when both memory and context are empty."""
        from app.main import _generate_memory_greeting
        from app.schemas import BotArm

        result = _generate_memory_greeting(BotArm.SALLY_NEPQ, {"has_memory": False}, recent_context="")
        assert result is None

    def test_returns_none_for_empty_memory_dict(self):
        """Should return None for completely empty memory dict with no context."""
        from app.main import _generate_memory_greeting
        from app.schemas import BotArm

        result = _generate_memory_greeting(BotArm.SALLY_NEPQ, {}, recent_context="")
        assert result is None

    def test_hank_uses_context_fallback(self):
        """Hank should use recent_context when no structured memory."""
        from app.main import _generate_memory_greeting
        from app.schemas import BotArm

        empty_memory = {"has_memory": False}
        recent_ctx = "LAST CONVERSATION:\nProspect: Hi, I'm Mike."

        result = _generate_memory_greeting(BotArm.HANK_HYPES, empty_memory, recent_context=recent_ctx)
        assert result is not None
        assert "Mike" in result
