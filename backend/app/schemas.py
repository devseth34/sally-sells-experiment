from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field
import time
import uuid


class NepqPhase(str, Enum):
    CONNECTION = "CONNECTION"
    SITUATION = "SITUATION"
    PROBLEM_AWARENESS = "PROBLEM_AWARENESS"
    SOLUTION_AWARENESS = "SOLUTION_AWARENESS"
    CONSEQUENCE = "CONSEQUENCE"
    OWNERSHIP = "OWNERSHIP"
    COMMITMENT = "COMMITMENT"
    TERMINATED = "TERMINATED"


class SessionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


# API Request Models
class CreateSessionRequest(BaseModel):
    pre_conviction: int = Field(..., ge=1, le=10, description="Pre-chat conviction score 1-10")


class SendMessageRequest(BaseModel):
    content: str = Field(..., min_length=1)


# API Response Models
class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    timestamp: float
    phase: str
    
    class Config:
        from_attributes = True


class CreateSessionResponse(BaseModel):
    session_id: str
    current_phase: str
    pre_conviction: int
    greeting: MessageResponse


class SendMessageResponse(BaseModel):
    user_message: MessageResponse
    assistant_message: MessageResponse
    current_phase: str
    previous_phase: str
    phase_changed: bool
    session_ended: bool


class SessionDetailResponse(BaseModel):
    id: str
    status: str
    current_phase: str
    pre_conviction: Optional[int]
    post_conviction: Optional[int]
    start_time: float
    end_time: Optional[float]
    messages: List[MessageResponse]
    
    class Config:
        from_attributes = True


class SessionListItem(BaseModel):
    id: str
    status: str
    current_phase: str
    pre_conviction: Optional[int]
    message_count: int
    start_time: float
    end_time: Optional[float]


class MetricsResponse(BaseModel):
    total_sessions: int
    active_sessions: int
    completed_sessions: int
    abandoned_sessions: int
    average_pre_conviction: Optional[float]
    conversion_rate: float
    phase_distribution: dict
    failure_modes: List[dict]