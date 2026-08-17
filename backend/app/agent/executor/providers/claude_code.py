from app.agent.executor.providers.base_cli import BaseCLIExecutor
from app.agent.executor.types import ExecutionRequest
from app.core.app_config import config_store


class ClaudeCodeExecutor(BaseCLIExecutor):
    def resolve_command(self) -> str:
        return config_store.get("claude_code_path", "claude")

    def _build_args(self, prompt: str, request: ExecutionRequest) -> list[str]:
        args = ["-p", prompt]
        config = request.config or {}
        ec = config.get("executor_config", {})
        model = ec.get("model") or config.get("model")
        if model:
            args.extend(["--model", str(model)])
        agent = ec.get("agent") or config.get("agent")
        if agent:
            args.extend(["--agent", str(agent)])
        if ec.get("allow_dangerously_skip_permissions") or config.get("allow_dangerously_skip_permissions"):
            args.append("--allow-dangerously-skip-permissions")
        return args
