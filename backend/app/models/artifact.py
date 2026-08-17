import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, String, Text, DateTime, Integer, ForeignKey, JSON, BigInteger
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.db import Base


class Artifact(Base):
    __tablename__ = "artifacts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_id = Column(UUID(as_uuid=True), ForeignKey("executions.id"))
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflows.id"))
    node_id = Column(String(255))
    name = Column(String(500), nullable=False)
    type = Column(String(50), nullable=False)
    mime_type = Column(String(100))
    size = Column(BigInteger, default=0)
    storage_path = Column(Text, nullable=False)
    version = Column(Integer, default=1)
    parent_id = Column(UUID(as_uuid=True), ForeignKey("artifacts.id"))
    checksum = Column(String(64))
    status = Column(String(20), default="draft")
    tags = Column(JSON, default=list)
    extra_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))
