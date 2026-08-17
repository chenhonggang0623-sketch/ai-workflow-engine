import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, String, Text, DateTime, Integer, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID

from app.core.db import Base


class Blueprint(Base):
    """Blueprint — 架构规划的单一权威记录，版本化持久化。

    每次修订生成新版本（version+1），旧版本 status 置为 superseded。
    """

    __tablename__ = "blueprints"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflows.id"), nullable=True)
    source_execution_id = Column(
        UUID(as_uuid=True), ForeignKey("executions.id"), nullable=True
    )
    version = Column(Integer, default=1)
    status = Column(String(20), default="active")  # active / superseded
    content = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))


class ExecutionDecision(Base):
    """ExecutionDecision — 级联重规划耗尽后抛回用户的决策单。"""

    __tablename__ = "execution_decisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_id = Column(UUID(as_uuid=True), ForeignKey("executions.id"), nullable=False)
    reason = Column(Text)
    attempts = Column(Integer, default=3)
    options = Column(JSON, default=list)
    blueprint = Column(JSON)
    workflow = Column(JSON)
    status = Column(String(20), default="pending")  # pending / resolved
    resolved_action = Column(String(50))
    resolved_at = Column(DateTime)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))
