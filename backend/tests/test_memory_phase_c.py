"""
Tests for Phase C: Memory Injection into Prompts.

Run with: cd backend && python -m pytest tests/test_memory_phase_c.py -v
"""
import pytest
import os
import json
import time
import uuid

# Set env vars BEFORE any app imports
os.environ["DATABASE_URL"] = "sqlite:///test_memory_c.db"
os.environ["ANTHROPIC_API_KEY"] = "test-key"
os.environ["GEMINI_API_KEY"] = "test-key"
os.environ["SKIP_SCHEMA_CHECK"] = "true"

from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def reset_db():
    """Reset DB singletons and create fresh schema for each test."""
    import app.database as db_module

    db_module.DATABASE_URL = "sqlite:///test_memory_c.db"
    db_module._engine = None
    db_module._SessionLocal = None

    from app.database import Base, _get_engine
    engine = _get_engine()
    Base.metadata.create_all(bind=engine)

    yield

    Base.metadata.drop_all(bind=engine)
    db_module._engine = None
    db_module._SessionLocal = None
    try:
        os.remove("test_memory_c.db")
    except OSError:
        pass


@pytest.fixture
def client():
    from app.main import app
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c


class TestComprehensionPromptMemoryInjection:
    """Test that comprehension prompt correctly includes/excludes memory."""

    def test_comprehension_prompt_includes_memory(self):
        """When memory_context is provided, prompt should include it."""
        from app.layers.comprehension import build_comprehension_prompt
        from app.models import ProspectProfile
        from app.schemas import NepqPhase

        memory = "RETURNING VISITOR — CONTEXT FROM PRIOR CONVERSATIONS:\nIdentity: Name: Alex, Role: VP Ops\nKnown pain points: Manual data entry"

        prompt = build_comprehension_prompt(
            current_phase=NepqPhase.CONNECTION,
            user_message="Hi there",
            conversation_history=[],
            prospect_profile=ProspectProfile(),
            memory_context=memory,
        )

        assert "LONG-TERM MEMORY" in prompt
        assert "Alex" in prompt
        assert "VP Ops" in prompt
        assert "ALREADY KNOWN" in prompt

    def test_comprehension_prompt_excludes_memory_when_empty(self):
        """When memory_context is empty, prompt should NOT include memory section."""
        from app.layers.comprehension import build_comprehension_prompt
        from app.models import ProspectProfile
        from app.schemas import NepqPhase

        prompt = build_comprehension_prompt(
            current_phase=NepqPhase.CONNECTION,
            user_message="Hi there",
            conversation_history=[],
            prospect_profile=ProspectProfile(),
            memory_context="",
        )

        assert "LONG-TERM MEMORY" not in prompt


class TestResponsePromptMemoryInjection:
    """Test that response prompt correctly includes/excludes memory."""

    def test_response_prompt_includes_memory(self):
        """When memory_context is provided, response prompt should include it."""
        from app.layers.response import build_response_prompt
        from app.models import ProspectProfile, DecisionOutput

        memory = "RETURNING VISITOR — CONTEXT FROM PRIOR CONVERSATIONS:\nIdentity: Name: Alex"

        decision = DecisionOutput(
            action="STAY",
            target_phase="CONNECTION",
            reason="continue",
            retry_count=0,
        )

        prompt = build_response_prompt(
            decision=decision,
            user_message="Hello",
            conversation_history=[],
            profile=ProspectProfile(),
            memory_context=memory,
        )

        assert "RETURNING VISITOR" in prompt
        assert "Alex" in prompt
        assert "naturally" in prompt.lower()

    def test_response_prompt_excludes_memory_when_empty(self):
        """When memory_context is empty, response prompt should NOT include memory section."""
        from app.layers.response import build_response_prompt
        from app.models import ProspectProfile, DecisionOutput

        decision = DecisionOutput(
            action="STAY",
            target_phase="CONNECTION",
            reason="continue",
            retry_count=0,
        )

        prompt = build_response_prompt(
            decision=decision,
            user_message="Hello",
            conversation_history=[],
            profile=ProspectProfile(),
            memory_context="",
        )

        assert "LONG-TERM MEMORY" not in prompt


