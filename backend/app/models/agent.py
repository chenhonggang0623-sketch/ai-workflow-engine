import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.db import Base


class Agent(Base):
    __tablename__ = "agents"

    id = Column(String(255), primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    definition = Column(JSON, nullable=False)
    status = Column(String(20), default="active")
    created_at = Column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), onupdate=lambda: datetime.now(UTC).replace(tzinfo=None))

    skills = relationship("Skill", secondary="agent_skills", back_populates="agents")


class Skill(Base):
    __tablename__ = "skills"

    id = Column(String(255), primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    type = Column(String(50), default="python")
    code = Column(Text)
    parameters = Column(JSON)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), onupdate=lambda: datetime.now(UTC).replace(tzinfo=None))

    agents = relationship("Agent", secondary="agent_skills", back_populates="skills")


class AgentSkill(Base):
    __tablename__ = "agent_skills"

    agent_id = Column(String(255), ForeignKey("agents.id"), primary_key=True)
    skill_id = Column(String(255), ForeignKey("skills.id"), primary_key=True)
