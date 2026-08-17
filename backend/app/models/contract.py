import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, String, Text, DateTime, Integer, Float, ForeignKey, JSON, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.db import Base


class TaskContract(Base):
    __tablename__ = "task_contracts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_id = Column(UUID(as_uuid=True), ForeignKey("executions.id"))
    parent_contract_id = Column(UUID(as_uuid=True), ForeignKey("task_contracts.id"))
    contract_type = Column(String(50), nullable=False)
    issuer_id = Column(String(255), nullable=False)
    executor_id = Column(String(255), nullable=False)
    task_name = Column(String(500), nullable=False)
    task_description = Column(Text)
    priority = Column(Integer, default=0)
    input_schema = Column(JSON)
    output_schema = Column(JSON)
    acceptance_criteria = Column(JSON, nullable=False)
    model_config = Column(JSON)
    max_tokens = Column(Integer)
    deadline = Column(DateTime)
    timeout_seconds = Column(Integer)
    dependencies = Column(JSON, default=list)
    retry_config = Column(JSON)
    status = Column(String(20), default="pending")
    result = Column(JSON)
    evaluation_id = Column(UUID(as_uuid=True), ForeignKey("evaluations.id"))
    issued_at = Column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))
    accepted_at = Column(DateTime)
    completed_at = Column(DateTime)
