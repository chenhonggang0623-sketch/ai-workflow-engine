import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, String, DateTime, Integer, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID

from app.core.db import Base


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_id = Column(UUID(as_uuid=True), ForeignKey("executions.id"))
    message_type = Column(String(20), nullable=False)
    sender_id = Column(String(255), nullable=False)
    target_id = Column(String(255))
    correlation_id = Column(UUID(as_uuid=True))
    subject = Column(String(255), nullable=False)
    payload = Column(JSON)
    priority = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))
