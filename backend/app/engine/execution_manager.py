import asyncio
import logging
from datetime import UTC, datetime
from typing import Awaitable, Callable
from uuid import UUID

from app.core.config import settings
from app.engine.types import (
    WorkflowDefinition,
    WorkflowResult,
    ExecutionStatus,
    NodeStatus,
    NodeResult,
)
from app.engine.scheduler import DAGScheduler
from app.engine.state_machine import ExecutionStateMachine
from app.engine.node_runner import NodeRunner, _apply_output_mapping
from app.engine.context_service import ContextService, DEFAULT_MAX_CONTEXT_CHARS
from app.models.workflow import NodeExecution as NodeExecutionModel
from app.models.workflow import ExecutionLog as ExecutionLogModel

logger = logging.getLogger(__name__)


class NodeLogSink:
    """节点控制台输出流：逐行入队 → 批量落库 ExecutionLog + 实时广播。

    避免每个 CLI 输出行都开一个 DB 事务：队列累积，0.5s 或满 50 行批量提交。
    """

    def __init__(self, execution_id: UUID, node_id: str,
                 node_execution_id: UUID, db_factory, broadcast: Callable[[dict], Awaitable[None]] | None):
        self._execution_id = execution_id
        self._node_id = node_id
        self._node_execution_id = node_execution_id
        self._db_factory = db_factory
        self._broadcast = broadcast
        self._queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.ensure_future(self._writer())

    async def write(self, line: str, stream: str) -> None:
        await self._queue.put((line, stream))

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _writer(self) -> None:
        try:
            while True:
                batch: list[tuple[str, str]] = []
                try:
                    item = await asyncio.wait_for(self._queue.get(), timeout=0.5)
                    batch.append(item)
                except asyncio.TimeoutError:
                    pass
                while len(batch) < 50 and not self._queue.empty():
                    batch.append(self._queue.get_nowait())
                if batch:
                    await self._flush(batch)
        except asyncio.CancelledError:
            batch = []
            while not self._queue.empty():
                batch.append(self._queue.get_nowait())
            if batch:
                await self._flush(batch)
            raise

    async def _flush(self, batch: list[tuple[str, str]]) -> None:
        try:
            async with self._db_factory() as session:
                for line, stream in batch:
                    session.add(
                        ExecutionLogModel(
                            execution_id=self._execution_id,
                            node_execution_id=self._node_execution_id,
                            level="output",
                            message=line,
                            log_metadata={"stream": stream},
                        )
                    )
                await session.commit()
        except Exception:
            logger.exception("Failed to persist node console output")
        if self._broadcast is not None:
            for line, stream in batch:
                try:
                    await self._broadcast(
                        {
                            "type": "node_output",
                            "node_id": self._node_id,
                            "node_execution_id": str(self._node_execution_id),
                            "stream": stream,
                            "message": line,
                            "created_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
                        }
                    )
                except Exception:
                    logger.exception("Failed to broadcast node output")
                    return


