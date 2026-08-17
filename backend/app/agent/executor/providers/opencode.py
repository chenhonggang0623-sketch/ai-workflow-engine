import json

from app.agent.executor.providers.base_cli import BaseCLIExecutor
from app.agent.executor.types import ExecutionRequest
from app.core.app_config import config_store


class OpenCodeExecutor(BaseCLIExecutor):
    def resolve_command(self) -> str:
        return config_store.get("opencode_path", "opencode")

    def _build_args(self, prompt: str, request: ExecutionRequest) -> list[str]:
        args = ["run", prompt]
        config = request.config or {}
        ec = config.get("executor_config", {})
        working_dir = ec.get("working_directory") or config.get("working_directory") or request.working_directory
        if working_dir:
            args.extend(["--dir", str(working_dir)])
        model = ec.get("model") or config.get("model")
        if model:
            args.extend(["--model", str(model)])
        agent = ec.get("agent") or config.get("agent")
        if agent:
            args.extend(["--agent", str(agent)])
        if ec.get("auto_approve") or config.get("auto_approve"):
            args.append("--auto")
        return args