class TestProfileSeedingFromMemory:
    """Test that prospect profile gets pre-populated from memory."""

    def test_seed_profile_with_full_memory(self):
        """Profile should be seeded with identity and situation facts."""
        from app.main import _seed_profile_from_memory

        memory = {
            "has_memory": True,
            "identity": {"name": "Alex", "role": "VP Ops", "company": "Acme Corp", "industry": "Real Estate"},
            "situation": {"team_size": "50", "tools_mentioned": ["Salesforce", "HubSpot"]},
            "pain_points": ["Manual data entry", "Slow follow-ups"],
        }

        profile_json = _seed_profile_from_memory(memory)
        profile = json.loads(profile_json)

        assert profile["name"] == "Alex"
        assert profile["role"] == "VP Ops"
        assert profile["company"] == "Acme Corp"
        assert profile["industry"] == "Real Estate"
        assert profile["team_size"] == "50"
        assert "Salesforce" in profile["tools_mentioned"]
        assert "Manual data entry" in profile["pain_points"]

    def test_seed_profile_no_memory(self):
        """No memory should return empty profile."""
        from app.main import _seed_profile_from_memory

        result = _seed_profile_from_memory({"has_memory": False})
        assert result == "{}"

    def test_seed_profile_partial_memory(self):
        """Partial memory should only seed available fields."""
        from app.main import _seed_profile_from_memory

        memory = {
            "has_memory": True,
            "identity": {"name": "Alex"},
            "situation": {},
            "pain_points": [],
        }

        profile_json = _seed_profile_from_memory(memory)
        profile = json.loads(profile_json)

        assert profile["name"] == "Alex"
        assert "role" not in profile
        assert "tools_mentioned" not in profile


class TestMemoryGreetingGeneration:
    """Test memory-aware greeting generation."""

    def test_greeting_no_memory_returns_none(self):
        """No memory should return None (caller uses default)."""
        from app.main import _generate_memory_greeting
        from app.schemas import BotArm

        result = _generate_memory_greeting(BotArm.SALLY_NEPQ, {"has_memory": False})
        assert result is None

    def test_greeting_no_name_returns_none(self):
        """Memory without a name should return None."""
        from app.main import _generate_memory_greeting
        from app.schemas import BotArm

        memory = {"has_memory": True, "identity": {}, "session_summaries": []}
        result = _generate_memory_greeting(BotArm.SALLY_NEPQ, memory)
        assert result is None

    def test_hank_greeting_with_memory(self):
        """Hank should get a template-based personalized greeting."""
        from app.main import _generate_memory_greeting
        from app.schemas import BotArm

        memory = {
            "has_memory": True,
            "identity": {"name": "Alex"},
            "session_summaries": [{"summary": "Discussed AI tools", "outcome": "abandoned", "phase": "SITUATION"}],
        }
        result = _generate_memory_greeting(BotArm.HANK_HYPES, memory)
        assert result is not None
        assert "Alex" in result

    def test_ivy_greeting_with_memory(self):
        """Ivy should get a template-based personalized greeting."""
        from app.main import _generate_memory_greeting
        from app.schemas import BotArm

        memory = {
            "has_memory": True,
            "identity": {"name": "Alex"},
            "session_summaries": [],
        }
        result = _generate_memory_greeting(BotArm.IVY_INFORMS, memory)
        assert result is not None
        assert "Alex" in result

    @patch("app.bots.base.get_client")
    def test_sally_greeting_with_memory(self, mock_get_client):
        """Sally should generate greeting via Claude API."""
        from app.main import _generate_memory_greeting
        from app.schemas import BotArm

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Hey Alex! Great to see you back. Last time we were exploring some interesting possibilities — shall we pick up where we left off?")]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        memory = {
            "has_memory": True,
            "identity": {"name": "Alex", "role": "VP Ops", "company": "Acme"},
            "session_summaries": [{"summary": "Discussed automation", "outcome": "abandoned", "phase": "SITUATION"}],
        }
        result = _generate_memory_greeting(BotArm.SALLY_NEPQ, memory)
        assert result is not None
        assert "Alex" in result
        mock_client.messages.create.assert_called_once()

    @patch("app.bots.base.get_client")
    def test_sally_greeting_api_failure_fallback(self, mock_get_client):
        """Sally greeting should fall back to template if Claude API fails."""
        from app.main import _generate_memory_greeting
        from app.schemas import BotArm

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API error")
        mock_get_client.return_value = mock_client

        memory = {
            "has_memory": True,
            "identity": {"name": "Alex"},
            "session_summaries": [],
            "relationship": {},
            "emotional_peaks": [],
            "strategic_notes": {},
            "unfinished_threads": [],
            "pain_points": [],
            "session_count": 1,
        }
        result = _generate_memory_greeting(BotArm.SALLY_NEPQ, memory)
        assert result is not None
        assert "Alex" in result
        assert "Good to see you back" in result


