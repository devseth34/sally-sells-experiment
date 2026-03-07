from sqlalchemy import create_engine, Column, String, Float, Integer, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import logging
import os
import time

# Single dotenv load for the entire app — other modules should NOT call load_dotenv()
# override=True ensures .env values take precedence over empty/stale system env vars
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"), override=True)

logger = logging.getLogger("sally.startup")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set. Set it in your .env file or hosting platform.")

# Lazy engine — only created when first accessed
_engine = None
_SessionLocal = None
Base = declarative_base()


def _get_engine():
    global _engine
    if _engine is None:
        t0 = time.monotonic()
        _engine = create_engine(
            DATABASE_URL,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
        ms = (time.monotonic() - t0) * 1000
        logger.info(f"create_engine() took {ms:.0f}ms")
    return _engine


def _get_session_local():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_get_engine())
    return _SessionLocal


class DBUser(Base):
    """Registered user account for persistent cross-device memory."""
    __tablename__ = "users"
    id = Column(String, primary_key=True)           # UUID
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    display_name = Column(String, nullable=True)
    phone = Column(String, nullable=True, index=True)
    created_at = Column(Float, nullable=False)
    last_login_at = Column(Float, nullable=True)
    is_active = Column(Integer, default=1)  # 1=active, 0=disabled. Integer for SQLite compat.


class DBSession(Base):
    __tablename__ = "sessions"
    id = Column(String, primary_key=True)
    status = Column(String, default="active")
    current_phase = Column(String, default="CONNECTION")
    pre_conviction = Column(Integer, nullable=True)
    post_conviction = Column(Integer, nullable=True)
    cds_score = Column(Integer, nullable=True)
    start_time = Column(Float)
    end_time = Column(Float, nullable=True)
    message_count = Column(Integer, default=0)

    # Three-layer architecture fields
    retry_count = Column(Integer, default=0)
    turn_number = Column(Integer, default=0)
    consecutive_no_new_info = Column(Integer, default=0)
    turns_in_current_phase = Column(Integer, default=0)
    deepest_emotional_depth = Column(String, default="surface")
    objection_diffusion_step = Column(Integer, default=0)
    ownership_substep = Column(Integer, default=0)
    prospect_profile = Column(Text, default="{}")
    thought_logs = Column(Text, default="[]")
    escalation_sent = Column(String, nullable=True)

    # Phase 1B: Multi-bot experiment
    assigned_arm = Column(String, nullable=True)  # 'sally_nepq', 'hank_hypes', 'ivy_informs'

    # Persistent memory: visitor identity
    visitor_id = Column(String, nullable=True, index=True)

    # User authentication
    user_id = Column(String, nullable=True, index=True)  # FK to users.id (nullable for anonymous)


class DBMessage(Base):
    __tablename__ = "messages"
    id = Column(String, primary_key=True)
    session_id = Column(String, index=True)
    role = Column(String)
    content = Column(String)
    timestamp = Column(Float)
    phase = Column(String)


class DBMemoryFact(Base):
    """Long-term memory: individual facts extracted from conversations."""
    __tablename__ = "memory_facts"
    id = Column(String, primary_key=True)
    visitor_id = Column(String, index=True, nullable=False)
    user_id = Column(String, nullable=True, index=True)  # Set when user is authenticated
    source_session_id = Column(String, nullable=False)
    category = Column(String, nullable=False)  # identity, situation, pain_point, preference, objection_history
    fact_key = Column(String, nullable=False)   # e.g., "name", "role", "company"
    fact_value = Column(Text, nullable=False)
    confidence = Column(Float, default=1.0)
    created_at = Column(Float, nullable=False)
    updated_at = Column(Float, nullable=False)
    is_active = Column(Integer, default=1)  # 1=active, 0=superseded. Using Integer for SQLite compat.


class DBSessionSummary(Base):
    """Long-term memory: per-session summaries for quick context loading."""
    __tablename__ = "session_summaries"
    id = Column(String, primary_key=True)
    visitor_id = Column(String, index=True, nullable=False)
    user_id = Column(String, nullable=True, index=True)
    session_id = Column(String, nullable=False)
    summary_text = Column(Text, nullable=False)
    outcome = Column(String, nullable=False)  # completed, abandoned, chose_free, chose_paid, hard_no
    final_phase = Column(String, nullable=False)
    key_pain_points = Column(Text, default="[]")  # JSON array
    key_objections = Column(Text, default="[]")    # JSON array
    created_at = Column(Float, nullable=False)


