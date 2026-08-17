import asyncio
import copy
import logging
import os
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, delete, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db, async_session_factory
from app.core.app_config import config_store
from app.core.config import settings
from app.models.workflow import Workflow, Execution, NodeExecution, ExecutionLog
from app.models.artifact import Artifact
from app.models.blueprint import Blueprint, ExecutionDecision
from app.models.contract import TaskContract
from app.models.evaluation import Evaluation
from app.models.message import AgentMessage
from app.schemas.workflow import WorkflowCreate, WorkflowUpdate, WorkflowResponse, NodeExecutorUpdate
from app.engine.types import WorkflowDefinition, NodeDefinition, EdgeDefinition
from app.engine.dag_validator import validate_dag, resolve_dag_limits
from app.engine.execution_manager import ExecutionManager

router = APIRouter()

logger = logging.getLogger(__name__)


@router.get("", response_model=list[WorkflowResponse])
async def list_workflows(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Workflow).order_by(Workflow.created_at.desc()))
    workflows = result.scalars().all()
    return workflows


@router.post("", response_model=WorkflowResponse, status_code=201)
async def create_workflow(body: WorkflowCreate, db: AsyncSession = Depends(get_db)):
    workflow = Workflow(
        name=body.name,
        description=body.description,
        definition=body.definition,
    )
    db.add(workflow)
    await db.flush()
    await db.refresh(workflow)
    return workflow


@router.get("/{id}", response_model=WorkflowResponse)
async def get_workflow(id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Workflow).where(Workflow.id == id))
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(404, "Workflow not found")
    return workflow


@router.put("/{id}", response_model=WorkflowResponse)
async def update_workflow(id: UUID, body: WorkflowUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Workflow).where(Workflow.id == id))
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(404, "Workflow not found")
    if body.name is not None:
        workflow.name = body.name
    if body.description is not None:
        workflow.description = body.description
    if body.definition is not None:
        workflow.definition = body.definition
    await db.flush()
    await db.refresh(workflow)
    return workflow


@router.delete("/{id}", status_code=204)
async def delete_workflow(id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Workflow).where(Workflow.id == id))
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(404, "Workflow not found")

    # 收集该项目下的 execution（含级联数据删除用的 project_path）
    executions = (
        await db.execute(select(Execution).where(Execution.workflow_id == id))
    ).scalars().all()
    execution_ids = [e.id for e in executions]

    # 按外键依赖顺序级联删除（先叶子，后父行）
    if execution_ids:
        await db.execute(
            delete(ExecutionLog).where(ExecutionLog.execution_id.in_(execution_ids))
        )
        # evaluations 同时引用 node_executions / task_contracts，先删
        await db.execute(
            delete(Evaluation).where(Evaluation.execution_id.in_(execution_ids))
        )
        await db.execute(
            delete(TaskContract).where(TaskContract.execution_id.in_(execution_ids))
        )
        await db.execute(
            delete(AgentMessage).where(AgentMessage.execution_id.in_(execution_ids))
        )
        await db.execute(
            delete(ExecutionDecision).where(ExecutionDecision.execution_id.in_(execution_ids))
        )
        await db.execute(
            delete(NodeExecution).where(NodeExecution.execution_id.in_(execution_ids))
        )
        await db.execute(
            delete(Artifact).where(Artifact.execution_id.in_(execution_ids))
        )
        # blueprint 引用 executions（source_execution_id）或 workflows（workflow_id），先删
        await db.execute(
            delete(Blueprint).where(
                or_(
                    Blueprint.workflow_id == id,
                    Blueprint.source_execution_id.in_(execution_ids),
                )
            )
        )
        await db.execute(delete(Execution).where(Execution.workflow_id == id))

    await db.execute(
        delete(Artifact).where(Artifact.workflow_id == id)
    )
    await db.execute(
        delete(Blueprint).where(Blueprint.workflow_id == id)
    )

    # 清理磁盘上的项目工作区（仅限 generated_projects 目录内）
    project_root = settings.project_root_abs
    cleaned, failed = [], []
    for e in executions:
        ctx = e.context or {}
        project_path = ctx.get("project_path")
        if not project_path:
            continue
        full = os.path.abspath(os.path.expanduser(project_path))
        if full == project_root or not full.startswith(project_root + os.sep):
            continue
        try:
            import shutil

            shutil.rmtree(full)
            cleaned.append(full)
        except OSError as exc:
            failed.append((full, str(exc)))

    if failed:
        logger.warning(
            "delete_workflow %s: %d workspace dir(s) not removed: %s",
            id, len(failed), failed,
        )

    await db.delete(workflow)
    await db.flush()


@router.put("/{workflow_id}/nodes/{node_id}/executor", response_model=WorkflowResponse)
async def update_node_executor(
    workflow_id: UUID,
    node_id: str,
    body: NodeExecutorUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(404, "Workflow not found")

    definition = copy.deepcopy(workflow.definition or {"nodes": [], "edges": []})
    nodes = definition.get("nodes", [])
    updated = False
    for node in nodes:
        if node.get("id") == node_id:
            if "config" not in node:
                node["config"] = {}
            node["config"]["executor_type"] = body.executor_type
            node["config"]["executor_config"] = body.executor_config
            if body.provider is not None:
                node["config"]["provider"] = body.provider
            if body.system_prompt is not None:
                node["config"]["system_prompt"] = body.system_prompt
            updated = True
            break

    if not updated:
        raise HTTPException(404, "Node not found in workflow")

    workflow.definition = definition
    await db.flush()
    await db.refresh(workflow)
    return workflow


@router.post("/{id}/execute")
async def execute_workflow(
    id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Workflow).where(Workflow.id == id))
    workflow = result.scalar_one_or_none()
    if not workflow:
        raise HTTPException(404, "Workflow not found")

    exec_mgr: ExecutionManager = request.app.state.execution_manager

    try:
        body = await request.json()
        initial_context = body.get("context", {}) if isinstance(body, dict) else {}
    except Exception:
        initial_context = {}

    definition = workflow.definition
    wf_def = WorkflowDefinition(
        name=workflow.name,
        description=workflow.description,
        nodes=[NodeDefinition(**n) for n in definition.get("nodes", [])],
        edges=[EdgeDefinition(**e) for e in definition.get("edges", [])],
    )

    dag_report = validate_dag(definition, limits=resolve_dag_limits(config_store))
    if not dag_report.approved:
        raise HTTPException(
            400,
            detail={
                "message": "Workflow DAG failed pre-execution validation",
                "errors": [e.message for e in dag_report.errors],
            },
        )

    execution = Execution(
        workflow_id=id,
        status="running",
        context={
            **initial_context,
            "workflow_definition": definition,
        },
    )
    db.add(execution)
    await db.flush()
    await db.refresh(execution)

    execution_id = execution.id

    async def _run():
        try:
            result = await exec_mgr.execute_workflow(
                wf_def,
                execution_id,
                async_session_factory,
                initial_context=initial_context,
            )
            async with async_session_factory() as session:
                stmt = select(Execution).where(Execution.id == execution_id)
                row = await session.execute(stmt)
                exe = row.scalar_one_or_none()
                if exe:
                    exe.status = result.status.value
                    exe.finished_at = result.finished_at
                    exe.context = result.context
                    await session.commit()
        except Exception:
            async with async_session_factory() as session:
                stmt = select(Execution).where(Execution.id == execution_id)
                row = await session.execute(stmt)
                exe = row.scalar_one_or_none()
                if exe:
                    exe.status = "failed"
                    await session.commit()

    asyncio.ensure_future(_run())

    return {"execution_id": str(execution_id)}