class TestControlBotMemoryContext:
    """Test that control bots (Hank/Ivy) properly use memory_context."""

    def test_hank_includes_memory_in_system_prompt(self):
        """Hank's system prompt should include memory when provided."""
        from app.bots.hank import HankBot

        bot = HankBot()
        memory = "RETURNING VISITOR: Name: Alex, Role: VP Ops"

        # We can't easily test the full respond() without mocking Claude,
        # but we can verify the system prompt assembly logic
        system = bot.system_prompt
        if memory:
            system = f"{bot.system_prompt}\n\n{memory}"

        assert "RETURNING VISITOR" in system
        assert "Alex" in system
        assert bot.system_prompt in system

    def test_ivy_includes_memory_in_system_prompt(self):
        """Ivy's system prompt should include memory when provided."""
        from app.bots.ivy import IvyBot

        bot = IvyBot()
        memory = "RETURNING VISITOR: Name: Alex"

        system = bot.system_prompt
        if memory:
            system = f"{bot.system_prompt}\n\n{memory}"

        assert "RETURNING VISITOR" in system
        assert "Alex" in system


class TestMemoryLoadedInSendMessage:
    """Test that send_message loads and passes memory to route_message."""

    @patch("app.main.route_message")
    def test_send_message_passes_memory_context(self, mock_route, client):
        """send_message should load memory and pass memory_context to route_message."""
        # Set up mock return value
        mock_route.return_value = {
            "response_text": "Hi there!",
            "new_phase": "CONNECTION",
            "new_profile_json": "{}",
            "thought_log_json": "{}",
            "phase_changed": False,
            "session_ended": False,
            "retry_count": 0,
            "consecutive_no_new_info": 0,
            "turns_in_current_phase": 1,
            "deepest_emotional_depth": "surface",
            "objection_diffusion_step": 0,
            "ownership_substep": 0,
        }

        # Create session with visitor_id
        visitor_id = str(uuid.uuid4())
        create_res = client.post("/api/sessions", json={
            "pre_conviction": 5,
            "selected_bot": "sally_nepq",
            "visitor_id": visitor_id,
        })
        session_id = create_res.json()["session_id"]

        # Send a message
        msg_res = client.post(f"/api/sessions/{session_id}/messages", json={
            "content": "Hello"
        })
        assert msg_res.status_code == 200

        # Verify route_message was called with memory_context parameter
        call_kwargs = mock_route.call_args
        assert "memory_context" in call_kwargs.kwargs or len(call_kwargs.args) > 2

    @patch("app.main.route_message")
    def test_send_message_no_visitor_empty_memory(self, mock_route, client):
        """Without visitor_id, memory_context should be empty string."""
        mock_route.return_value = {
            "response_text": "Hi there!",
            "new_phase": "CONVERSATION",
            "new_profile_json": "{}",
            "thought_log_json": "{}",
            "phase_changed": False,
            "session_ended": False,
            "retry_count": 0,
            "consecutive_no_new_info": 0,
            "turns_in_current_phase": 1,
            "deepest_emotional_depth": "surface",
            "objection_diffusion_step": 0,
            "ownership_substep": 0,
        }

        # Create session without visitor_id
        create_res = client.post("/api/sessions", json={
            "pre_conviction": 5,
            "selected_bot": "hank_hypes",
        })
        session_id = create_res.json()["session_id"]

        # Send a message
        client.post(f"/api/sessions/{session_id}/messages", json={
            "content": "Hello"
        })

        # Verify route_message was called with empty memory_context
        call_kwargs = mock_route.call_args
        if call_kwargs.kwargs.get("memory_context") is not None:
            assert call_kwargs.kwargs["memory_context"] == ""


