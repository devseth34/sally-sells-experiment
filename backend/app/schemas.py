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


class BotArm(str, Enum):
    SALLY_NEPQ = "sally_nepq"
    HANK_HYPES = "hank_hypes"
    IVY_INFORMS = "ivy_informs"
    SALLY_HANK_CLOSE = "sally_hank_close"
    SALLY_IVY_BRIDGE = "sally_ivy_bridge"
    SALLY_EMPATHY_PLUS = "sally_empathy_plus"
    SALLY_DIRECT = "sally_direct"
    HANK_STRUCTURED = "hank_structured"


# API Request Models
class CreateSessionRequest(BaseModel):
    pre_conviction: int = Field(..., ge=1, le=10, description="Pre-chat conviction score 1-10")
    selected_bot: Optional[BotArm] = Field(default=None, description="Which bot to talk to (None = random assignment)")
    visitor_id: Optional[str] = Field(default=None, description="Persistent visitor identifier for memory/resumption")
    experiment_mode: bool = Field(default=False, description="If true, bot is randomly assigned and arm is hidden from user")
    participant_name: Optional[str] = Field(default=None, description="Participant's name")
    participant_email: Optional[str] = Field(default=None, description="Participant's email address")
    platform: Optional[str] = Field(default=None, description="Recruitment platform (prolific, mturk)")
    platform_participant_id: Optional[str] = Field(default=None, description="Participant ID from the recruitment platform")


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
    assigned_arm: str
    bot_display_name: str
    greeting: MessageResponse
    visitor_id: Optional[str] = None


class ResumeSessionResponse(BaseModel):
    session_id: str
    current_phase: str
    assigned_arm: str
    bot_display_name: str
    messages: List[MessageResponse]
    visitor_id: str
    can_resume: bool = True


class SendMessageResponse(BaseModel):
    user_message: MessageResponse
    assistant_message: MessageResponse
    current_phase: str
    previous_phase: str
    phase_changed: bool
    session_ended: bool
    engagement_gate_met: bool = False


class SessionDetailResponse(BaseModel):
    id: str
    status: str
    current_phase: str
    pre_conviction: Optional[int]
    post_conviction: Optional[int]
    start_time: float
    end_time: Optional[float]
    assigned_arm: Optional[str] = None
    messages: List[MessageResponse]
    
    class Config:
        from_attributes = True


class SessionListItem(BaseModel):
    id: str
    status: str
    current_phase: str
    pre_conviction: Optional[int]
    post_conviction: Optional[int]
    cds_score: Optional[int]
    message_count: int
    start_time: float
    end_time: Optional[float]
    assigned_arm: Optional[str] = None
    channel: Optional[str] = None
    phone_number: Optional[str] = None
    turn_number: Optional[int] = None
    followup_count: Optional[int] = None
    experiment_mode: Optional[str] = None


class PostConvictionRequest(BaseModel):
    post_conviction: int = Field(..., ge=1, le=10, description="Post-chat conviction score 1-10")


class PostConvictionResponse(BaseModel):
    session_id: str
    pre_conviction: Optional[int]
    post_conviction: int
    cds_score: int
    legitimacy_score: Optional[int] = None
    legitimacy_tier: Optional[str] = None


class MetricsResponse(BaseModel):
    total_sessions: int
    active_sessions: int
    completed_sessions: int
    abandoned_sessions: int
    average_pre_conviction: Optional[float]
    average_cds: Optional[float]
    conversion_rate: float
    phase_distribution: dict
    failure_modes: List[dict]


# --- Authentication Models ---

class RegisterRequest(BaseModel):
    email: str = Field(..., description="Email address")
    password: str = Field(..., min_length=6, description="Password (min 6 characters)")
    display_name: Optional[str] = Field(default=None, description="Full name")
    phone: Optional[str] = Field(default=None, description="Phone number")
    visitor_id: Optional[str] = Field(default=None, description="Existing visitor_id to merge memory from")


class LoginRequest(BaseModel):
    email: str = Field(..., description="Email address")
    password: str = Field(..., description="Password")
    visitor_id: Optional[str] = Field(default=None, description="Current visitor_id to merge on login")


class AuthResponse(BaseModel):
    token: str
    user_id: str
    email: str
    display_name: Optional[str] = None


class IdentifyRequest(BaseModel):
    """For non-authenticated identification via name + phone."""
    full_name: str = Field(..., min_length=1, description="Full name")
    phone: str = Field(..., min_length=6, description="Phone number")
    visitor_id: Optional[str] = Field(default=None, description="Current visitor_id")


class IdentifyResponse(BaseModel):
    identified: bool
    user_id: Optional[str] = None
    display_name: Optional[str] = None
    has_memory: bool = False