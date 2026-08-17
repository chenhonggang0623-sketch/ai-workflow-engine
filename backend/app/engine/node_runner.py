import asyncio
import copy
from datetime import UTC, datetime

from app.engine.types import (
    NodeDefinition,
    NodeResult,
    NodeStatus,
    NodeType,
    InputMapping,
    OutputMapping,
)
from app.agent.executor.types import ExecutionRequest, ExecutionResult
from app.agent.executor.router import ExecutorRouter
from app.engine.context_service import ContextService, DEFAULT_MAX_CONTEXT_CHARS
from app.engine.prompt_factory import build_node_prompt


def _resolve_jsonpath(obj: dict, path: str):
    keys = path.lstrip("$.").split(".")
    val = obj
    for k in keys:
        if isinstance(val, dict):
            val = val.get(k)
        else:
            return None
    return val


def _set_jsonpath(obj: dict, path: str, value):
    keys = path.lstrip("$.").split(".")
    cur = obj
    for k in keys[:-1]:
        if k not in cur:
            cur[k] = {}
        cur = cur[k]
    cur[keys[-1]] = value


def _apply_input_mapping(node: NodeDefinition, context: dict) -> dict:
    node_input = {}
    for mapping in node.input_mapping:
        val = _resolve_jsonpath(context, mapping.source)
        node_input[mapping.target] = val
    return node_input


def _apply_output_mapping(node: NodeDefinition, output: dict, context: dict) -> dict:
    ctx = copy.deepcopy(context)
    for mapping in node.output_mapping:
        val = output.get(mapping.source)
        if val is not None:
            _set_jsonpath(ctx, mapping.target, val)
    return ctx


async def _execute_with_timeout(handler, node: NodeDefinition, node_input: dict,
                                ctx: dict, timeout: int, log_sink=None) -> dict:
    return await asyncio.wait_for(
        handler(node, node_input, ctx, log_sink) if log_sink is not None
        else handler(node, node_input, ctx),
        timeout=timeout,
    )


class NodeRunner:
    def __init__(
        self,
        agent_executor=None,
        tool_registry=None,
        executor_router=None,
        context_service: ContextService | None = None,
    ):
        self._agent = agent_executor
        self._tools = tool_registry
        self._router = executor_router
        self._context_service = context_service or ContextService()

    async def handle_node(
        self,
        node: NodeDefinition,
        context: dict,
        log_sink=None,
    ) -> NodeResult:
        node_input = _apply_input_mapping(node, context)
        if node.type == NodeType.CONDITION:
            node_input = {**context, **node_input}

        timeout = node.config.timeout_seconds
        retry_config = node.config.retry_config
        max_retries = retry_config.max_retries
        backoff = retry_config.backoff_seconds

        started_at = datetime.now(UTC).replace(tzinfo=None)

        handler = self._get_handler(node.type)
        if handler is None:
            return NodeResult(
                node_id=node.id,
                status=NodeStatus.FAILED,
                error=f"No handler for node type {node.type}",
                started_at=started_at,
                finished_at=datetime.now(UTC).replace(tzinfo=None),
            )

        for attempt in range(max_retries + 1):
            try:
                output = await _execute_with_timeout(
                    handler, node, node_input, context, timeout, log_sink
                )

                return NodeResult(
                    node_id=node.id,
                    status=NodeStatus.SUCCEEDED,
                    output=output,
                    started_at=started_at,
                    finished_at=datetime.now(UTC).replace(tzinfo=None),
                )
            except asyncio.TimeoutError:
                error = f"Node {node.id} timed out after {timeout}s"
                if attempt < max_retries:
                    await asyncio.sleep(backoff)
                    continue
                return NodeResult(
                    node_id=node.id,
                    status=NodeStatus.FAILED,
                    error=error,
                    started_at=started_at,
                    finished_at=datetime.now(UTC).replace(tzinfo=None),
                )
            except Exception as exc:
                error = f"Node {node.id} failed: {exc}"
                if attempt < max_retries:
                    await asyncio.sleep(backoff)
                    continue
                return NodeResult(
                    node_id=node.id,
                    status=NodeStatus.FAILED,
                    error=error,
                    started_at=started_at,
                    finished_at=datetime.now(UTC).replace(tzinfo=None),
                )

        return NodeResult(
            node_id=node.id,
            status=NodeStatus.FAILED,
            error="Exhausted all retries",
            started_at=started_at,
            finished_at=datetime.now(UTC).replace(tzinfo=None),
        )

    def _get_handler(self, node_type: NodeType):
        handlers = {
            NodeType.AGENT: self._run_agent,
            NodeType.TOOL: self._run_tool,
            NodeType.CONDITION: self._run_condition,
            NodeType.LOOP: self._run_loop,
            NodeType.HUMAN: self._run_human,
            NodeType.PLANNER: self._run_planner,
        }
        return handlers.get(node_type)

    async def _run_agent(self, node: NodeDefinition, node_input: dict, ctx: dict,
                         log_sink=None) -> dict:
        if self._router is not None:
            # system_prompt 缺失时用契约驱动的提示词工厂兜底生成
            if not node.config.system_prompt:
                node.config.system_prompt = build_node_prompt(node.model_dump())
            shared_context = self._context_service.build_agent_context(
                node, node_input, ctx
            )
            request = ExecutionRequest(
                task=node_input,
                context=shared_context,
                config=node.config.model_dump(),
                working_directory=node.config.working_directory,
                timeout=node.config.timeout_seconds,
                log_sink=log_sink,
            )
            result = await self._router.execute(node.config.executor_type, request)
            if not result.success:
                raise RuntimeError(result.error)
            output = result.output or {}
            if result.metadata:
                output["_executor_metadata"] = result.metadata
            return output

        if self._agent is None:
            return {"output": "AgentExecutor not configured"}
        result = await self._agent.execute(
            agent_id=node.config.agent_id or node.id,
            node_input=node_input,
            context={},
            system_prompt=node.config.system_prompt,
        )
        return result

    async def _run_tool(self, node: NodeDefinition, node_input: dict, ctx: dict = None, log_sink=None) -> dict:
        if self._tools is None:
            return {"output": "ToolRegistry not configured"}
        result = await self._tools.execute(
            node.config.tool_id or node.id, node_input
        )
        return result

    async def _run_condition(self, node: NodeDefinition, node_input: dict, ctx: dict = None, log_sink=None) -> dict:
        expr = node.config.expression or ""
        if not expr:
            return {"condition_result": True}
        try:
            result = eval(expr, {"__builtins__": {}}, {**node_input, **(ctx or {})})
            return {"condition_result": result}
        except Exception as exc:
            raise RuntimeError(f"Condition eval failed: {exc}") from exc

    async def _run_loop(self, node: NodeDefinition, node_input: dict, ctx: dict = None, log_sink=None) -> dict:
        max_iter = node.config.max_iterations or 1
        return {"iterations": max_iter, "body_nodes": node.config.body_node_ids or []}

    async def _run_human(self, node: NodeDefinition, node_input: dict, ctx: dict = None, log_sink=None) -> dict:
        return {"status": "awaiting_input", "input": node_input}

    async def _run_planner(self, node: NodeDefinition, node_input: dict, ctx: dict = None, log_sink=None) -> dict:
        return {"plan": f"plan from {node.label}", "input": node_input}

    def apply_output_mapping(self, node: NodeDefinition, output: dict, context: dict) -> dict:
        return _apply_output_mapping(node, output, context)
