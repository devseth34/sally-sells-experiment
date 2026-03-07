"""
Tests for User Authentication & Multi-Method Identification.

Covers:
- Registration (success, duplicate, short password)
- Login (success, wrong password, nonexistent email)
- GET /api/auth/me (authenticated, unauthenticated)
- Session creation with auth header
- Name+phone identification (new user, existing user, phone normalization)
- Memory merge on register/login

Run with: cd backend && python -m pytest tests/test_auth.py -v
"""
import pytest
import os
import time
import uuid

# Set env vars BEFORE any app imports (database.py checks DATABASE_URL at import time)
os.environ["DATABASE_URL"] = "sqlite:///test_auth.db"
os.environ["ANTHROPIC_API_KEY"] = "test-key"
os.environ["GEMINI_API_KEY"] = "test-key"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-auth-tests"
os.environ["SKIP_SCHEMA_CHECK"] = "true"

from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def reset_db():
    """Reset DB singletons and create fresh schema for each test."""
    import app.database as db_module

    db_module.DATABASE_URL = "sqlite:///test_auth.db"
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
        os.remove("test_auth.db")
    except OSError:
        pass


@pytest.fixture
def client():
    """Create a test client."""
    from app.main import app
    with TestClient(app) as c:
        yield c


def _register(client, email="alice@example.com", password="secret123", name="Alice Smith", phone="555-123-4567"):
    """Helper: register a user and return the response."""
    return client.post("/api/auth/register", json={
        "email": email,
        "password": password,
        "display_name": name,
        "phone": phone,
    })


def _login(client, email="alice@example.com", password="secret123", visitor_id=None):
    """Helper: login and return the response."""
    body = {"email": email, "password": password}
    if visitor_id:
        body["visitor_id"] = visitor_id
    return client.post("/api/auth/login", json=body)


# ===========================================================================
#  Registration Tests
# ===========================================================================

class TestRegistration:

    def test_register_success(self, client):
        """Registration with valid data returns token, user_id, email."""
        res = _register(client)
        assert res.status_code == 200
        data = res.json()
        assert "token" in data
        assert data["email"] == "alice@example.com"
        assert data["user_id"]
        assert data["display_name"] == "Alice Smith"

    def test_register_duplicate_email(self, client):
        """Registering with the same email twice returns 409."""
        _register(client, email="dup@test.com")
        res = _register(client, email="dup@test.com")
        assert res.status_code == 409
        assert "already registered" in res.json()["detail"].lower()

    def test_register_duplicate_email_case_insensitive(self, client):
        """Email uniqueness is case-insensitive."""
        _register(client, email="Test@Example.COM")
        res = _register(client, email="test@example.com")
        assert res.status_code == 409

    def test_register_short_password(self, client):
        """Password shorter than 6 chars is rejected (422 validation)."""
        res = _register(client, password="12345")
        assert res.status_code == 422

    def test_register_without_optional_fields(self, client):
        """Registration works with only email and password."""
        res = client.post("/api/auth/register", json={
            "email": "minimal@test.com",
            "password": "password123",
        })
        assert res.status_code == 200
        data = res.json()
        assert data["email"] == "minimal@test.com"
        assert data["display_name"] is None


# ===========================================================================
#  Login Tests
# ===========================================================================

class TestLogin:

    def test_login_success(self, client):
        """Login with correct credentials returns token."""
        _register(client)
        res = _login(client)
        assert res.status_code == 200
        data = res.json()
        assert "token" in data
        assert data["email"] == "alice@example.com"
        assert data["display_name"] == "Alice Smith"

    def test_login_wrong_password(self, client):
        """Login with incorrect password returns 401."""
        _register(client)
        res = _login(client, password="wrongpassword")
        assert res.status_code == 401
        assert "invalid" in res.json()["detail"].lower()

    def test_login_nonexistent_email(self, client):
        """Login with non-existent email returns 401."""
        res = _login(client, email="nobody@test.com", password="whatever")
        assert res.status_code == 401

    def test_login_case_insensitive_email(self, client):
        """Email lookup is case-insensitive."""
        _register(client, email="CamelCase@Test.Com")
        res = _login(client, email="camelcase@test.com")
        assert res.status_code == 200


# ===========================================================================
#  Auth Me Tests
# ===========================================================================

class TestAuthMe:

    def test_me_authenticated(self, client):
        """GET /api/auth/me with valid token returns user info."""
        reg = _register(client)
        token = reg.json()["token"]
        res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        data = res.json()
        assert data["email"] == "alice@example.com"
        assert data["display_name"] == "Alice Smith"

    def test_me_unauthenticated(self, client):
        """GET /api/auth/me without token returns 401."""
        res = client.get("/api/auth/me")
        assert res.status_code == 401

    def test_me_invalid_token(self, client):
        """GET /api/auth/me with garbage token returns 401."""
        res = client.get("/api/auth/me", headers={"Authorization": "Bearer garbage.token.here"})
        assert res.status_code == 401


# ===========================================================================
#  Session Creation with Auth
# ===========================================================================

