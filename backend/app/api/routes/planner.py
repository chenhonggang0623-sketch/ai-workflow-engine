import asyncio
import os
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db, async_session_factory
from app.core.config import settings
from app.agent.llm_gateway import LLMGateway
from app.agent.registry import AgentRegistry
from app.mcp.tool_registry import ToolRegistry
from app.planner.planner_agent import PlannerAgent
from app.planner.architect import Architect
from app.planner.replan_coordinator import ReplanCoordinator
from app.planner.workspace import build_project_path, inject_workspace, next_generation_version, strip_workspace
from app.schemas.planner import PlanRequest, PlanResponse, PlanConfirm
from app.engine.types import WorkflowDefinition, NodeDefinition, EdgeDefinition
from app.engine.execution_manager import ExecutionManager
from app.models.workflow import Workflow, Execution
from app.models.blueprint import Blueprint

router = APIRouter()


@router.post("/plan", response_model=PlanResponse)
async def generate_plan(body: PlanRequest, request: Request, db: AsyncSession = Depends(get_db)):
    llm: LLMGateway = request.app.state.llm_gateway
    tool_registry: ToolRegistry = request.app.state.tool_registry
    agent_registry = AgentRegistry(db)
    planner = PlannerAgent(llm, agent_registry, tool_registry)
    try:
        result = await planner.plan(body.requirement, body.constraints)

        blueprint_content = result.get("blueprint", {}).get("content")
        blueprint_payload = {"content": blueprint_content}
        if blueprint_content:
            architect = Architect(llm)
            await architect.cleanup_dangling_drafts(db)
            saved = await architect.save(
                blueprint_content, db, status="draft"
            )
            await db.commit()
            blueprint_payload = {
                "id": str(saved.id),
                "version": saved.version,
                "content": blueprint_content,
            }

        return PlanResponse(
            plan=result["workflow"],
            blueprint=blueprint_payload,
            explanation=result["explanation"],
            estimated_duration_seconds=result.get("estimated_duration_seconds"),
            complexity_analysis=result.get("complexity_analysis"),
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/confirm")
async def confirm_plan(body: PlanConfirm, request: Request, db: AsyncSession = Depends(get_db)):
    exec_mgr: ExecutionManager = request.app.state.execution_manager
    llm: LLMGateway = request.app.state.llm_gateway
    plan = body.modifications or {}
    if not plan:
        raise HTTPException(400, "No plan provided")

    original_def = WorkflowDefinition(
        name=plan.get("name", "Planned Workflow"),
        description=plan.get("description", ""),
        nodes=[NodeDefinition(**n) for n in plan.get("nodes", [])],
        edges=[EdgeDefinition(**e) for e in plan.get("edges", [])],
    )

    # 幂等：相同名称+描述的工作流若已存在未终态的执行（running/pending/paused/blocked），
    # 直接复用该执行，避免重复创建相同项目。
    existing_wf = await db.execute(
        select(Workflow)
        .where(
            Workflow.name == original_def.name,
            Workflow.description == original_def.description,
        )
        .order_by(Workflow.created_at.desc())
    )
    for wf in existing_wf.scalars():
        existing_exes = await db.execute(
            select(Execution).where(Execution.workflow_id == wf.id)
        )
        for exe in existing_exes.scalars():
            if exe.status in ("pending", "running", "paused", "blocked"):
                return {
                    "workflow_id": str(wf.id),
                    "execution_id": str(exe.id),
                    "status": "existing",
                    "project_path": (exe.context or {}).get("project_path"),
                }

    execution_id = uuid.uuid4()
    version = await next_generation_version(db, original_def.name)
    project_path = build_project_path(
        settings.project_root_abs, original_def.name, version
    )
    os.makedirs(project_path, exist_ok=True)
    plan = inject_workspace(plan, project_path)

    wf_def = WorkflowDefinition(
        name=plan.get("name", original_def.name),
        description=plan.get("description", ""),
        nodes=[NodeDefinition(**n) for n in plan.get("nodes", [])],
        edges=[EdgeDefinition(**e) for e in plan.get("edges", [])],
    )

    # P1-2: workflow.definition 存"干净"版本（不含工作目录），工作目录是
    # execution 级属性；若把第一次执行的项目路径烘焙进 definition，
    # 后续复跑/并发执行会复用并污染同一目录。
    clean_definition = strip_workspace(body.modifications or {})
    workflow = Workflow(
        name=wf_def.name,
        description=wf_def.description,
        definition=clean_definition,
    )
    db.add(workflow)
    await db.flush()
    await db.refresh(workflow)

    requirement = plan.get("description", wf_def.name)
    execution = Execution(
        id=execution_id,
        workflow_id=workflow.id,
        status="running",
        replan_count=0,
        started_at=datetime.now(UTC).replace(tzinfo=None),
        context={
            "requirement": requirement,
            "project_path": project_path,
            "workflow_definition": plan,
        },
    )
    db.add(execution)
    await db.flush()
    await db.refresh(execution)

    # 回填 plan 阶段创建的蓝图（workflow_id + 触发 execution）
    blueprint_content = None
    if body.blueprint_id:
        bp = await db.get(Blueprint, body.blueprint_id)
        if bp:
            bp.workflow_id = workflow.id
            bp.source_execution_id = execution_id
            bp.status = "active"
            blueprint_content = bp.content
            db.add(bp)
    await db.commit()

    # 没有蓝图时（例如 test.sh 直接 POST workflow JSON），生成基础蓝图兜底
    if blueprint_content is None:
        architect = Architect(llm)
        fallback_blueprint = {
            "prd": {"summary": requirement, "goals": [], "features": [],
                    "non_functional": [], "acceptance_criteria": [],
                    "assumptions": [], "open_questions": []},
            "architecture": {"tech_stack": [], "directory_structure": [],
                             "data_model": [], "api_contracts": []},
            "modules": [
                {
                    "id": m.get("id", "core"),
                    "name": m.get("label", "Core"),
                    "description": "Implicit module",
                    "depends_on": [],
                    "input_contract": ["requirement"],
                    "output_contract": ["output"],
                }
                for m in plan.get("nodes", []) if m.get("type") == "agent"
            ] or [{
                "id": "core",
                "name": "Core",
                "description": "Core implementation",
                "depends_on": [],
                "input_contract": ["requirement"],
                "output_contract": ["output"],
            }],
            "constraints": [],
        }
        async with async_session_factory() as session:
            saved_bp = await architect.save(
                fallback_blueprint, session,
                workflow_id=workflow.id, source_execution_id=execution_id,
            )
            await session.commit()
        blueprint_content = fallback_blueprint

    # 启动重规划循环
    coordinator = ReplanCoordinator(
        planner=PlannerAgent(llm, AgentRegistry(db), request.app.state.tool_registry),
        architect=Architect(llm),
        exec_mgr=exec_mgr,
        db_factory=async_session_factory,
        workspace_injector=lambda wf, path: inject_workspace(wf, path),
    )

    async def _run():
        try:
            result = await coordinator.run(
                requirement=requirement,
                blueprint_content=blueprint_content,
                workflow_definition=plan,
                execution_id=execution_id,
                project_path=project_path,
                workflow_id=workflow.id,
            )
            async with async_session_factory() as session:
                exe = await session.get(Execution, execution_id)
                if exe:
                    exe.replan_count = result.get("replan_count", exe.replan_count)
                    if result.get("status") == "blocked":
                        exe.status = "blocked"
                        exe.context = {
                            **(exe.context or {}),
                            "blocked_reason": result.get("reason", ""),
                        }
                    await session.commit()
        except Exception:
            logger_exc()

    asyncio.ensure_future(_run())

    return {
        "workflow_id": str(workflow.id),
        "execution_id": str(execution_id),
        "status": "started",
        "project_path": project_path,
    }


def logger_exc():
    import logging
    logging.getLogger(__name__).exception("Execution background task crashed")


@router.get("/templates")
async def list_templates():
    return {
        "categories": [
            {
                "id": "documentation",
                "name": "Documentation",
                "description": "Documentation generation workflows",
                "templates": [
                    {
                        "id": "wiki-doc-generator",
                        "name": "Wiki Documentation Generator",
                        "description": "PM -> Developer -> QA pipeline that generates project documentation",
                        "definition": {
                            "nodes": [
                                {
                                    "id": "pm",
                                    "type": "agent",
                                    "label": "PM",
                                    "config": {
                                        "agent_id": "pm_agent",
                                        "timeout_seconds": 900,
                                    },
                                },
                                {
                                    "id": "dev",
                                    "type": "agent",
                                    "label": "Developer",
                                    "config": {
                                        "agent_id": "developer_agent",
                                        "timeout_seconds": 900,
                                    },
                                },
                                {
                                    "id": "qa",
                                    "type": "agent",
                                    "label": "QA",
                                    "config": {
                                        "agent_id": "qa_agent",
                                        "timeout_seconds": 900,
                                    },
                                },
                            ],
                            "edges": [
                                {"id": "e1", "source": "pm", "target": "dev"},
                                {"id": "e2", "source": "dev", "target": "qa"},
                            ],
                        },
                    }
                ],
            },
            {
                "id": "code-review",
                "name": "Code Review",
                "description": "Automated review and QA workflows",
                "templates": [
                    {
                        "id": "review-gate",
                        "name": "Review Gate",
                        "description": "Developer -> QA review gate with safety net",
                        "definition": {
                            "nodes": [
                                {
                                    "id": "dev",
                                    "type": "agent",
                                    "label": "Developer",
                                    "config": {
                                        "agent_id": "developer_agent",
                                        "timeout_seconds": 900,
                                    },
                                },
                                {
                                    "id": "qa",
                                    "type": "agent",
                                    "label": "QA",
                                    "config": {
                                        "agent_id": "qa_agent",
                                        "timeout_seconds": 900,
                                    },
                                },
                            ],
                            "edges": [{"id": "e1", "source": "dev", "target": "qa"}],
                        },
                    }
                ],
            },
        ]
    }
