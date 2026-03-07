"""
Tests for Phase B: Memory Extraction and Storage.

Run with: cd backend && python -m pytest tests/test_memory_phase_b.py -v
"""
import pytest
import os
import json
import time
import uuid

# Set env vars BEFORE any app imports
os.environ["DATABASE_URL"] = "sqlite:///test_memory_b.db"
os.environ["ANTHROPIC_API_KEY"] = "test-key"
os.environ["GEMINI_API_KEY"] = "test-key"
os.environ["SKIP_SCHEMA_CHECK"] = "true"

from unittest.mock import patch, MagicMock


class TestMemoryExtraction:
    """Test the memory extraction prompt and parsing."""

    def test_extract_memory_parses_valid_json(self):
        """Extraction should parse well-formed Gemini output."""
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "identity": {"name": "Alex", "role": "VP Sales", "company": "TechCorp", "industry": "SaaS"},
            "situation": {"team_size": "12", "tools_mentioned": ["Apollo", "Salesforce"], "workflow_description": "outbound sales"},
            "pain_points": ["manual follow-ups waste 10hrs/week"],
            "desired_state": "automate follow-ups",
            "objection_history": ["PRICE: too expensive"],
            "emotional_signals": ["got excited about automation"],
            "session_summary": "Alex is a VP Sales at TechCorp. Main pain is manual follow-ups.",
            "conversation_outcome": "completed_free",
        })

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            with patch("google.generativeai.GenerativeModel") as mock_model:
                mock_model.return_value.generate_content.return_value = mock_response

                from app.memory import extract_memory_from_session
                # Reset the lazy config flag
                import app.memory as mem_module
                mem_module._gemini_configured = False

                result = extract_memory_from_session(
                    session_id="TEST123",
                    visitor_id="visitor-1",
                    transcript=[
                        {"role": "assistant", "content": "Hey there!"},
                        {"role": "user", "content": "Hi, I'm Alex, VP Sales at TechCorp"},
                    ],
                    profile_json='{"name": "Alex"}',
                    outcome="completed",
                    final_phase="COMMITMENT",
                )

                assert result["identity"]["name"] == "Alex"
                assert result["identity"]["company"] == "TechCorp"
                assert len(result["pain_points"]) == 1
                assert result["conversation_outcome"] == "completed_free"

    def test_extract_memory_handles_failure(self):
        """Extraction should return empty dict on failure."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            with patch("google.generativeai.GenerativeModel") as mock_model:
                mock_model.return_value.generate_content.side_effect = Exception("API error")

                from app.memory import extract_memory_from_session
                import app.memory as mem_module
                mem_module._gemini_configured = False

                result = extract_memory_from_session(
                    session_id="TEST123",
                    visitor_id="visitor-1",
                    transcript=[{"role": "user", "content": "hi"}],
                    profile_json="{}",
                    outcome="abandoned",
                    final_phase="CONNECTION",
                )
                assert result == {}


class TestMemoryStorage:
    """Test storing and loading memory facts."""

    @pytest.fixture
    def db_setup(self):
        """Set up a SQLite DB for testing."""
        import app.database as db_module
        db_module.DATABASE_URL = "sqlite:///test_memory_b.db"
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
            os.remove("test_memory_b.db")
        except OSError:
            pass

    def test_store_and_load_memory(self, db_setup):
        """Should store facts and retrieve them correctly."""
        from app.memory import store_memory, load_visitor_memory

        visitor_id = str(uuid.uuid4())
        extraction = {
            "identity": {"name": "Alex", "role": "VP Sales", "company": "TechCorp", "industry": "SaaS"},
            "situation": {"team_size": "12", "tools_mentioned": ["Apollo"], "workflow_description": "outbound"},
            "pain_points": ["manual follow-ups waste time"],
            "desired_state": "automate everything",
            "objection_history": ["PRICE: too expensive"],
            "emotional_signals": ["excited about AI"],
            "session_summary": "Alex from TechCorp wants automation.",
            "conversation_outcome": "completed_free",
            "final_phase": "COMMITMENT",
        }

        store_memory(db_setup, "SESSION-1", visitor_id, extraction)

        db = db_setup()
        try:
            memory = load_visitor_memory(db, visitor_id)
            assert memory["has_memory"] is True
            assert memory["identity"]["name"] == "Alex"
            assert memory["identity"]["company"] == "TechCorp"
            assert len(memory["pain_points"]) == 1
            assert memory["total_prior_sessions"] == 1
        finally:
            db.close()

    def test_fact_superseding(self, db_setup):
        """Newer facts should supersede older ones for same category+key."""
        from app.memory import store_memory, load_visitor_memory

        visitor_id = str(uuid.uuid4())

        # First session: Alex is VP Sales
        extraction1 = {
            "identity": {"name": "Alex", "role": "VP Sales"},
            "situation": {},
            "pain_points": [],
            "desired_state": None,
            "objection_history": [],
            "emotional_signals": [],
            "session_summary": "First chat.",
            "conversation_outcome": "abandoned_early",
            "final_phase": "CONNECTION",
        }
        store_memory(db_setup, "SESSION-1", visitor_id, extraction1)

        # Second session: Alex is now VP Ops
        extraction2 = {
            "identity": {"name": "Alex", "role": "VP Ops"},
            "situation": {},
            "pain_points": [],
            "desired_state": None,
            "objection_history": [],
            "emotional_signals": [],
            "session_summary": "Second chat, role changed.",
            "conversation_outcome": "abandoned_mid",
            "final_phase": "SITUATION",
        }
        store_memory(db_setup, "SESSION-2", visitor_id, extraction2)

        db = db_setup()
        try:
            memory = load_visitor_memory(db, visitor_id)
            assert memory["identity"]["role"] == "VP Ops"  # Should be the newer value
            assert memory["total_prior_sessions"] == 2
        finally:
            db.close()


class TestMemoryFormatting:
    """Test the prompt formatting function."""

    def test_format_empty_memory(self):
        """No memory should return empty string."""
        from app.memory import format_memory_for_prompt
        assert format_memory_for_prompt({"has_memory": False}) == ""

    def test_format_full_memory(self):
        """Full memory should produce a well-structured prompt block."""
        from app.memory import format_memory_for_prompt
        memory = {
            "has_memory": True,
            "identity": {"name": "Alex", "role": "VP Sales", "company": "TechCorp"},
            "situation": {"team_size": "12", "tools_mentioned": ["Apollo"]},
            "pain_points": ["manual follow-ups"],
            "objection_history": ["PRICE: too expensive"],
            "emotional_signals": [],
            "session_summaries": [
                {"summary": "Alex wants automation", "outcome": "completed_free", "phase": "COMMITMENT"}
            ],
            "total_prior_sessions": 1,
        }
        result = format_memory_for_prompt(memory)
        assert "YOU KNOW THIS PERSON" in result
        assert "Alex" in result
        assert "TechCorp" in result
        assert "manual follow-ups" in result
        assert "PRICE: too expensive" in result
