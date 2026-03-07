"""
Tests for Phase A: Session Resumption with Visitor Identity.

Run with: cd backend && python -m pytest tests/test_memory_phase_a.py -v
Requires: pip install pytest httpx
"""
import pytest
import os
import sys
import time
import uuid

# Set env vars BEFORE any app imports (database.py checks DATABASE_URL at import time)
os.environ["DATABASE_URL"] = "sqlite:///test_memory_a.db"
os.environ["ANTHROPIC_API_KEY"] = "test-key"
os.environ["GEMINI_API_KEY"] = "test-key"
os.environ["SKIP_SCHEMA_CHECK"] = "true"

from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def reset_db():
    """Reset DB singletons and create fresh schema for each test."""
    import app.database as db_module

    # Force SQLite for tests — override both the module var and the singleton
    db_module.DATABASE_URL = "sqlite:///test_memory_a.db"
    db_module._engine = None
    db_module._SessionLocal = None

    from app.database import Base, _get_engine
    engine = _get_engine()
    Base.metadata.create_all(bind=engine)

    yield

    Base.metadata.drop_all(bind=engine)
    db_module._engine = None
    db_module._SessionLocal = None
    # Clean up test DB file
    try:
        os.remove("test_memory_a.db")
    except OSError:
        pass


@pytest.fixture
def client():
    """Create a test client."""
    from app.main import app
    with TestClient(app) as c:
        yield c


class TestVisitorIdOnSessionCreation:
    """Test that visitor_id is accepted and stored when creating sessions."""

    def test_create_session_with_visitor_id(self, client):
        """Session creation should accept and return visitor_id."""
        visitor_id = str(uuid.uuid4())
        res = client.post("/api/sessions", json={
            "pre_conviction": 5,
            "selected_bot": "sally_nepq",
            "visitor_id": visitor_id,
        })
        assert res.status_code == 200
        data = res.json()
        assert data["visitor_id"] == visitor_id
        assert data["session_id"]
        assert data["greeting"]["role"] == "assistant"

    def test_create_session_without_visitor_id(self, client):
        """Session creation should still work without visitor_id (backward compat)."""
        res = client.post("/api/sessions", json={
            "pre_conviction": 7,
            "selected_bot": "hank_hypes",
        })
        assert res.status_code == 200
        data = res.json()
        assert data["session_id"]


class TestSessionResumption:
    """Test the active session lookup and resumption endpoint."""

    def test_no_active_session_returns_404(self, client):
        """Visitor with no sessions should get 404."""
        fake_visitor = str(uuid.uuid4())
        res = client.get(f"/api/visitors/{fake_visitor}/active-session")
        assert res.status_code == 404

    def test_resume_active_session(self, client):
        """Should find and return an active session for a known visitor."""
        visitor_id = str(uuid.uuid4())

        # Create a session
        create_res = client.post("/api/sessions", json={
            "pre_conviction": 5,
            "selected_bot": "sally_nepq",
            "visitor_id": visitor_id,
        })
        assert create_res.status_code == 200
        session_id = create_res.json()["session_id"]

        # Check for active session
        resume_res = client.get(f"/api/visitors/{visitor_id}/active-session")
        assert resume_res.status_code == 200
        data = resume_res.json()
        assert data["session_id"] == session_id
        assert data["visitor_id"] == visitor_id
        assert len(data["messages"]) >= 1  # At least the greeting
        assert data["messages"][0]["role"] == "assistant"

    def test_resume_abandoned_session_reactivates(self, client):
        """Abandoned sessions within 24h should be reactivated."""
        visitor_id = str(uuid.uuid4())

        # Create and abandon a session
        create_res = client.post("/api/sessions", json={
            "pre_conviction": 5,
            "selected_bot": "ivy_informs",
            "visitor_id": visitor_id,
        })
        session_id = create_res.json()["session_id"]
        client.post(f"/api/sessions/{session_id}/end")

        # Should still find it
        resume_res = client.get(f"/api/visitors/{visitor_id}/active-session")
        assert resume_res.status_code == 200
        data = resume_res.json()
        assert data["session_id"] == session_id

    def test_completed_session_not_resumable(self, client):
        """Completed sessions should NOT be resumable."""
        visitor_id = str(uuid.uuid4())

        # Create a session and mark it completed
        create_res = client.post("/api/sessions", json={
            "pre_conviction": 5,
            "selected_bot": "sally_nepq",
            "visitor_id": visitor_id,
        })
        session_id = create_res.json()["session_id"]

        # Manually update status to completed
        from app.database import get_db, DBSession
        db = next(get_db())
        db_session = db.query(DBSession).filter(DBSession.id == session_id).first()
        db_session.status = "completed"
        db_session.end_time = time.time()
        db.commit()
        db.close()

        # Should not find it
        resume_res = client.get(f"/api/visitors/{visitor_id}/active-session")
        assert resume_res.status_code == 404

    def test_resume_returns_correct_bot_info(self, client):
        """Resumed session should return correct bot display name and arm."""
        visitor_id = str(uuid.uuid4())

        client.post("/api/sessions", json={
            "pre_conviction": 3,
            "selected_bot": "hank_hypes",
            "visitor_id": visitor_id,
        })

        resume_res = client.get(f"/api/visitors/{visitor_id}/active-session")
        data = resume_res.json()
        assert data["assigned_arm"] == "hank_hypes"
        assert data["bot_display_name"] == "Hank"

    def test_multiple_sessions_returns_most_recent(self, client):
        """If visitor has multiple sessions, return the most recent one."""
        visitor_id = str(uuid.uuid4())

        # Create first session and end it
        res1 = client.post("/api/sessions", json={
            "pre_conviction": 3,
            "selected_bot": "sally_nepq",
            "visitor_id": visitor_id,
        })
        session1_id = res1.json()["session_id"]
        client.post(f"/api/sessions/{session1_id}/end")

        # Create second session
        res2 = client.post("/api/sessions", json={
            "pre_conviction": 7,
            "selected_bot": "hank_hypes",
            "visitor_id": visitor_id,
        })
        session2_id = res2.json()["session_id"]

        # Should return the second (most recent) session
        resume_res = client.get(f"/api/visitors/{visitor_id}/active-session")
        data = resume_res.json()
        assert data["session_id"] == session2_id


class TestBackwardCompatibility:
    """Ensure existing endpoints still work without visitor_id."""

    def test_session_detail_still_works(self, client):
        """Session detail should work regardless of visitor_id presence."""
        res = client.post("/api/sessions", json={
            "pre_conviction": 5,
            "selected_bot": "ivy_informs",
        })
        session_id = res.json()["session_id"]

        session_res = client.get(f"/api/sessions/{session_id}")
        assert session_res.status_code == 200

    def test_list_sessions_still_works(self, client):
        """Session listing should still work."""
        res = client.get("/api/sessions")
        assert res.status_code == 200

    def test_metrics_still_works(self, client):
        """Metrics endpoint should still work."""
        res = client.get("/api/metrics")
        assert res.status_code == 200
