from uuid import UUID

from pydantic import BaseModel, Field


class PlanRequest(BaseModel):
    requirement: str = Field(..., description="用户需求描述")
    constraints: dict = Field(default_factory=dict)


class PlanResponse(BaseModel):
    plan: dict  # Workflow JSON
    blueprint: dict | None = None  # {id, version, content} 或 {content}
    explanation: str
    estimated_duration_seconds: int | None = None
    complexity_analysis: dict | None = None


class PlanConfirm(BaseModel):
    approved: bool = True
    modifications: dict | None = None
    blueprint_id: UUID | None = None
