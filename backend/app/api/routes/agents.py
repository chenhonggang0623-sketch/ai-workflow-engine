from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.agent.registry import AgentRegistry
from app.schemas.agent import AgentCreate, AgentResponse

router = APIRouter()


@router.get("", response_model=list[AgentResponse])
async def list_agents(
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    registry = AgentRegistry(db)
    agents = await registry.list(status=status)
    return agents


@router.post("", response_model=AgentResponse, status_code=201)
async def register_agent(body: AgentCreate, db: AsyncSession = Depends(get_db)):
    registry = AgentRegistry(db)
    agent = await registry.register(
        agent_id=body.id,
        name=body.name,
        description=body.description,
        definition=body.definition,
    )
    return agent


@router.get("/{id}", response_model=AgentResponse)
async def get_agent(id: str, db: AsyncSession = Depends(get_db)):
    registry = AgentRegistry(db)
    agent = await registry.get(id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return agent


@router.delete("/{id}", status_code=204)
async def delete_agent(id: str, db: AsyncSession = Depends(get_db)):
    registry = AgentRegistry(db)
    agent = await registry.get(id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    await registry.delete(id)
