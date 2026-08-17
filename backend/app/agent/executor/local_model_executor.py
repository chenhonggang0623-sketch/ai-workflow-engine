import logging

from app.agent.executor.base import BaseExecutor
from app.agent.executor.types import ExecutionRequest, ExecutionResult
from app.agent.executor.llm_executor import LLMExecutor
from app.agent.llm_gateway import LLMGateway
from app.agent.registry import AgentRegistry
from app.mcp.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


class LocalModelExecutor(BaseExecutor):
    def __init__(
        self,
        llm_gateway: LLMGateway,
        tool_registry: ToolRegistry | None = None,
        agent_registry: AgentRegistry | None = None,
    ):
        self._inner = LLMExecutor(
            llm_gateway=llm_gateway,
            tool_registry=tool_registry,
            agent_registry=agent_registry,
        )

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        config = request.config or {}
        ec = config.get("executor_config", {})
        config["model_params"] = {
            "provider": ec.get("provider", "openai"),
            "base_url": ec.get("base_url", "http://localhost:11434/v1"),
            "model": ec.get("model", "qwen2.5-coder:7b"),
            "temperature": ec.get("temperature", 0.7),
            "max_tokens": ec.get("max_tokens", 4096),
        }
        return await self._inner.execute(request)
