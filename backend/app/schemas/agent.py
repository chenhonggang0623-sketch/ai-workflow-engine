from datetime import datetime

from pydantic import ConfigDict, BaseModel, Field


class AgentCreate(BaseModel):
    id: str = Field(..., max_length=255)
    name: str = Field(..., max_length=255)
    description: str = ""
    definition: dict


class AgentResponse(BaseModel):
    id: str
    name: str
    description: str
    status: str
    definition: dict
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
