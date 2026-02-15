from sqlalchemy import create_engine, Column, String, Float, Integer, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"))

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set. Set it in your .env file or hosting platform.")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


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
    Base.metadata.create_all(bind=engine)
    # Migrate: add new columns if they don't exist (safe for existing DBs)
    from sqlalchemy import text, inspect
    inspector = inspect(engine)
    existing_columns = {col["name"] for col in inspector.get_columns("sessions")}
    with engine.connect() as conn:
        migrations = {
            "consecutive_no_new_info": "ALTER TABLE sessions ADD COLUMN consecutive_no_new_info INTEGER DEFAULT 0",
            "turns_in_current_phase": "ALTER TABLE sessions ADD COLUMN turns_in_current_phase INTEGER DEFAULT 0",
            "deepest_emotional_depth": "ALTER TABLE sessions ADD COLUMN deepest_emotional_depth VARCHAR DEFAULT 'surface'",
            "objection_diffusion_step": "ALTER TABLE sessions ADD COLUMN objection_diffusion_step INTEGER DEFAULT 0",
            "ownership_substep": "ALTER TABLE sessions ADD COLUMN ownership_substep INTEGER DEFAULT 0",
        }
        for col_name, sql in migrations.items():
            if col_name not in existing_columns:
                conn.execute(text(sql))
        conn.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()