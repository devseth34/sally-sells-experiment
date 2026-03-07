"""
Sally Sells — Authentication Module

Simple JWT-based auth with email/password registration and login.
Tokens are stateless — no session store needed on the server.
"""
from __future__ import annotations

import os
import time
import uuid
import logging
from typing import Optional

from fastapi import HTTPException, Depends, Header
import bcrypt
from jose import jwt, JWTError
from sqlalchemy.orm import Session as DBSessionType

from app.database import DBUser, get_db

logger = logging.getLogger("sally.auth")

# JWT configuration
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "sally-sells-dev-secret-change-in-production")
ALGORITHM = "HS256"
TOKEN_EXPIRE_SECONDS = 86400 * 30  # 30 days


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": time.time() + TOKEN_EXPIRE_SECONDS,
        "iat": time.time(),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token. Raises HTTPException on failure."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("exp", 0) < time.time():
            raise HTTPException(status_code=401, detail="Token expired")
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


def get_optional_user(
    authorization: Optional[str] = Header(default=None),
    db: DBSessionType = Depends(get_db),
) -> Optional[DBUser]:
    """
    Extract user from Authorization header if present.
    Returns None for anonymous users — does NOT raise errors.
    This is the primary dependency for endpoints that work for both
    authenticated and anonymous users.
    """
    if not authorization:
        return None

    # Support both "Bearer <token>" and raw token
    token = authorization
    if token.startswith("Bearer "):
        token = token[7:]

    try:
        payload = decode_token(token)
        user_id = payload.get("sub")
        if not user_id:
            return None
        user = db.query(DBUser).filter(DBUser.id == user_id, DBUser.is_active == 1).first()
        return user
    except HTTPException:
        return None  # Invalid token = treat as anonymous, don't block


def get_required_user(
    authorization: Optional[str] = Header(default=None),
    db: DBSessionType = Depends(get_db),
) -> DBUser:
    """
    Extract user from Authorization header. Raises 401 if not authenticated.
    Use this for endpoints that REQUIRE authentication.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Authentication required")

    token = authorization
    if token.startswith("Bearer "):
        token = token[7:]

    payload = decode_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    user = db.query(DBUser).filter(DBUser.id == user_id, DBUser.is_active == 1).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def register_user(
    db: DBSessionType,
    email: str,
    password: str,
    display_name: Optional[str] = None,
    phone: Optional[str] = None,
) -> DBUser:
    """Create a new user account. Raises HTTPException if email already exists."""
    # Check for existing email
    existing = db.query(DBUser).filter(DBUser.email == email.lower().strip()).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = DBUser(
        id=str(uuid.uuid4()),
        email=email.lower().strip(),
        password_hash=hash_password(password),
        display_name=display_name,
        phone=phone.strip() if phone else None,
        created_at=time.time(),
        last_login_at=time.time(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info(f"User registered: {user.email} (id={user.id[:8]})")
    return user


def login_user(db: DBSessionType, email: str, password: str) -> DBUser:
    """Authenticate a user by email/password. Raises HTTPException on failure."""
    user = db.query(DBUser).filter(
        DBUser.email == email.lower().strip(),
        DBUser.is_active == 1,
    ).first()

    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    user.last_login_at = time.time()
    db.commit()
    return user


def merge_visitor_memory_to_user(
    db: DBSessionType,
    visitor_id: str,
    user_id: str,
):
    """
    Merge all memory from a visitor_id to a user_id.
    Called when an anonymous visitor creates an account or logs in.
    This links their prior conversations and memory to their account.
    """
    from app.database import DBSession, DBMemoryFact, DBSessionSummary

    # Update sessions
    sessions_updated = (
        db.query(DBSession)
        .filter(DBSession.visitor_id == visitor_id, DBSession.user_id.is_(None))
        .update({"user_id": user_id})
    )

    # Update memory facts
    facts_updated = (
        db.query(DBMemoryFact)
        .filter(DBMemoryFact.visitor_id == visitor_id, DBMemoryFact.user_id.is_(None))
        .update({"user_id": user_id})
    )

    # Update session summaries
    summaries_updated = (
        db.query(DBSessionSummary)
        .filter(DBSessionSummary.visitor_id == visitor_id, DBSessionSummary.user_id.is_(None))
        .update({"user_id": user_id})
    )

    db.commit()
    logger.info(
        f"Merged visitor {visitor_id[:8]} -> user {user_id[:8]}: "
        f"{sessions_updated} sessions, {facts_updated} facts, {summaries_updated} summaries"
    )


def find_user_by_name_and_phone(
    db: DBSessionType,
    name: str,
    phone: str,
) -> Optional[DBUser]:
    """
    Look up a user by display_name + phone combination.
    Used for non-authenticated identification (Tier 2).
    Returns None if no match found.
    """
    import re
    normalized_phone = re.sub(r'[\s\-\(\)\+]', '', phone.strip())

    # Search for matching user
    users = db.query(DBUser).filter(DBUser.phone.isnot(None)).all()
    for user in users:
        user_phone_normalized = re.sub(r'[\s\-\(\)\+]', '', (user.phone or '').strip())
        if user_phone_normalized == normalized_phone:
            # Phone matches — check name (case-insensitive)
            if user.display_name and name.lower().strip() == user.display_name.lower().strip():
                return user
    return None
