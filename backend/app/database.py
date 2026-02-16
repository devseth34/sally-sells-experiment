from sqlalchemy import create_engine, Column, String, Float, Integer, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import logging
import os
import time

# Single dotenv load for the entire app — other modules should NOT call load_dotenv()
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"))

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


class DBMessage(Base):
    __tablename__ = "messages"
    id = Column(String, primary_key=True)
    session_id = Column(String, index=True)
    role = Column(String)
    content = Column(String)
    timestamp = Column(Float)
    phase = Column(String)


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
        }
        applied = 0
        for col_name, sql in migrations.items():
            if col_name not in existing_columns:
                conn.execute(text(sql))
                applied += 1
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