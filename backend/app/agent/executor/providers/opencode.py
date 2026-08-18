import json

from app.agent.executor.providers.base_cli import BaseCLIExecutor
from app.agent.executor.types import ExecutionRequest
from app.core.app_config import config_store


class OpenCodeExecutor(BaseCLIExecutor):
    # P0-1: prompt 走 stdin（多行参数在 Windows cmd.exe 下会被截断，opencode 是
    # .CMD shim，命令行只收到首行）。见 EXECUTION_PROBLEMS.md P0-1。
    prompt_via_stdin = True

    def resolve_command(self) -> str:
        return config_store.get("opencode_path", "opencode")

    def _build_args(self, prompt: str, request: ExecutionRequest) -> list[str]:
        # --format json: machine-readable JSONL events on stdout and no TUI
        # banner / ANSI noise on stderr, so console output stays clean.
        # Prompt 由 base_cli 写入 stdin，不再作为 run 的位置参数。
        args = ["run", "--format", "json"]
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

    def _begin_execution(self, request: ExecutionRequest) -> None:
        self._event_stats = {"text": 0, "tool_use": 0, "error": 0}
        self._event_errors: list[str] = []

    def _process_line(self, text: str, stream: str) -> str | None:
        """Parse `--format json` events into a clean console/output stream.

        - text events  -> the assistant text (the real output)
        - tool_use     -> a compact "[tool:<name>] <title>" activity line
        - error events -> a "[error] <message>" line (P2-1: 不透明错误透传)
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
            self._event_stats["text"] += 1
            return part.get("text") or None
        if etype == "tool_use":
            self._event_stats["tool_use"] += 1
            state = part.get("state") or {}
            title = (state.get("title") or "").strip()
            tool = (part.get("tool") or "tool").strip()
            line = f"[tool:{tool}] {title}".strip()
            return line or None
        if etype == "error":
            self._event_stats["error"] += 1
            message = (
                ev.get("error")
                or part.get("error")
                or part.get("message")
                or part.get("text")
                or ""
            )
            if isinstance(message, dict):
                message = json.dumps(message, ensure_ascii=False)
            message = str(message).strip()
            if message:
                self._event_errors.append(message)
                return f"[error] {message}"
            return None
        return None

    def _validate_output(
        self, stdout_lines: list[str], stderr_lines: list[str],
        request: ExecutionRequest,
    ) -> tuple[bool, str | None]:
        """opencode 的成功判定：出现过 text 或 tool_use 事件才算真的干了活。

        - 只有 error 事件（如上游 401 被包装成 UnknownError / ref: err_xxx）
          -> 判失败并透传错误，避免"成功但没产物"。
        - 空输出（P0-1 的截断场景：进程秒退、无任何事件）-> 判失败。
        """
        stats = getattr(self, "_event_stats", None)
        if stats and (stats["text"] > 0 or stats["tool_use"] > 0):
            return True, None
        errors = getattr(self, "_event_errors", [])
        stderr_text = "\n".join(stderr_lines)
        if errors:
            reason = (
                "opencode finished with no work performed. "
                f"Agent errors: {'; '.join(errors[:5])}"
            )
            if stderr_text:
                reason += f" stderr: {stderr_text[:300]}"
            return False, reason
        if stderr_text:
            return False, (
                "opencode exited 0 but produced no output "
                f"(silent failure). stderr: {stderr_text[:300]}"
            )
        return False, (
            "opencode exited 0 but produced no output "
            "(silent failure, no text or tool_use events)"
        )

    def _success_metadata(self) -> dict:
        return {"event_stats": dict(getattr(self, "_event_stats", {}))}