from datetime import datetime
from uuid import UUID

from pydantic import ConfigDict, BaseModel


class ArtifactResponse(BaseModel):
    id: UUID
    name: str
    type: str
    mime_type: str | None
    size: int
    version: int
    status: str
    tags: list
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
