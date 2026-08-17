from datetime import datetime
from uuid import UUID

from pydantic import ConfigDict, BaseModel, Field


class BlueprintSummary(BaseModel):
    id: UUID
    workflow_id: UUID | None
    source_execution_id: UUID | None
    version: int
    status: str
    created_at: datetime


class BlueprintResponse(BaseModel):
    id: UUID
    workflow_id: UUID | None
    source_execution_id: UUID | None
    version: int
    status: str
    content: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BlueprintListResponse(BaseModel):
    workflow_id: UUID
    versions: list[BlueprintResponse]


class BlueprintReviseRequest(BaseModel):
    feedback: str = Field(..., description="修订反馈/失败原因")


class ExecutionDecisionResponse(BaseModel):
    id: UUID
    execution_id: UUID
    reason: str | None
    attempts: int
    options: list[str]
    blueprint: dict | None
    workflow: dict | None
    status: str
    resolved_action: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ResolveRequest(BaseModel):
    action: str = Field(..., description="retry / revise_blueprint / abandon")
    feedback: str | None = None
    blueprint: dict | None = None
