from app.agent.executor.providers.base_cli import BaseCLIExecutor
from app.agent.executor.types import ExecutionRequest
from app.core.app_config import config_store


class CodexExecutor(BaseCLIExecutor):
    def resolve_command(self) -> str:
        return config_store.get("codex_path", "codex")

    def _build_args(self, prompt: str, request: ExecutionRequest) -> list[str]:
        args = ["exec", prompt, "--skip-git-repo-check"]
        config = request.config or {}
        ec = config.get("executor_config", {})
        working_dir = ec.get("working_directory") or config.get("working_directory") or request.working_directory
        if working_dir:
            args.extend(["--cd", str(working_dir)])
        sandbox = ec.get("sandbox") or config.get("sandbox")
        if sandbox:
            args.extend(["--sandbox", str(sandbox)])
        if ec.get("json_output") or config.get("json_output"):
            args.append("--json")
        return args