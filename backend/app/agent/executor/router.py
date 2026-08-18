import logging

from pydantic import ValidationError

from app.agent.executor.base import BaseExecutor
from app.agent.executor.types import ExecutorType, ExecutionRequest, ExecutionResult
from app.agent.executor.llm_executor import LLMExecutor
from app.agent.executor.local_cli_executor import LocalCLIExecutor
from app.agent.executor.local_model_executor import LocalModelExecutor
from app.agent.executor.human_executor import HumanExecutor
from app.agent.executor.mcp_executor import MCPExecutor
from app.agent.providers import (
    AgentProviderRegistry,
    PROVIDER_OPENAI,
    PROVIDER_OPENCODE_CLI,
    PROVIDER_CLAUDE_CLI,
    PROVIDER_LOCAL_MODEL,
)

logger = logging.getLogger(__name__)

PROVIDER_TO_EXECUTOR_TYPE = {
    PROVIDER_OPENAI: ExecutorType.LLM_API,
    PROVIDER_OPENCODE_CLI: ExecutorType.LOCAL_CLI,
    PROVIDER_CLAUDE_CLI: ExecutorType.LOCAL_CLI,
    PROVIDER_LOCAL_MODEL: ExecutorType.LOCAL_MODEL,
}


class ExecutorRouter:
    def __init__(
        self,
        llm_executor: LLMExecutor | None = None,
        local_cli_executor: LocalCLIExecutor | None = None,
        local_model_executor: LocalModelExecutor | None = None,
        human_executor: HumanExecutor | None = None,
        mcp_executor: MCPExecutor | None = None,
        provider_registry: AgentProviderRegistry | None = None,
    ):
        self._llm = llm_executor
        self._local_cli = local_cli_executor
        self._local_model = local_model_executor
        self._human = human_executor
        self._mcp = mcp_executor
        self._provider_registry = provider_registry

    def get_executor(self, executor_type: str | ExecutorType) -> BaseExecutor | None:
        if isinstance(executor_type, str):
            try:
                executor_type = ExecutorType(executor_type)
            except ValueError:
                logger.warning("Unknown executor type: %s", executor_type)
                return None

        if executor_type == ExecutorType.LLM_API:
            return self._llm
        elif executor_type == ExecutorType.LOCAL_CLI:
            return self._local_cli
        elif executor_type == ExecutorType.LOCAL_MODEL:
            return self._local_model
        elif executor_type == ExecutorType.HUMAN:
            return self._human
        elif executor_type == ExecutorType.MCP:
            return self._mcp

        return None

    def resolve_provider_name(self, config: dict) -> str | None:
        provider = config.get("provider") or config.get("agent_provider")
        if provider:
            return str(provider)
        executor_type = config.get("executor_type")
        if executor_type == ExecutorType.LOCAL_CLI.value:
            return PROVIDER_OPENCODE_CLI
        return None

    async def execute(
        self,
        executor_type: str | ExecutorType,
        request: ExecutionRequest,
    ) -> ExecutionResult:
        config = request.config or {}
        provider_name = self.resolve_provider_name(config)
        try:
            return await self._dispatch(executor_type, request, config, provider_name)
        except ValidationError as exc:
            logger.warning(
                "Invalid ExecutionResult from provider '%s': %s",
                provider_name or executor_type,
                exc,
            )
            return ExecutionResult(
                success=False,
                error=(
                    f"Provider '{provider_name or executor_type}' returned an "
                    f"invalid result (output must be a JSON object): {exc.errors()[0]['msg'] if exc.errors() else exc}"
                ),
            )

    async def _dispatch(
        self,
        executor_type: str | ExecutorType,
        request: ExecutionRequest,
        config: dict,
        provider_name: str | None,
    ) -> ExecutionResult:
        if provider_name and self._provider_registry is not None:
            provider = self._provider_registry.get(provider_name)
            if provider is None:
                logger.warning(
                    "Provider '%s' not registered. Falling back to executor_type dispatch.",
                    provider_name,
                )
            else:
                input_text = self._build_input_text(request)
                result = await provider.execute(
                    system_prompt=config.get("system_prompt") or "",
                    input_text=input_text,
                    context=request.context or {},
                    config=config,
                    log_sink=request.log_sink,
                )
                return self._result_from_provider(result)

        executor = self.get_executor(executor_type)
        if executor is None:
            return ExecutionResult(
                success=False,
                error=f"No executor available for type: {executor_type}",
            )
        return await executor.execute(request)

    def _build_input_text(self, request: ExecutionRequest) -> str:
        task = request.task or {}
        for key in ("prompt", "task", "message"):
            if task.get(key):
                return str(task[key])
        import json

        return json.dumps(task, ensure_ascii=False, indent=2)

    def _result_from_provider(self, result: dict) -> ExecutionResult:
        if not result.get("status") == "success":
            return ExecutionResult(
                success=False,
                error=result.get("error") or "Agent provider execution failed",
                output=self._coerce_output(result.get("output")),
            )
        metadata = {
            "provider": result.get("provider"),
            "status": "success",
        }
        # 携带 ensemble 明细（scores / findings / recommend_rerun 等），
        # 供执行详情页 / 实时页渲染，避免在路由边界丢失。
        if isinstance(result.get("ensemble"), dict):
            metadata["ensemble"] = result["ensemble"]
        return ExecutionResult(
            success=True,
            output=self._coerce_output(result.get("output")),
            metadata=metadata,
        )

    @staticmethod
    def _coerce_output(output) -> dict:
        """输出协议归一化：所有 provider 的输出必须是 JSON object。

        裸字符串 / 标量 / 列表统一包装为 {"result": <value>}，
        保证下游 _apply_output_mapping 与 _executor_metadata 注入安全。
        """
        if output is None:
            return {}
        if isinstance(output, dict):
            return output
        return {"result": output}
