from datetime import datetime
from uuid import UUID

from pydantic import ConfigDict, BaseModel, Field


class WorkflowCreate(BaseModel):
    name: str = Field(..., max_length=255)
    description: str = ""
    definition: dict = Field(default_factory=lambda: {"nodes": [], "edges": []})


class WorkflowUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    definition: dict | None = None


class WorkflowResponse(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    version: str
    status: str
    definition: dict
    created_by: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ExecutionResponse(BaseModel):
    id: UUID
    workflow_id: UUID
    status: str
    context: dict
    replan_count: int = 0
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NodeExecutorUpdate(BaseModel):
    executor_type: str = "llm_api"
    executor_config: dict = {}
    provider: str | None = None
    system_prompt: str | None = None


class NodeExecutionResponse(BaseModel):
    id: UUID
    execution_id: UUID
    node_id: str
    node_type: str
    status: str
    input: dict | None
    output: dict | None
    error: str | None
    retry_count: int
    started_at: datetime | None
    finished_at: datetime | None
    slow: bool = False
    slow_elapsed_seconds: int | None = None

    model_config = ConfigDict(from_attributes=True)