def init_db():
    """Initialize database schema.
    
    Set SKIP_SCHEMA_CHECK=true in production to skip create_all() and migration
    checks on every startup. This drops cold start from ~10s to <500ms.
    
    When you change the schema, either:
    - Temporarily unset SKIP_SCHEMA_CHECK and redeploy, or
    - Run migrations manually via: python -c "from app.database import init_db; init_db()"
      with SKIP_SCHEMA_CHECK unset
    """
    if os.getenv("SKIP_SCHEMA_CHECK", "false").lower() == "true":
        logger.info("init_db: SKIPPED (SKIP_SCHEMA_CHECK=true)")
        return

    eng = _get_engine()

    t0 = time.monotonic()
    Base.metadata.create_all(bind=eng)
    create_all_ms = (time.monotonic() - t0) * 1000
    logger.info(f"init_db: create_all took {create_all_ms:.0f}ms")

    # Migrate: add new columns if they don't exist (safe for existing DBs)
    t1 = time.monotonic()
    from sqlalchemy import text, inspect
    inspector = inspect(eng)
    existing_columns = {col["name"] for col in inspector.get_columns("sessions")}
    with eng.connect() as conn:
        migrations = {
            "consecutive_no_new_info": "ALTER TABLE sessions ADD COLUMN consecutive_no_new_info INTEGER DEFAULT 0",
            "turns_in_current_phase": "ALTER TABLE sessions ADD COLUMN turns_in_current_phase INTEGER DEFAULT 0",
            "deepest_emotional_depth": "ALTER TABLE sessions ADD COLUMN deepest_emotional_depth VARCHAR DEFAULT 'surface'",
            "objection_diffusion_step": "ALTER TABLE sessions ADD COLUMN objection_diffusion_step INTEGER DEFAULT 0",
            "ownership_substep": "ALTER TABLE sessions ADD COLUMN ownership_substep INTEGER DEFAULT 0",
            "assigned_arm": "ALTER TABLE sessions ADD COLUMN assigned_arm VARCHAR",
            "visitor_id": "ALTER TABLE sessions ADD COLUMN visitor_id VARCHAR",
            "user_id": "ALTER TABLE sessions ADD COLUMN user_id VARCHAR",
        }
        applied = 0
        for col_name, sql in migrations.items():
            if col_name not in existing_columns:
                conn.execute(text(sql))
                applied += 1

        # Create indexes for sessions columns
        for idx_sql in [
            "CREATE INDEX IF NOT EXISTS ix_sessions_visitor_id ON sessions (visitor_id)",
            "CREATE INDEX IF NOT EXISTS ix_sessions_user_id ON sessions (user_id)",
        ]:
            try:
                conn.execute(text(idx_sql))
            except Exception:
                pass

        # Migrate: add user_id to memory_facts and session_summaries
        # These tables already exist in production, so create_all() won't add the new column
        try:
            mf_cols = {col["name"] for col in inspector.get_columns("memory_facts")}
            if "user_id" not in mf_cols:
                conn.execute(text("ALTER TABLE memory_facts ADD COLUMN user_id VARCHAR"))
                applied += 1
            try:
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_memory_facts_user_id ON memory_facts (user_id)"))
            except Exception:
                pass
        except Exception:
            pass  # Table may not exist yet (create_all handles it)

        try:
            ss_cols = {col["name"] for col in inspector.get_columns("session_summaries")}
            if "user_id" not in ss_cols:
                conn.execute(text("ALTER TABLE session_summaries ADD COLUMN user_id VARCHAR"))
                applied += 1
            try:
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_session_summaries_user_id ON session_summaries (user_id)"))
            except Exception:
                pass
        except Exception:
            pass  # Table may not exist yet (create_all handles it)

        conn.commit()
    migration_ms = (time.monotonic() - t1) * 1000
    logger.info(f"init_db: migration check took {migration_ms:.0f}ms ({applied} applied)")
    logger.info(f"init_db: TOTAL {create_all_ms + migration_ms:.0f}ms")


def get_db():
    session_local = _get_session_local()
    db = session_local()
    try:
        yield db
    finally:
        db.close()