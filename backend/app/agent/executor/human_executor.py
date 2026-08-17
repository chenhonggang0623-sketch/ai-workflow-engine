import logging

from app.agent.executor.base import BaseExecutor
from app.agent.executor.types import ExecutionRequest, ExecutionResult

logger = logging.getLogger(__name__)


class HumanExecutor(BaseExecutor):
    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        config = request.config or {}
        ec = config.get("executor_config", {})
        prompt_message = (
            ec.get("prompt_message")
            or config.get("prompt_message")
            or "Awaiting human input"
        )
        logger.info("Human executor waiting for input: %s", prompt_message)
        return ExecutionResult(
            success=True,
            output={
                "status": "awaiting_input",
                "task": request.task,
                "prompt_message": prompt_message,
            },
            metadata={"requires_input": True},
        )
