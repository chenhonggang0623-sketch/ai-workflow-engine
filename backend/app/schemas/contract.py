from datetime import datetime
from uuid import UUID

from pydantic import ConfigDict, BaseModel, Field


class ContractCreate(BaseModel):
    contract_type: str
    issuer_id: str
    executor_id: str
    task_name: str = Field(..., max_length=500)
    task_description: str = ""
    input_schema: dict | None = None
    output_schema: dict | None = None
    acceptance_criteria: list[dict] = []
    model_params: dict | None = Field(None, alias="model_config")
    timeout_seconds: int = 300


class ContractResponse(BaseModel):
    id: UUID
    contract_type: str
    issuer_id: str
    executor_id: str
    task_name: str
    status: str
    priority: int
    issued_at: datetime
    accepted_at: datetime | None
    completed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)
