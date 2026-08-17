import logging

from app.agent.executor.base import BaseExecutor
from app.agent.executor.types import ExecutionRequest, ExecutionResult

logger = logging.getLogger(__name__)


class MCPExecutor(BaseExecutor):
    def __init__(self, bridge=None):
        self._bridge = bridge

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        config = request.config or {}
        tool_name = config.get("tool_id") or config.get("tool_name", "")
        params = request.task or {}

        if not tool_name:
            return ExecutionResult(
                success=False,
                error="No tool_id or tool_name specified in config",
            )

        if self._bridge is None:
            return ExecutionResult(
                success=False,
                error="MCPBridge not configured",
            )

        try:
            result = await self._bridge.call_tool(
                server_name=config.get("server_name", "default"),
                tool_name=tool_name,
                arguments=params,
            )
            return ExecutionResult(
                success=True,
                output={"result": result},
                metadata={"tool": tool_name},
            )
        except Exception as exc:
            logger.exception("MCP tool execution failed: %s", tool_name)
            return ExecutionResult(
                success=False,
                error=f"MCP tool {tool_name} failed: {exc}",
            )
