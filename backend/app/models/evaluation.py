import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, String, Text, DateTime, Float, Boolean, JSON, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from app.core.db import Base


class Evaluation(Base):
    __tablename__ = "evaluations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_id = Column(UUID(as_uuid=True), ForeignKey("executions.id"))
    node_execution_id = Column(UUID(as_uuid=True), ForeignKey("node_executions.id"))
    contract_id = Column(UUID(as_uuid=True), ForeignKey("task_contracts.id"))
    agent_id = Column(String(255), nullable=False)
    evaluator = Column(String(50), nullable=False)
    scores = Column(JSON, nullable=False)
    weighted_score = Column(Float, nullable=False)
    confidence = Column(Float)
    summary = Column(Text)
    strengths = Column(JSON, default=list)
    weaknesses = Column(JSON, default=list)
    suggestions = Column(JSON, default=list)
    passed = Column(Boolean, nullable=False)
    severity = Column(String(20), default="info")
    created_at = Column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))


class AgentPerformance(Base):
    __tablename__ = "agent_performance"

    agent_id = Column(String(255), primary_key=True)
    evaluation_count = Column(Integer, default=0)
    average_scores = Column(JSON, default=dict)
    score_trend = Column(String(20), default="stable")
    reliability = Column(Float, default=1.0)
    last_evaluation_at = Column(DateTime)
    weakness_patterns = Column(JSON, default=list)