class TestSessionWithAuth:

    def test_create_session_authenticated(self, client):
        """Creating a session with a valid auth token associates it with the user."""
        reg = _register(client)
        token = reg.json()["token"]
        visitor_id = str(uuid.uuid4())
        res = client.post("/api/sessions", json={
            "pre_conviction": 5,
            "selected_bot": "sally_nepq",
            "visitor_id": visitor_id,
        }, headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
        data = res.json()
        assert data["session_id"]
        assert data["visitor_id"] == visitor_id

    def test_create_session_anonymous(self, client):
        """Creating a session without auth still works (backward compat)."""
        visitor_id = str(uuid.uuid4())
        res = client.post("/api/sessions", json={
            "pre_conviction": 7,
            "selected_bot": "hank_hypes",
            "visitor_id": visitor_id,
        })
        assert res.status_code == 200


# ===========================================================================
#  Name + Phone Identification Tests
# ===========================================================================

class TestNamePhoneIdentification:

    def test_identify_existing_user(self, client):
        """Identification finds an existing user by name + phone."""
        _register(client, name="Bob Jones", phone="555-999-8888")
        res = client.post("/api/auth/identify", json={
            "full_name": "Bob Jones",
            "phone": "555-999-8888",
        })
        assert res.status_code == 200
        data = res.json()
        assert data["identified"] is True
        assert data["display_name"] == "Bob Jones"
        assert data["has_memory"] is False  # No memory yet (just registered)

    def test_identify_phone_normalization(self, client):
        """Phone matching ignores dashes, spaces, parens."""
        _register(client, name="Carol White", phone="(555) 111-2222")
        res = client.post("/api/auth/identify", json={
            "full_name": "Carol White",
            "phone": "5551112222",  # No formatting
        })
        assert res.status_code == 200
        assert res.json()["identified"] is True

    def test_identify_case_insensitive_name(self, client):
        """Name matching is case-insensitive."""
        _register(client, name="Dave Brown", phone="555-333-4444")
        res = client.post("/api/auth/identify", json={
            "full_name": "dave brown",
            "phone": "555-333-4444",
        })
        assert res.status_code == 200
        assert res.json()["identified"] is True

    def test_identify_creates_new_when_not_found(self, client):
        """Identification creates a lightweight user when no match found."""
        res = client.post("/api/auth/identify", json={
            "full_name": "New Person",
            "phone": "555-000-0000",
        })
        assert res.status_code == 200
        data = res.json()
        # Creates a new record but identified=False since they weren't an existing match
        assert data["identified"] is False
        assert data["user_id"]  # still creates a user_id
        assert data["display_name"] == "New Person"

    def test_identify_wrong_name_same_phone(self, client):
        """Phone match with wrong name does not match."""
        _register(client, name="Eve Green", phone="555-777-8888")
        res = client.post("/api/auth/identify", json={
            "full_name": "Wrong Name",
            "phone": "555-777-8888",
        })
        assert res.status_code == 200
        # Should NOT match the existing user — will create a new record
        data = res.json()
        assert data["display_name"] == "Wrong Name"


# ===========================================================================
#  Memory Merge Tests
# ===========================================================================

class TestMemoryMerge:

    def test_register_with_visitor_id_merges_sessions(self, client):
        """Registering with a visitor_id merges that visitor's sessions."""
        # First, create an anonymous session with a visitor_id
        visitor_id = str(uuid.uuid4())
        sess_res = client.post("/api/sessions", json={
            "pre_conviction": 5,
            "selected_bot": "sally_nepq",
            "visitor_id": visitor_id,
        })
        assert sess_res.status_code == 200
        session_id = sess_res.json()["session_id"]

        # Now register and pass the same visitor_id
        reg_res = client.post("/api/auth/register", json={
            "email": "merge@test.com",
            "password": "password123",
            "display_name": "Merge User",
            "visitor_id": visitor_id,
        })
        assert reg_res.status_code == 200
        user_id = reg_res.json()["user_id"]

        # Verify the session is now linked to the user
        from app.database import _get_session_local, DBSession
        db = _get_session_local()()
        try:
            session = db.query(DBSession).filter(DBSession.id == session_id).first()
            assert session is not None
            assert session.user_id == user_id
        finally:
            db.close()

    def test_login_with_visitor_id_merges_sessions(self, client):
        """Logging in with a visitor_id merges that visitor's sessions."""
        # Register user first
        _register(client, email="loginmerge@test.com")

        # Create anonymous session with a different visitor_id
        visitor_id = str(uuid.uuid4())
        sess_res = client.post("/api/sessions", json={
            "pre_conviction": 3,
            "selected_bot": "ivy_informs",
            "visitor_id": visitor_id,
        })
        assert sess_res.status_code == 200
        session_id = sess_res.json()["session_id"]

        # Login with that visitor_id
        login_res = _login(client, email="loginmerge@test.com", visitor_id=visitor_id)
        assert login_res.status_code == 200
        user_id = login_res.json()["user_id"]

        # Verify session was merged
        from app.database import _get_session_local, DBSession
        db = _get_session_local()()
        try:
            session = db.query(DBSession).filter(DBSession.id == session_id).first()
            assert session is not None
            assert session.user_id == user_id
        finally:
            db.close()


# ===========================================================================
#  Token Validation Edge Cases
# ===========================================================================

class TestTokenEdgeCases:

    def test_raw_token_without_bearer_prefix(self, client):
        """Authorization header without 'Bearer ' prefix should still work."""
        reg = _register(client)
        token = reg.json()["token"]
        res = client.get("/api/auth/me", headers={"Authorization": token})
        assert res.status_code == 200

    def test_session_with_invalid_token_still_works(self, client):
        """Creating a session with an invalid auth token doesn't block — treated as anonymous."""
        res = client.post("/api/sessions", json={
            "pre_conviction": 5,
            "selected_bot": "sally_nepq",
            "visitor_id": str(uuid.uuid4()),
        }, headers={"Authorization": "Bearer invalid.token"})
        assert res.status_code == 200
