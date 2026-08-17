from datetime import datetime
from uuid import UUID

from pydantic import ConfigDict, BaseModel


class EvaluationResponse(BaseModel):
    id: UUID
    agent_id: str
    evaluator: str
    scores: dict
    weighted_score: float
    summary: str
    passed: bool
    severity: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
