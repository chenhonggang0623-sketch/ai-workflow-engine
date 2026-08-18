import asyncio
import os
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db, async_session_factory
from app.models.workflow import Workflow, Execution, ExecutionLog, NodeExecution
from app.models.blueprint import ExecutionDecision
from app.schemas.workflow import ExecutionResponse, NodeExecutionResponse
from app.schemas.blueprint import ExecutionDecisionResponse, ResolveRequest
from app.engine.execution_manager import ExecutionManager
from app.agent.registry import AgentRegistry
from app.planner.planner_agent import PlannerAgent
from app.planner.architect import Architect
from app.planner.replan_coordinator import ReplanCoordinator
from app.planner.workspace import inject_workspace
import asyncio

router = APIRouter()


@router.get("")
async def list_executions(
    workflow_id: UUID | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """列出执行记录（含工作流名称），支持按 workflow_id / status 过滤。"""
    query = (
        select(Execution, Workflow.name)
        .join(Workflow, Execution.workflow_id == Workflow.id)
        .order_by(Execution.created_at.desc())
        .limit(min(limit, 200))
        .offset(offset)
    )
    if workflow_id:
        query = query.where(Execution.workflow_id == workflow_id)
    if status:
        query = query.where(Execution.status == status)

    result = await db.execute(query)
    rows = result.all()
    return [
        {
            "id": str(exe.id),
            "workflow_id": str(exe.workflow_id),
            "workflow_name": wf_name,
            "status": exe.status,
            "replan_count": exe.replan_count,
            "started_at": exe.started_at.isoformat() if exe.started_at else None,
            "finished_at": exe.finished_at.isoformat() if exe.finished_at else None,
            "created_at": exe.created_at.isoformat() if exe.created_at else None,
        }
        for exe, wf_name in rows
    ]


def _walk_project(project_path: str) -> list[dict]:
    files = []
    for root, dirs, names in os.walk(project_path):
        dirs.sort()
        for name in sorted(names):
            abs_path = os.path.join(root, name)
            rel_path = os.path.relpath(abs_path, project_path).replace("\\", "/")
            try:
                size = os.path.getsize(abs_path)
            except OSError:
                size = 0
            files.append({"path": rel_path, "type": "file", "size": size})
    return files


@router.get("/{id}/files")
async def get_execution_files(id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Execution).where(Execution.id == id))
    execution = result.scalar_one_or_none()
    if not execution:
        raise HTTPException(404, "Execution not found")

    project_path = (execution.context or {}).get("project_path")
    if not project_path or not os.path.isdir(project_path):
        return {"execution_id": str(id), "project_path": project_path, "files": []}

    return {
        "execution_id": str(id),
        "project_path": project_path,
        "files": _walk_project(project_path),
    }


@router.get("/{id}", response_model=ExecutionResponse)
async def get_execution(id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Execution).where(Execution.id == id))
    execution = result.scalar_one_or_none()
    if not execution:
        raise HTTPException(404, "Execution not found")
    return execution


