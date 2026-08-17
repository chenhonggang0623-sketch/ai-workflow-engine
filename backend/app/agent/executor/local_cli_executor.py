import logging

from app.agent.executor.base import BaseExecutor
from app.agent.executor.types import ExecutionRequest, ExecutionResult
from app.agent.executor.providers import (
    OpenCodeExecutor,
    ClaudeCodeExecutor,
    CodexExecutor,
)

logger = logging.getLogger(__name__)


PROVIDER_MAP = {
    "opencode": OpenCodeExecutor,
    "opencode_cli": OpenCodeExecutor,
    "claude": ClaudeCodeExecutor,
    "claude-code": ClaudeCodeExecutor,
    "claude_cli": ClaudeCodeExecutor,
    "codex": CodexExecutor,
    "codex_cli": CodexExecutor,
}


class LocalCLIExecutor(BaseExecutor):
    def __init__(self):
        self._providers: dict[str, BaseExecutor] = {}

    def _get_provider(self, name: str) -> BaseExecutor | None:
        name = name.lower()
        if name not in self._providers:
            cls = PROVIDER_MAP.get(name)
            if cls is None:
                return None
            self._providers[name] = cls()
        return self._providers[name]

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        config = request.config or {}
        ec = config.get("executor_config", {})
        provider_name = (
            ec.get("provider")
            or config.get("provider")
            or config.get("agent_provider", "opencode")
        )

        if ec.get("working_directory") and request.working_directory is None:
            request.working_directory = ec["working_directory"]

        if ec.get("model") and config.get("model") is None:
            config["model"] = ec["model"]

        provider = self._get_provider(provider_name)
        if provider is None:
            return ExecutionResult(
                success=False,
                error=f"Unknown CLI provider: {provider_name}. "
                      f"Supported: {list(PROVIDER_MAP.keys())}",
            )

        return await provider.execute(request)
