from app.agent.executor.types import ExecutionRequest, ExecutionResult


class BaseExecutor:
    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        raise NotImplementedError
