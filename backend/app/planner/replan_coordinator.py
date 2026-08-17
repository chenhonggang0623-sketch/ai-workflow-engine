import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from app.engine.types import (
    WorkflowDefinition,
    NodeDefinition,
    EdgeDefinition,
    ExecutionStatus,
)
from app.models.workflow import Execution
from app.models.blueprint import ExecutionDecision

logger = logging.getLogger(__name__)

MAX_REPLAN = 3

BLOCK_OPTIONS = ["retry", "revise_blueprint", "abandon"]


class ReplanCoordinator:
    """级联重规划协调器：执行失败 → 修订蓝图 → 重新生成 DAG → 重新执行。

    自动重规划上限 MAX_REPLAN 次；仍失败则置 blocked 并落 ExecutionDecision
    把问题抛回用户。
    """

    def __init__(self, planner, architect, exec_mgr, db_factory, workspace_injector=None):
        self._planner = planner
        self._architect = architect
        self._exec_mgr = exec_mgr
        self._db_factory = db_factory
        self._workspace_injector = workspace_injector

    async def run(
        self,
        *,
        requirement: str,
        blueprint_content: dict,
        workflow_definition: dict,
        execution_id: UUID,
        project_path: str,
        workflow_id: UUID | None = None,
    ) -> dict:
        """执行完整循环。返回值含 status / replan_count / decision 摘要。"""
        current_blueprint = blueprint_content
        current_wf = workflow_definition
        replan_count = 0
        last_result = None
        error_summary = ""

        while True:
            if self._is_cancel_requested(execution_id):
                await self._update_execution(execution_id, status="cancelled")
                return {
                    "status": "cancelled",
                    "replan_count": replan_count,
                    "execution_id": str(execution_id),
                }

            wf_def = self._to_workflow_definition(current_wf, replan_count)

            async def _run_once():
                return await self._exec_mgr.execute_workflow(
                    wf_def,
                    execution_id,
                    self._db_factory,
                    initial_context={
                        "requirement": requirement,
                        "project_path": project_path,
                        "workflow_definition": current_wf,
                        "replan_attempt": replan_count,
                    },
                )

            try:
                last_result = await _run_once()
            except Exception as e:
                logger.exception("Execution %s raised: %s", execution_id, e)
                await self._update_execution(
                    execution_id, status="failed", context=None
                )
                return {
                    "status": "failed",
                    "replan_count": replan_count,
                    "error": str(e),
                }

            if last_result.status == ExecutionStatus.SUCCEEDED:
                recommendations = getattr(
                    last_result, "rerun_recommendations", []
                ) or []
                if recommendations:
                    logger.warning(
                        "Execution %s succeeded but audit recommends rerun for "
                        "nodes %s (not auto-rerun; surfaced as a prompt)",
                        execution_id,
                        [r.get("node_id") for r in recommendations],
                    )
                await self._update_execution(
                    execution_id, status="succeeded", context=last_result.context
                )
                return {
                    "status": "succeeded",
                    "replan_count": replan_count,
                    "execution_id": str(execution_id),
                    "rerun_recommended": bool(recommendations),
                    "rerun_recommendations": recommendations,
                }

            if last_result.status in (ExecutionStatus.CANCELLED, ExecutionStatus.PAUSED):
                await self._update_execution(
                    execution_id, status=last_result.status.value, context=last_result.context
                )
                return {
                    "status": last_result.status.value,
                    "replan_count": replan_count,
                    "execution_id": str(execution_id),
                }

            # FAILED → 级联重规划
            error_summary = self._summarize_failure(last_result)
            replan_count += 1

            if replan_count > MAX_REPLAN:
                return await self._block(
                    execution_id=execution_id,
                    reason=error_summary,
                    attempts=replan_count - 1,
                    blueprint=current_blueprint,
                    workflow=current_wf,
                )

            logger.info(
                "Execution %s failed (attempt %d): %s. Replanning...",
                execution_id, replan_count, error_summary,
            )
            await self._update_execution(execution_id, status="replanning")

            try:
                revised = await self._architect.revise(current_blueprint, error_summary)
                async with self._db_factory() as session:
                    saved = await self._architect.save(
                        revised,
                        session,
                        workflow_id=workflow_id,
                        source_execution_id=execution_id,
                    )
                    await session.commit()
                current_blueprint = revised
                current_wf = await self._planner.generate_dag(revised)
                current_wf = self._inject_workspace(current_wf, project_path)
                await self._update_execution(
                    execution_id, status="running",
                    context={
                        "requirement": requirement,
                        "project_path": project_path,
                        "workflow_definition": current_wf,
                    },
                )
            except Exception as e:
                logger.exception("Replan failed: %s", e)
                return await self._block(
                    execution_id=execution_id,
                    reason=f"Replan crashed: {e}",
                    attempts=replan_count - 1,
                    blueprint=current_blueprint,
                    workflow=current_wf,
                )

        return {
            "status": "unknown",
            "replan_count": replan_count,
            "execution_id": str(execution_id),
        }

    def _is_cancel_requested(self, execution_id: UUID) -> bool:
        method = getattr(type(self._exec_mgr), "is_cancel_requested", None)
        if not method:
            return False
        try:
            return bool(method(self._exec_mgr, execution_id))
        except Exception:
            return False

    async def _block(
        self,
        *,
        execution_id: UUID,
        reason: str,
        attempts: int,
        blueprint: dict,
        workflow: dict,
    ) -> dict:
        """重规划耗尽：置 blocked 并写入 ExecutionDecision。"""
        logger.warning(
            "Execution %s blocked after %d replans: %s", execution_id, attempts, reason
        )
        await self._update_execution(
            execution_id,
            status="blocked",
            context={"blocked_reason": reason},
        )
        async with self._db_factory() as session:
            decision = ExecutionDecision(
                execution_id=execution_id,
                reason=reason,
                attempts=attempts,
                options=list(BLOCK_OPTIONS),
                blueprint=blueprint,
                workflow=workflow,
                status="pending",
            )
            session.add(decision)
            await session.commit()
            decision_id = decision.id
        return {
            "status": "blocked",
            "replan_count": attempts,
            "execution_id": str(execution_id),
            "decision_id": str(decision_id),
            "reason": reason,
        }

    async def _update_execution(
        self, execution_id: UUID, status: str, context: dict | None = None
    ) -> None:
        async with self._db_factory() as session:
            exe = await session.get(Execution, execution_id)
            if not exe:
                return
            exe.status = status
            if context is not None:
                merged = dict(exe.context or {})
                merged.update(context)
                exe.context = merged
            if status in ("succeeded", "failed", "cancelled", "blocked"):
                exe.finished_at = datetime.now(UTC).replace(tzinfo=None)
            await session.commit()

    def _summarize_failure(self, result) -> str:
        errors = []
        for node_result in getattr(result, "node_results", []) or []:
            if getattr(node_result, "status", None) is not None:
                status = getattr(node_result, "status", None)
                if getattr(status, "value", status) in ("failed", "cancelled"):
                    errors.append(
                        f"{node_result.node_id}: {node_result.error or 'unknown error'}"
                    )
        if errors:
            return "; ".join(errors[:5])
        return getattr(result, "error", None) or "Execution failed for unknown reason"

    def _inject_workspace(self, workflow: dict, project_path: str) -> dict:
        if self._workspace_injector is not None:
            return self._workspace_injector(workflow, project_path)
        return workflow

    def _to_workflow_definition(
        self, workflow: dict, replan_count: int
    ) -> WorkflowDefinition:
        suffix = f"_r{replan_count}" if replan_count > 0 else ""
        id_map: dict[str, str] = {}

        nodes = []
        for n in workflow.get("nodes", []):
            node = dict(n)
            node_id = node.get("id", "")
            mapped = f"{node_id}{suffix}" if node_id else ""
            id_map[node_id] = mapped
            node["id"] = mapped
            if "module_id" in (node.get("config") or {}):
                node["config"] = dict(node["config"])
            nodes.append(NodeDefinition(**node))

        edges = []
        for e in workflow.get("edges", []):
            edge = dict(e)
            edge["source"] = id_map.get(edge.get("source", ""), edge.get("source", ""))
            edge["target"] = id_map.get(edge.get("target", ""), edge.get("target", ""))
            edges.append(EdgeDefinition(**edge))

        return WorkflowDefinition(
            name=workflow.get("name", "Planned Workflow"),
            description=workflow.get("description", ""),
            nodes=nodes,
            edges=edges,
        )
