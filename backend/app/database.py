from sqlalchemy import create_engine, Column, String, Float, Integer, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"))

DATABASE_URL = os.environ["DATABASE_URL"]

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


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()