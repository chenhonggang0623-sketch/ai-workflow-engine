import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, String, Text, DateTime, Float, Integer, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.db import Base


class Workflow(Base):
    __tablename__ = "workflows"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    version = Column(String(20), default="1.0.0")
    definition = Column(JSON, nullable=False)
    status = Column(String(20), default="draft")
    created_by = Column(String(255))
    created_at = Column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), onupdate=lambda: datetime.now(UTC).replace(tzinfo=None))

    executions = relationship("Execution", back_populates="workflow", cascade="all, delete-orphan")


class Execution(Base):
    __tablename__ = "executions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflows.id"), nullable=False)
    status = Column(String(20), default="pending")
    context = Column(JSON, default=dict)
    replan_count = Column(Integer, default=0)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))

    workflow = relationship("Workflow", back_populates="executions")
    node_executions = relationship("NodeExecution", back_populates="execution", cascade="all, delete-orphan")
    logs = relationship("ExecutionLog", back_populates="execution", cascade="all, delete-orphan")


class NodeExecution(Base):
    __tablename__ = "node_executions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_id = Column(UUID(as_uuid=True), ForeignKey("executions.id"), nullable=False)
    node_id = Column(String(255), nullable=False)
    node_type = Column(String(50), nullable=False)
    status = Column(String(20), default="pending")
    input = Column(JSON)
    output = Column(JSON)
    error = Column(Text)
    retry_count = Column(Integer, default=0)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)

    execution = relationship("Execution", back_populates="node_executions")


class ExecutionLog(Base):
    __tablename__ = "execution_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    execution_id = Column(UUID(as_uuid=True), ForeignKey("executions.id"), nullable=False)
    node_execution_id = Column(UUID(as_uuid=True), ForeignKey("node_executions.id"))
    level = Column(String(20), default="info")
    message = Column(Text, nullable=False)
    log_metadata = Column("metadata", JSON)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))

    execution = relationship("Execution", back_populates="logs")