class ExecutionManager:
    def __init__(self, node_runner: NodeRunner, max_concurrency: int = 5,
                 context_service: ContextService | None = None):
        self._node_runner = node_runner
        self._max_concurrency = max_concurrency
        self._cancel_events: dict[UUID, asyncio.Event] = {}
        self._state_machines: dict[UUID, ExecutionStateMachine] = {}
        self._cancelled: set[UUID] = set()
        self._context_service = context_service or ContextService()
        self._interventions: dict[UUID, dict[str, dict]] = {}
        self._intervention_events: dict[UUID, asyncio.Event] = {}
        self._slow_since: dict[UUID, dict[str, datetime]] = {}
        self._slow_notified: dict[UUID, set[str]] = {}
        self._slow_after = settings.slow_node_after_seconds
        self._event_cb: Callable[[UUID, dict], Awaitable[None]] | None = None

    def set_event_callback(self, cb: Callable[[UUID, dict], Awaitable[None]]) -> None:
        """注册实时事件回调（如 WebSocket 广播）：回调签名 (execution_id, message)。"""
        self._event_cb = cb

    async def _emit(self, execution_id: UUID, message: dict) -> None:
        if self._event_cb is None:
            return
        try:
            await self._event_cb(execution_id, message)
        except Exception:
            logger.exception("Event callback failed")

    def slow_nodes(self, execution_id: UUID) -> dict[str, dict]:
        """返回超阈值未干预的运行中节点（供 API 查询）：
        {node_id: {"since": ISO时间, "elapsed_seconds": int}}
        """
        return {
            nid: {
                "since": since.isoformat(),
                "elapsed_seconds": int((datetime.now(UTC).replace(tzinfo=None) - since).total_seconds()),
            }
            for nid, since in (self._slow_since.get(execution_id) or {}).items()
        }

    def intervene(self, execution_id: UUID, node_id: str, action: str,
                  provider: str | None = None, model: str | None = None) -> None:
        """用户干预请求：wait 清除慢标记；switch_model 取消节点并按新 provider/model 重排；
        terminate 取消整个执行。"""
        if action == "wait":
            self._ack_slow(execution_id, node_id)
            return
        if action == "terminate":
            self._cancel_events.get(execution_id, asyncio.Event()).set()
            return
        if action == "switch_model":
            self._interventions.setdefault(execution_id, {})[node_id] = {
                "action": action,
                "provider": provider,
                "model": model,
            }
            self._intervention_events.setdefault(execution_id, asyncio.Event()).set()

    def _ack_slow(self, execution_id: UUID, node_id: str) -> None:
        self._slow_since.get(execution_id, {}).pop(node_id, None)
        self._slow_notified.get(execution_id, set()).discard(node_id)

    def _mark_slow_if_needed(self, execution_id: UUID, node_id: str,
                             started_at: datetime) -> None:
        elapsed = (datetime.now(UTC).replace(tzinfo=None) - started_at).total_seconds()
        if elapsed < self._slow_after:
            return
        if node_id in self._slow_notified.get(execution_id, set()):
            return
        self._slow_since.setdefault(execution_id, {})[node_id] = started_at
        self._slow_notified.setdefault(execution_id, set()).add(node_id)

    async def execute_workflow(
        self,
        workflow: WorkflowDefinition,
        execution_id: UUID,
        db_factory,
        initial_context: dict | None = None,
    ) -> WorkflowResult:
        if workflow.validate_dag():
            pass
        else:
            raise ValueError("Workflow DAG contains a cycle")

        sm = ExecutionStateMachine(execution_id=execution_id)
        self._state_machines[execution_id] = sm
        scheduler = DAGScheduler(workflow)
        context = dict(initial_context or {})
        cancel_event = asyncio.Event()
        self._cancel_events[execution_id] = cancel_event
        intervention_event = self._intervention_events.setdefault(
            execution_id, asyncio.Event()
        )
        node_started: dict[str, datetime] = {}

        if self.is_cancel_requested(execution_id):
            cancel_event.set()

        sm.start(len(workflow.nodes))
        await self._emit(execution_id, {
            "type": "execution_status",
            "status": sm.status.value,
            "started_at": sm.started_at.isoformat() if sm.started_at else None,
        })
        semaphore = asyncio.Semaphore(self._max_concurrency)

        node_results: list[NodeResult] = []
        rerun_recommendations: list[dict] = []
        in_flight: dict[asyncio.Task, NodeDefinition] = {}

        async def cancel_in_flight() -> None:
            tasks = list(in_flight)
            for t in tasks:
                t.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            in_flight.clear()

        try:
            while not scheduler.is_complete():
                if cancel_event.is_set():
                    if not sm.is_terminal():
                        sm.cancel()
                    break

                if sm.status == ExecutionStatus.PAUSED:
                    await asyncio.sleep(0.1)
                    continue

                # 慢节点检测：对每个 in-flight 节点标记超阈值提醒
                for task, node in in_flight.items():
                    started = node_started.get(node.id)
                    if started:
                        self._mark_slow_if_needed(execution_id, node.id, started)

                # 干预处理：取消被要求切换模型的 in-flight 节点
                pending_interventions = self._interventions.get(execution_id, {})
                for task, node in list(in_flight.items()):
                    if node.id in pending_interventions:
                        task.cancel()
                        intervention_event.clear()

                running_ids = {n.id for n in in_flight.values()}
                for node in scheduler.get_ready_nodes():
                    if node.id in running_ids:
                        continue
                    task = asyncio.ensure_future(
                        self._execute_node(
                            node, context, execution_id, db_factory, semaphore, cancel_event
                        )
                    )
                    in_flight[task] = node
                    node_started[node.id] = datetime.now(UTC).replace(tzinfo=None)

                if not in_flight:
                    await asyncio.sleep(0.05)
                    continue

                cancel_watcher = asyncio.ensure_future(cancel_event.wait())
                intervene_watcher = asyncio.ensure_future(intervention_event.wait())
                slow_watcher = asyncio.ensure_future(asyncio.sleep(1))
                done, pending = await asyncio.wait(
                    [*in_flight.keys(), cancel_watcher, intervene_watcher, slow_watcher],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if cancel_watcher in done:
                    for t in pending:
                        t.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                    cancel_watcher.cancel()
                    intervene_watcher.cancel()
                    if not sm.is_terminal():
                        sm.cancel()
                    break
                cancel_watcher.cancel()
                intervene_watcher.cancel()
                slow_watcher.cancel()

                for task in [t for t in done if t in in_flight]:
                    node_def = in_flight.pop(task)
                    node_started.pop(node_def.id, None)
                    try:
                        result = task.result()
                    except asyncio.CancelledError:
                        result = NodeResult(
                            node_id=node_def.id,
                            status=NodeStatus.CANCELLED,
                            error="Execution cancelled",
                        )
                    except Exception as exc:
                        result = NodeResult(
                            node_id=node_def.id,
                            status=NodeStatus.FAILED,
                            error=str(exc),
                        )

                    # 节点级干预（switch_model）：取消后改配置重排，不终止执行
                    intervention = self._interventions.get(execution_id, {}).pop(
                        node_def.id, None
                    )
                    if intervention:
                        if result.status in (NodeStatus.CANCELLED, NodeStatus.FAILED):
                            self._apply_intervention(node_def, intervention)
                            node_results.append(result)
                            continue
                    self._ack_slow(execution_id, node_def.id)

                    if result.status == NodeStatus.FAILED:
                        sm.fail(result.error or "Node failed")
                        node_results.append(result)
                        await cancel_in_flight()
                        return self._build_result(
                            sm, node_results, context, rerun_recommendations
                        )

                    if result.status == NodeStatus.CANCELLED:
                        sm.cancel()
                        node_results.append(result)
                        await cancel_in_flight()
                        return self._build_result(
                            sm, node_results, context, rerun_recommendations
                        )

                    node_results.append(result)
                    recommendation = self._extract_rerun_recommendation(
                        result, node_def
                    )
                    if recommendation:
                        rerun_recommendations.append(recommendation)
                    context = _apply_output_mapping(node_def, result.output, context)
                    self._context_service.write_output(
                        context,
                        result.node_id,
                        result.output,
                        node_def.output_mapping,
                    )

                    scheduler.mark_completed(result.node_id)
                    sm.increment_progress()
                    await self._emit(execution_id, {
                        "type": "progress",
                        "completed": scheduler.completed_count,
                        "total": len(workflow.nodes),
                    })

            if not sm.is_terminal():
                sm.succeed()
            await self._emit(execution_id, {
                "type": "execution_status",
                "status": sm.status.value,
                "finished_at": sm.finished_at.isoformat() if sm.finished_at else None,
            })
        except asyncio.CancelledError:
            if not sm.is_terminal():
                sm.cancel()
        except Exception as exc:
            logger.exception("Execution %s loop crashed", execution_id)
            if not sm.is_terminal():
                sm.fail(str(exc))
        finally:
            self._state_machines.pop(execution_id, None)
            self._cancel_events.pop(execution_id, None)

        return self._build_result(
            sm, node_results, context, rerun_recommendations
        )

    @staticmethod
    def _apply_intervention(node_def, intervention: dict) -> None:
        """按干预请求重写节点执行配置（provider / executor_type / model）。

        切换模型 = 取消当前运行 → 换 provider/模型 → 重新调度执行同一节点。
        """
        provider = intervention.get("provider")
        if provider:
            config = node_def.config
            config.provider = provider
            from app.planner.planner_agent import PROVIDER_TO_EXECUTOR_TYPE

            derived = PROVIDER_TO_EXECUTOR_TYPE.get(provider)
            if derived:
                config.executor_type = derived
        model = intervention.get("model")
        if model:
            config = node_def.config
            config.model = model

    @staticmethod
    def _extract_rerun_recommendation(
        result: NodeResult, node_def
    ) -> dict | None:
        """从 audit 节点的输出中提取 recommend_rerun 信号（仅提示，不自动重跑）。"""
        if result.status != NodeStatus.SUCCEEDED or node_def is None:
            return None
        meta = (result.output or {}).get("_executor_metadata") or {}
        ensemble = meta.get("ensemble") if isinstance(meta, dict) else None
        if not isinstance(ensemble, dict) or ensemble.get("mode") != "audit":
            return None
        if not ensemble.get("recommend_rerun"):
            return None
        return {
            "node_id": node_def.id,
            "critical_count": ensemble.get("critical_count", 0),
            "findings_count": len(ensemble.get("findings") or []),
            "reviewers": ensemble.get("reviewers") or [],
        }

    async def _execute_node(
        self,
        node_def,
        context: dict,
        execution_id: UUID,
        db_factory,
        semaphore: asyncio.Semaphore,
        cancel_event: asyncio.Event,
    ) -> NodeResult:
        async with semaphore:
            if cancel_event.is_set():
                return NodeResult(
                    node_id=node_def.id,
                    status=NodeStatus.CANCELLED,
                    error="Execution cancelled",
                )

            started_at = datetime.now(UTC).replace(tzinfo=None)

            async with db_factory() as session:
                node_exec = NodeExecutionModel(
                    execution_id=execution_id,
                    node_id=node_def.id,
                    node_type=node_def.type.value,
                    status="running",
                    started_at=started_at,
                )
                session.add(node_exec)
                await session.flush()
                exec_id = node_exec.id
                session.add(
                    ExecutionLogModel(
                        execution_id=execution_id,
                        node_execution_id=exec_id,
                        level="info",
                        message=f"Node {node_def.id} ({node_def.type.value}) started",
                    )
                )
                await session.commit()

            await self._emit(execution_id, {
                "type": "node_started",
                "node_id": node_def.id,
                "node_type": node_def.type.value,
                "node_execution_id": str(exec_id),
                "started_at": started_at.isoformat(),
            })

            broadcast = None
            if self._event_cb is not None:
                async def broadcast(msg: dict) -> None:
                    await self._emit(execution_id, msg)
            sink = NodeLogSink(
                execution_id=execution_id,
                node_id=node_def.id,
                node_execution_id=exec_id,
                db_factory=db_factory,
                broadcast=broadcast,
            )
            sink.start()

            try:
                result = await self._node_runner.handle_node(
                    node_def, context, log_sink=sink.write
                )
            except asyncio.CancelledError:
                await sink.stop()
                finished_at = datetime.now(UTC).replace(tzinfo=None)
                async with db_factory() as session:
                    stored = await session.get(NodeExecutionModel, exec_id)
                    if stored:
                        stored.status = NodeStatus.CANCELLED.value
                        stored.error = "Execution cancelled"
                        stored.finished_at = finished_at
                    session.add(
                        ExecutionLogModel(
                            execution_id=execution_id,
                            node_execution_id=exec_id,
                            level="info",
                            message=f"Node {node_def.id} cancelled",
                        )
                    )
                    await session.commit()
                await self._emit(execution_id, {
                    "type": "node_finished",
                    "node_id": node_def.id,
                    "node_execution_id": str(exec_id),
                    "status": NodeStatus.CANCELLED.value,
                    "finished_at": finished_at.isoformat(),
                })
                return NodeResult(
                    node_id=node_def.id,
                    status=NodeStatus.CANCELLED,
                    error="Execution cancelled",
                    started_at=started_at,
                    finished_at=finished_at,
                )

            await sink.stop()
            finished_at = datetime.now(UTC).replace(tzinfo=None)

            async with db_factory() as session:
                stored = await session.get(NodeExecutionModel, exec_id)
                if stored:
                    stored.status = result.status.value
                    stored.output = result.output
                    stored.error = result.error
                    stored.finished_at = finished_at
                if result.status == NodeStatus.FAILED:
                    session.add(
                        ExecutionLogModel(
                            execution_id=execution_id,
                            node_execution_id=exec_id,
                            level="error",
                            message=(
                                f"Node {node_def.id} failed: "
                                f"{result.error or 'unknown error'}"
                            ),
                        )
                    )
                elif result.status == NodeStatus.SUCCEEDED:
                    session.add(
                        ExecutionLogModel(
                            execution_id=execution_id,
                            node_execution_id=exec_id,
                            level="info",
                            message=f"Node {node_def.id} completed successfully",
                        )
                    )
                await session.commit()

            await self._emit(execution_id, {
                "type": "node_finished",
                "node_id": node_def.id,
                "node_execution_id": str(exec_id),
                "status": result.status.value,
                "finished_at": finished_at.isoformat(),
                "error": result.error,
            })

            return NodeResult(
                node_id=node_def.id,
                status=result.status,
                output=result.output,
                error=result.error,
                started_at=started_at,
                finished_at=finished_at,
            )

    def _build_result(
        self,
        sm: ExecutionStateMachine,
        node_results: list[NodeResult],
        context: dict,
        rerun_recommendations: list[dict] | None = None,
    ) -> WorkflowResult:
        rerun_recommendations = rerun_recommendations or []
        if rerun_recommendations:
            context["_rerun_recommendations"] = rerun_recommendations
        return WorkflowResult(
            execution_id=sm.execution_id,
            workflow_id=sm.execution_id,
            status=sm.status,
            node_results=node_results,
            context=context,
            rerun_recommendations=rerun_recommendations,
            started_at=sm.started_at,
            finished_at=sm.finished_at,
        )

    async def pause(self, execution_id: UUID) -> None:
        sm = self._state_machines.get(execution_id)
        if not sm:
            raise ValueError(f"Execution {execution_id} not found")
        sm.pause()

    async def resume(self, execution_id: UUID) -> None:
        sm = self._state_machines.get(execution_id)
        if not sm:
            raise ValueError(f"Execution {execution_id} not found")
        sm.resume()

    async def cancel(self, execution_id: UUID) -> None:
        sm = self._state_machines.get(execution_id)
        if not sm:
            raise ValueError(f"Execution {execution_id} not found")
        cancel_event = self._cancel_events.get(execution_id)
        if cancel_event:
            cancel_event.set()
        self._cancelled.add(execution_id)
        sm.cancel()

    def is_cancel_requested(self, execution_id: UUID) -> bool:
        return execution_id in self._cancelled

    def get_status(self, execution_id: UUID) -> ExecutionStatus:
        sm = self._state_machines.get(execution_id)
        if not sm:
            raise ValueError(f"Execution {execution_id} not found")
        return sm.status
