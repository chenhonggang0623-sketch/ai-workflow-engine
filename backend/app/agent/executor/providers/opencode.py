import json

from app.agent.executor.providers.base_cli import BaseCLIExecutor
from app.agent.executor.types import ExecutionRequest
from app.core.app_config import config_store


class OpenCodeExecutor(BaseCLIExecutor):
    def resolve_command(self) -> str:
        return config_store.get("opencode_path", "opencode")

    def _build_args(self, prompt: str, request: ExecutionRequest) -> list[str]:
        # --format json: machine-readable JSONL events on stdout and no TUI
        # banner / ANSI noise on stderr, so console output stays clean.
        args = ["run", prompt, "--format", "json"]
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

    def _process_line(self, text: str, stream: str) -> str | None:
        """Parse `--format json` events into a clean console/output stream.

        - text events  -> the assistant text (the real output)
        - tool_use     -> a compact "[tool:<name>] <title>" activity line
        - everything else (step_start / step_finish / ...) -> dropped
        """
        text = super()._process_line(text, stream)
        if text is None:
            return None
        if stream != "stdout":
            return text
        try:
            ev = json.loads(text)
        except ValueError:
            return None
        if not isinstance(ev, dict):
            return None
        etype = ev.get("type")
        part = ev.get("part") or {}
        if etype == "text":
            return part.get("text") or None
        if etype == "tool_use":
            state = part.get("state") or {}
            title = (state.get("title") or "").strip()
            tool = (part.get("tool") or "tool").strip()
            line = f"[tool:{tool}] {title}".strip()
            return line or None
        return None
