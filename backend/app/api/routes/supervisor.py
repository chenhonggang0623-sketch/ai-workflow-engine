from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.supervisor.orchestrator import SupervisorOrchestrator
from app.supervisor.evaluation import EvaluationEngine
from app.supervisor.quality_gate import QualityGate
from app.supervisor.recovery import RecoveryManager
from app.contract.contract_manager import ContractManager
from app.agent.registry import AgentRegistry
from app.agent.runtime import AgentExecutor
from app.agent.llm_gateway import LLMGateway
from app.context.manager import ContextManager
from app.artifact.manager import ArtifactManager
from app.mcp.tool_registry import ToolRegistry
from app.models.evaluation import Evaluation
from app.schemas.evaluation import EvaluationResponse
from app.core.config import settings
from app.core.redis import get_redis

router = APIRouter()


def _build_orchestrator(db: AsyncSession, request: Request) -> SupervisorOrchestrator:
    llm: LLMGateway = request.app.state.llm_gateway
    tool_registry: ToolRegistry = request.app.state.tool_registry
    redis_client = get_redis()
    agent_registry = AgentRegistry(db)
    eval_engine = EvaluationEngine(db, llm)
    gate = QualityGate(eval_engine)
    cm = ContractManager(db, eval_engine)
    recovery = RecoveryManager(cm, agent_registry)
    agent_executor = AgentExecutor(agent_registry, llm, tool_registry)
    ctx_mgr = ContextManager(db, redis_client)
    artifact_mgr = ArtifactManager(db, settings.storage_path)
    from app.contract.communication_broker import CommunicationBroker
    broker = CommunicationBroker(db, redis_client)

    return SupervisorOrchestrator(
        db_session=db,
        evaluation_engine=eval_engine,
        quality_gate=gate,
        recovery_manager=recovery,
        contract_manager=cm,
        comm_broker=broker,
        agent_executor=agent_executor,
        context_manager=ctx_mgr,
        artifact_manager=artifact_mgr,
    )


@router.get("/executions/{id}/gates")
async def get_quality_gates(id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Evaluation).where(Evaluation.execution_id == id)
    )
    evaluations = result.scalars().all()
    if not evaluations:
        return {"execution_id": str(id), "gates": []}
    return {
        "execution_id": str(id),
        "gates": [
            {
                "id": str(e.id),
                "agent_id": e.agent_id,
                "score": e.weighted_score,
                "passed": e.passed,
                "severity": e.severity,
            }
            for e in evaluations
        ],
    }


@router.get("/executions/{id}/report")
async def get_execution_report(id: UUID, request: Request, db: AsyncSession = Depends(get_db)):
    orch = _build_orchestrator(db, request)
    progress = await orch.get_progress(id)
    result = await db.execute(
        select(Evaluation).where(Evaluation.execution_id == id)
    )
    evaluations = result.scalars().all()
    return {
        "progress": progress,
        "evaluations": [
            {
                "id": str(e.id),
                "agent_id": e.agent_id,
                "weighted_score": e.weighted_score,
                "passed": e.passed,
                "summary": e.summary,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in evaluations
        ],
    }


@router.get("/evaluations", response_model=list[EvaluationResponse])
async def get_evaluations(
    agent_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(Evaluation)
    if agent_id:
        query = query.where(Evaluation.agent_id == agent_id)
    query = query.order_by(Evaluation.created_at.desc())
    result = await db.execute(query)
    evaluations = result.scalars().all()
    return evaluations