@router.get("/{id}/logs")
async def get_execution_logs(id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ExecutionLog)
        .where(ExecutionLog.execution_id == id)
        .order_by(ExecutionLog.created_at)
    )
    logs = result.scalars().all()
    return [
        {
            "id": log.id,
            "level": log.level,
            "message": log.message,
            "metadata": log.log_metadata,
            "node_execution_id": (
                str(log.node_execution_id) if log.node_execution_id else None
            ),
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]


@router.get("/{id}/nodes", response_model=list[NodeExecutionResponse])
async def get_execution_nodes(id: UUID, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(NodeExecution)
        .where(NodeExecution.execution_id == id)
        .order_by(NodeExecution.started_at)
    )
    nodes = result.scalars().all()
    exec_mgr: ExecutionManager = request.app.state.execution_manager
    slow = exec_mgr.slow_nodes(id)
    items = []
    for n in nodes:
        info = slow.get(n.node_id)
        if info:
            n.slow = True
            n.slow_elapsed_seconds = info["elapsed_seconds"]
        items.append(n)
    return items


class NodeIntervention(BaseModel):
    node_id: str
    action: str = Field(..., pattern="^(wait|switch_model|terminate)$")
    provider: str | None = None
    model: str | None = None


@router.post("/{id}/intervene")
async def intervene_execution(id: UUID, body: NodeIntervention, request: Request,
                              db: AsyncSession = Depends(get_db)):
    exec_mgr: ExecutionManager = request.app.state.execution_manager
    try:
        await exec_mgr.intervene(id, body.node_id, body.action,
                                 provider=body.provider, model=body.model)
    except ValueError as e:
        raise HTTPException(404, str(e))
    if body.action == "terminate":
        execution = await db.get(Execution, id)
        if not execution:
            raise HTTPException(404, "Execution not found")
        execution.status = "cancelled"
        execution.finished_at = datetime.now(UTC).replace(tzinfo=None)
        await db.commit()
        return {"status": "cancelled", "execution_id": str(id)}
    return {
        "status": "intervened",
        "execution_id": str(id),
        "node_id": body.node_id,
        "action": body.action,
        "provider": body.provider,
        "model": body.model,
    }


@router.post("/{id}/pause")
async def pause_execution(id: UUID, request: Request, db: AsyncSession = Depends(get_db)):
    exec_mgr: ExecutionManager = request.app.state.execution_manager
    try:
        await exec_mgr.pause(id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    execution = await db.get(Execution, id)
    if execution:
        execution.status = "paused"
        await db.commit()
    return {"status": "paused", "execution_id": str(id)}


@router.post("/{id}/resume")
async def resume_execution(id: UUID, request: Request, db: AsyncSession = Depends(get_db)):
    exec_mgr: ExecutionManager = request.app.state.execution_manager
    try:
        await exec_mgr.resume(id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    execution = await db.get(Execution, id)
    if execution:
        execution.status = "running"
        await db.commit()
    return {"status": "resumed", "execution_id": str(id)}


@router.post("/{id}/cancel")
async def cancel_execution(id: UUID, request: Request, db: AsyncSession = Depends(get_db)):
    exec_mgr: ExecutionManager = request.app.state.execution_manager
    try:
        await exec_mgr.cancel(id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    execution = await db.get(Execution, id)
    if execution:
        execution.status = "cancelled"
        execution.finished_at = datetime.now(UTC).replace(tzinfo=None)
        await db.commit()
    return {"status": "cancelled", "execution_id": str(id)}


@router.get("/{id}/decision", response_model=ExecutionDecisionResponse | None)
async def get_execution_decision(id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ExecutionDecision)
        .where(ExecutionDecision.execution_id == id)
        .order_by(ExecutionDecision.created_at.desc())
        .limit(1)
    )
    decision = result.scalar_one_or_none()
    return decision


@router.post("/{id}/resolve")
async def resolve_execution(id: UUID, body: ResolveRequest, request: Request, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ExecutionDecision)
        .where(ExecutionDecision.execution_id == id, ExecutionDecision.status == "pending")
        .order_by(ExecutionDecision.created_at.desc())
        .limit(1)
    )
    decision = result.scalar_one_or_none()
    if not decision:
        raise HTTPException(404, "No pending decision for this execution")

    execution = await db.get(Execution, id)
    if not execution:
        raise HTTPException(404, "Execution not found")

    if body.action == "abandon":
        decision.status = "resolved"
        decision.resolved_action = "abandon"
        decision.resolved_at = datetime.now(UTC).replace(tzinfo=None)
        execution.status = "cancelled"
        await db.commit()
        return {"status": "cancelled", "execution_id": str(id)}

    if body.action not in ("retry", "revise_blueprint"):
        raise HTTPException(400, "action must be retry / revise_blueprint / abandon")

    blueprint_content = decision.blueprint or {}
    workflow_definition = decision.workflow or {}
    project_path = (execution.context or {}).get("project_path")

    llm = request.app.state.llm_gateway
    planner = PlannerAgent(llm, AgentRegistry(db), request.app.state.tool_registry)

    if body.action == "revise_blueprint":
        architect = Architect(llm)
        if body.blueprint:
            blueprint_content = body.blueprint
        elif body.feedback:
            blueprint_content = await architect.revise(blueprint_content, body.feedback)
        saved = await architect.save(
            blueprint_content,
            db,
            workflow_id=execution.workflow_id,
            source_execution_id=execution.id,
        )
        await db.flush()
        workflow_definition = await planner.generate_dag(blueprint_content)
        if project_path:
            workflow_definition = inject_workspace(workflow_definition, project_path)

    decision.status = "resolved"
    decision.resolved_action = body.action
    execution.status = "running"
    execution.replan_count = 0
    execution.finished_at = None
    await db.commit()

    coordinator = ReplanCoordinator(
        planner=planner,
        architect=Architect(llm),
        exec_mgr=request.app.state.execution_manager,
        db_factory=async_session_factory,
        workspace_injector=lambda wf, path: inject_workspace(wf, path),
    )

    async def _run():
        await coordinator.run(
            requirement=(execution.context or {}).get("requirement") or "requirement",
            blueprint_content=blueprint_content,
            workflow_definition=workflow_definition,
            execution_id=id,
            project_path=project_path or "",
            workflow_id=execution.workflow_id,
        )

    asyncio.ensure_future(_run())

    return {"status": "started", "action": body.action, "execution_id": str(id)}
