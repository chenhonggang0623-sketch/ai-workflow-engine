import logging

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent

logger = logging.getLogger(__name__)


class AgentRegistry:
    def __init__(self, db_session: AsyncSession):
        self._db = db_session

    async def register(
        self, agent_id: str, name: str, description: str, definition: dict
    ) -> Agent:
        existing = await self.get(agent_id)
        if existing:
            agent = await self._db.get(Agent, agent_id)
            if agent:
                agent.name = name
                agent.description = description
                agent.definition = definition
                self._db.add(agent)
                await self._db.flush()
                return agent

        agent = Agent(
            id=agent_id,
            name=name,
            description=description,
            definition=definition,
            status="active",
        )
        self._db.add(agent)
        await self._db.flush()
        logger.info("Registered agent: %s (%s)", agent_id, name)
        return agent

    async def get(self, agent_id: str) -> dict | None:
        result = await self._db.execute(
            select(Agent).where(Agent.id == agent_id)
        )
        agent = result.scalar_one_or_none()
        if agent is None:
            return None
        return {
            "id": agent.id,
            "name": agent.name,
            "description": agent.description,
            "definition": agent.definition,
            "status": agent.status,
            "created_at": agent.created_at.isoformat() if agent.created_at else None,
            "updated_at": agent.updated_at.isoformat() if agent.updated_at else None,
        }

    async def list_agents(self, status: str | None = None) -> list[dict]:
        query = select(Agent)
        if status:
            query = query.where(Agent.status == status)
        result = await self._db.execute(query.order_by(Agent.created_at))
        agents = result.scalars().all()
        return [
            {
                "id": a.id,
                "name": a.name,
                "description": a.description,
                "definition": a.definition,
                "status": a.status,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "updated_at": a.updated_at.isoformat() if a.updated_at else None,
            }
            for a in agents
        ]

    async def delete(self, agent_id: str) -> None:
        await self._db.execute(delete(Agent).where(Agent.id == agent_id))
        await self._db.flush()
        logger.info("Deleted agent: %s", agent_id)
