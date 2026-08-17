import asyncio
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.supervisor.evaluation import EvaluationEngine
from app.supervisor.quality_gate import QualityGate
from app.supervisor.recovery import RecoveryManager
from app.contract.contract_manager import ContractManager
from app.agent.runtime import AgentExecutor
from app.context.manager import ContextManager
from app.artifact.manager import ArtifactManager
from app.models.workflow import Execution, NodeExecution
from app.engine.types import ExecutionStatus, NodeStatus

logger = logging.getLogger(__name__)

DEFAULT_GATES = ["schema_validate", "llm_review"]


class SupervisorOrchestrator:
    def __init__(
        self,
        db_session: AsyncSession,
        evaluation_engine: EvaluationEngine,
        quality_gate: QualityGate,
        recovery_manager: RecoveryManager,
        contract_manager: ContractManager,
        comm_broker,
        agent_executor: AgentExecutor,
        context_manager: ContextManager,
        artifact_manager: ArtifactManager,
    ):
        self.db = db_session
        self._eval = evaluation_engine
        self._gate = quality_gate
        self._recovery = recovery_manager
        self._cm = contract_manager
        self._broker = comm_broker
        self._executor = agent_executor
        self._ctx = context_manager
        self._artifacts = artifact_manager
        self._progress: dict[uuid.UUID, dict] = {}
        self._node_contracts: dict[uuid.UUID, dict] = {}

    async def supervise(self, execution_id: uuid.UUID) -> None:
        exec_data = await self._load_execution(execution_id)
        if not exec_data:
            logger.error("Execution %s not found", execution_id)
            return

        self._progress[execution_id] = {
            "total": len(exec_data.get("nodes", [])),
            "completed": 0,
            "failed": 0,
            "skipped": 0,
            "status": ExecutionStatus.RUNNING.value,
            "started_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
        }

        nodes = exec_data.get("nodes", [])
        context = await self._ctx.get(execution_id)

        for node in nodes:
            node_exec = await self._get_or_create_node_exec(execution_id, node["id"])
            context["node_execution_id"] = str(node_exec.id)

            await self._broker.broadcast(
                execution_id=execution_id,
                sender_id="supervisor",
                subject="node.started",
                payload={"node_id": node["id"], "node_execution_id": str(node_exec.id)},
            )

            try:
                result = await self.supervise_node(
                    {"id": node["id"], **node, "execution_id": str(execution_id)},
                    context,
                )

                if result.get("status") == NodeStatus.SUCCEEDED.value:
                    self._progress[execution_id]["completed"] += 1
                elif result.get("status") in (NodeStatus.FAILED.value, NodeStatus.CANCELLED.value):
                    self._progress[execution_id]["failed"] += 1
                elif result.get("status") == NodeStatus.SKIPPED.value:
                    self._progress[execution_id]["skipped"] += 1

                if result.get("output"):
                    await self._ctx.set_value(
                        execution_id, f"$.nodes.{node['id']}.output", result["output"]
                    )

            except Exception as exc:
                logger.error("Node %s failed: %s", node["id"], exc)
                self._progress[execution_id]["failed"] += 1

            await self._broker.broadcast(
                execution_id=execution_id,
                sender_id="supervisor",
                subject="node.completed",
                payload={"node_id": node["id"], "result": result if "result" in locals() else {"status": "failed"}},
            )

        total = self._progress[execution_id]["total"]
        failed = self._progress[execution_id]["failed"]
        self._progress[execution_id]["status"] = (
            ExecutionStatus.FAILED.value if failed > 0 else ExecutionStatus.SUCCEEDED.value
        )
        self._progress[execution_id]["finished_at"] = datetime.now(UTC).replace(tzinfo=None).isoformat()

    async def supervise_node(self, node_exec: dict, context: dict) -> dict:
        node_id = node_exec["id"]
        execution_id = uuid.UUID(node_exec["execution_id"])
        agent_id = node_exec.get("agent_id")

        node_result = {
            "node_id": node_id,
            "status": NodeStatus.RUNNING.value,
            "output": {},
            "started_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
        }

        if not agent_id:
            node_result["status"] = NodeStatus.SKIPPED.value
            node_result["output"] = {"note": "No agent assigned to this node"}
            return node_result

        contract = await self._cm.create(
            execution_id=execution_id,
            issuer_id="supervisor",
            executor_id=agent_id,
            task_name=node_exec.get("label", f"node-{node_id}"),
            task_description=node_exec.get("description", ""),
            input_schema=node_exec.get("input_schema"),
            output_schema=node_exec.get("output_schema"),
            acceptance_criteria=node_exec.get("acceptance_criteria", []),
            timeout_seconds=node_exec.get("timeout_seconds", 300),
        )
        self._node_contracts[uuid.UUID(node_exec.get("node_execution_id", str(uuid.uuid4())))] = {
            "contract_id": contract.id,
            "agent_id": agent_id,
        }

        try:
            agent_output = await self._executor.execute(
                agent_id=agent_id,
                node_input=node_exec.get("input", context),
                context=context,
            )

            if "error" in agent_output:
                return await self._handle_node_failure(
                    contract.id, agent_output["error"], node_result, node_exec, context
                )

            await self._cm.complete(contract.id, agent_output)

            gate_config = {
                "schema": node_exec.get("output_schema", {}),
                "criteria": node_exec.get("acceptance_criteria", []),
            }
            gate_result = await self._gate.check_contract(contract, agent_output)

            if not gate_result["passed"]:
                recovery = await self._recovery.handle_failure(
                    contract.id, gate_result["feedback"]
                )
                node_result["recovery"] = recovery

                if recovery["action"] in ("retry", "replace"):
                    node_result["output"] = {"recovery": recovery, "note": "Recovery in progress"}
                    return node_result

                if recovery["action"] == "pause":
                    node_result["status"] = NodeStatus.WAITING.value
                    node_result["output"] = {
                        "gate_result": gate_result,
                        "recovery": recovery,
                    }
                    return node_result

            await self._eval.evaluate(
                agent_id=agent_id,
                node_execution_id=uuid.UUID(node_exec.get("node_execution_id", str(uuid.uuid4()))),
                agent_output=agent_output,
                expected_schema=node_exec.get("output_schema"),
            )

            node_result["status"] = NodeStatus.SUCCEEDED.value
            node_result["output"] = agent_output

        except Exception as exc:
            return await self._handle_node_failure(
                contract.id, str(exc), node_result, node_exec, context
            )

        node_result["finished_at"] = datetime.now(UTC).replace(tzinfo=None).isoformat()
        return node_result

    async def get_progress(self, execution_id: uuid.UUID) -> dict:
        stored = self._progress.get(execution_id)
        if stored:
            return stored

        exec_data = await self._load_execution(execution_id)
        if not exec_data:
            return {"status": "not_found"}

        return {
            "execution_id": str(execution_id),
            "status": exec_data.get("status", "unknown"),
            "total": 0,
            "completed": 0,
            "failed": 0,
        }

    async def _load_execution(self, execution_id: uuid.UUID) -> dict | None:
        stmt = select(Execution).where(Execution.id == execution_id)
        row = await self.db.execute(stmt)
        execution = row.scalar_one_or_none()
        if not execution:
            return None
        return {
            "id": str(execution.id),
            "workflow_id": str(execution.workflow_id) if execution.workflow_id else None,
            "status": execution.status,
            "nodes": (execution.workflow.nodes if execution.workflow else []) if hasattr(execution, "workflow") else [],
            "context": execution.context or {},
        }

    async def _get_or_create_node_exec(self, execution_id: uuid.UUID, node_id: str) -> NodeExecution:
        stmt = select(NodeExecution).where(
            NodeExecution.execution_id == execution_id,
            NodeExecution.node_id == node_id,
        )
        row = await self.db.execute(stmt)
        existing = row.scalar_one_or_none()
        if existing:
            return existing

        ne = NodeExecution(
            id=uuid.uuid4(),
            execution_id=execution_id,
            node_id=node_id,
            status=NodeStatus.PENDING.value,
        )
        self.db.add(ne)
        await self.db.flush()
        return ne

    async def _handle_node_failure(
        self, contract_id: uuid.UUID, error: str, node_result: dict, node_exec: dict, context: dict
    ) -> dict:
        recovery = await self._recovery.handle_failure(contract_id, error)
        node_result["recovery"] = recovery
        node_result["error"] = error

        if recovery["action"] in ("retry", "replace"):
            node_result["output"] = {"recovery": recovery, "note": "Recovery in progress"}
            return node_result

        if recovery["action"] == "pause":
            node_result["status"] = NodeStatus.WAITING.value
            return node_result

        if recovery["action"] == "skip":
            node_result["status"] = NodeStatus.SKIPPED.value
            return node_result

        node_result["status"] = NodeStatus.FAILED.value
        return node_result