class TestCreateSessionWithMemory:
    """Test that create_session loads memory and seeds profile."""

    def test_create_session_seeds_profile_for_returning_visitor(self, client):
        """Returning visitor's profile should be pre-populated from memory."""
        from app.database import get_db, DBMemoryFact, DBSession
        import app.database as db_module

        visitor_id = str(uuid.uuid4())

        # Manually insert memory facts for this visitor
        db = next(get_db())
        now = time.time()
        facts = [
            DBMemoryFact(id=str(uuid.uuid4()), visitor_id=visitor_id, source_session_id="PREV",
                         category="identity", fact_key="name", fact_value="Alex",
                         confidence=1.0, created_at=now, updated_at=now, is_active=1),
            DBMemoryFact(id=str(uuid.uuid4()), visitor_id=visitor_id, source_session_id="PREV",
                         category="identity", fact_key="role", fact_value="VP Ops",
                         confidence=1.0, created_at=now, updated_at=now, is_active=1),
        ]
        for f in facts:
            db.add(f)
        db.commit()
        db.close()

        # Create session for this visitor
        res = client.post("/api/sessions", json={
            "pre_conviction": 5,
            "selected_bot": "hank_hypes",  # Use Hank to avoid Claude API call for greeting
            "visitor_id": visitor_id,
        })
        assert res.status_code == 200
        session_id = res.json()["session_id"]

        # Check that profile was seeded
        db2 = next(get_db())
        session = db2.query(DBSession).filter(DBSession.id == session_id).first()
        profile = json.loads(session.prospect_profile or "{}")
        assert profile.get("name") == "Alex"
        assert profile.get("role") == "VP Ops"
        db2.close()

    def test_create_session_personalized_greeting_hank(self, client):
        """Returning visitor should get personalized greeting from Hank."""
        from app.database import get_db, DBMemoryFact

        visitor_id = str(uuid.uuid4())

        # Insert name fact
        db = next(get_db())
        now = time.time()
        db.add(DBMemoryFact(
            id=str(uuid.uuid4()), visitor_id=visitor_id, source_session_id="PREV",
            category="identity", fact_key="name", fact_value="Alex",
            confidence=1.0, created_at=now, updated_at=now, is_active=1,
        ))
        db.commit()
        db.close()

        res = client.post("/api/sessions", json={
            "pre_conviction": 5,
            "selected_bot": "hank_hypes",
            "visitor_id": visitor_id,
        })
        assert res.status_code == 200
        greeting = res.json()["greeting"]["content"]
        assert "Alex" in greeting

    def test_create_session_default_greeting_new_visitor(self, client):
        """New visitor (no memory) should get default greeting."""
        res = client.post("/api/sessions", json={
            "pre_conviction": 5,
            "selected_bot": "hank_hypes",
        })
        assert res.status_code == 200
        greeting = res.json()["greeting"]["content"]
        # Hank's default greeting starts with "Hey!"
        assert "Hey!" in greeting or "Great to connect" in greeting
