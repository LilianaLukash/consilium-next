from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Phase(str, Enum):
    INDEPENDENT = "independent"
    DEBATE = "debate"
    REVIEW = "review"
    SYNTHESIS = "synthesis"
    REVISION = "revision"
    COMPLETE = "complete"
    ERROR = "error"


class AgentId(str, Enum):
    DIATOR = "diator"
    ARCHITECT = "architect"
    CRITIC = "critic"
    VISIONARY = "visionary"


class AgentMessage(BaseModel):
    agent_id: AgentId
    phase: Phase
    round: int = 0
    content: str
    model: str
    tokens_estimate: int | None = None


class SessionState(BaseModel):
    session_id: str
    user_prompt: str
    goal: str = ""
    phase: Phase = Phase.INDEPENDENT
    current_round: int = 0
    messages: list[AgentMessage] = Field(default_factory=list)
    compressed_context: str = ""
    attachments_context: str = ""
    user_comment: str | None = None
    verdict_version: int = 1
    final_verdict: str | None = None
    error: str | None = None


class CouncilConfigBody(BaseModel):
    price_threshold: float = 10.0
    preset: str = "balanced"
    models: dict[str, str] = Field(default_factory=dict)


class RunRequest(BaseModel):
    prompt: str = Field(..., min_length=10, max_length=32000)
    max_debate_rounds: int | None = None
    session_id: str | None = None
    council_config: CouncilConfigBody | None = None


class ReviseRequest(BaseModel):
    comment: str = Field(..., min_length=5, max_length=16000)
    max_debate_rounds: int | None = 1


class StreamEvent(BaseModel):
    type: str
    data: dict[str, Any]
