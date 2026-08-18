import json
import logging

from app.agent.executor.base import BaseExecutor
from app.agent.executor.types import ExecutionRequest, ExecutionResult
from app.agent.llm_gateway import LLMGateway
from app.agent.registry import AgentRegistry
from app.agent.prompt_template import PromptTemplate
from app.mcp.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

CONTEXT_TEXT_LIMIT = 16_000


def _compact_context(context: dict) -> str:
    """渲染共享上下文为紧凑文本；跳过 _context_meta 之外的内部键。"""
    try:
        payload = {
            k: v for k, v in context.items() if not k.startswith("_")
        }
        text = json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(context)
    if len(text) > CONTEXT_TEXT_LIMIT:
        text = text[:CONTEXT_TEXT_LIMIT] + "\n...(context truncated)"
    return text


class LLMExecutor(BaseExecutor):
    def __init__(
        self,
        llm_gateway: LLMGateway,
        tool_registry: ToolRegistry | None = None,
        agent_registry: AgentRegistry | None = None,
    ):
        self._llm = llm_gateway
        self._tools = tool_registry
        self._registry = agent_registry

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        config = request.config or {}
        system_prompt = config.get("system_prompt")
        agent_id = config.get("agent_id", "default")
        context = request.context or {}
        ec = config.get("executor_config", {})
        model_config = dict(
            ec.get("model_config")
            or config.get("model_params")
            or config.get("model_config")
            or {}
        )

        if not system_prompt and self._registry:
            agent_def = await self._registry.get(agent_id)
            if agent_def:
                definition = agent_def.get("definition", {})
                system_prompt = definition.get("system_prompt")
                if not model_config:
                    model_config = definition.get("model_config", {})

        if not system_prompt:
            system_prompt = "You are a helpful assistant."

        rendered_system = PromptTemplate.render(system_prompt, context)

        user_content = json.dumps(request.task, ensure_ascii=False)
        if context:
            context_text = _compact_context(context)
            if context_text:
                user_content = f"{user_content}\n\n# Shared Upstream Context\n{context_text}"

        messages = [
            {"role": "system", "content": rendered_system},
            {"role": "user", "content": user_content},
        ]

        tool_defs = self._tools.list_tools() if self._tools else []
        openai_tools = []
        for td in tool_defs:
            if td.schema:
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": td.id,
                        "description": td.description,
                        "parameters": td.schema,
                    },
                })

        try:
            response = await self._llm.chat(
                model_config=model_config,
                messages=messages,
                tools=openai_tools if openai_tools else None,
            )
        except Exception as exc:
            logger.exception("LLM chat failed")
            return ExecutionResult(success=False, error=str(exc))

        tool_results = []
        while response.get("tool_calls"):
            for tc in response["tool_calls"]:
                func_name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}

                if self._tools:
                    tool_result = await self._tools.execute(func_name, args)
                else:
                    tool_result = {"error": "ToolRegistry not available"}

                tool_results.append({
                    "tool_call_id": tc["id"],
                    "tool_name": func_name,
                    "result": tool_result,
                })

                messages.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": func_name,
                            "arguments": tc["function"]["arguments"],
                        },
                    }],
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(tool_result, ensure_ascii=False),
                })

            try:
                response = await self._llm.chat(
                    model_config=model_config,
                    messages=messages,
                    tools=openai_tools if openai_tools else None,
                )
            except Exception as exc:
                logger.exception("LLM chat failed during tool loop")
                return ExecutionResult(
                    success=False,
                    error=str(exc),
                    metadata={"partial_tool_results": tool_results},
                )

        return ExecutionResult(
            success=True,
            output={
                "output": response.get("content", ""),
                "tool_calls": tool_results,
                "usage": response.get("usage", {}),
            },
            metadata={"usage": response.get("usage", {})},
        )
