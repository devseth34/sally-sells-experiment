from sqlalchemy import create_engine, Column, String, Float, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sally_sells.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class DBSession(Base):
    __tablename__ = "sessions"
    id = Column(String, primary_key=True)
    status = Column(String, default="active")
    current_phase = Column(String, default="CONNECTION")
    pre_conviction = Column(Integer, nullable=True)
    post_conviction = Column(Integer, nullable=True)
    start_time = Column(Float)
    end_time = Column(Float, nullable=True)
    message_count = Column(Integer, default=0)
    messages_in_current_phase = Column(Integer, default=0)


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