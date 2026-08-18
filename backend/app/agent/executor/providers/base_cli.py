import asyncio
import json
import logging
import os
import re
import shutil
import signal

from app.agent.executor.base import BaseExecutor
from app.agent.executor.types import ExecutionRequest, ExecutionResult

logger = logging.getLogger(__name__)

_ANSI_RE = re.compile(r"\x1b(?:\[[0-9;?]*[a-zA-Z]|\][^\x07]*(?:\x07|\x1b\\))")


class BaseCLIExecutor(BaseExecutor):
    command: str = ""
    args_template: list[str] = []
    # 多行 prompt 以命令行参数传递时，在 Windows 会被 cmd.exe 截断（.CMD shim
    # 在第一个换行符处截断），导致 agent 空转。置 True 时 prompt 改走 stdin，
    # 跨平台安全。见 EXECUTION_PROBLEMS.md P0-1。
    prompt_via_stdin: bool = False
    # 成功判定要求至少产出非空输出，避免"静默失败"（空回复 / 模型没干活）
    # 伪装成成功。见 EXECUTION_PROBLEMS.md P0-2。
    require_output: bool = True

    def _task_text(self, request: ExecutionRequest) -> str:
        task = request.task or {}
        for key in ("prompt", "task", "message"):
            if task.get(key):
                return str(task[key])
        if task:
            return json.dumps(task, ensure_ascii=False, indent=2)
        return ""

    def _build_prompt(self, request: ExecutionRequest) -> str:
        task_text = self._task_text(request)
        config = request.config or {}
        system_prompt = config.get("system_prompt")
        if system_prompt and task_text:
            return f"{system_prompt}\n\nTask:\n{task_text}"
        if system_prompt:
            return system_prompt
        return task_text

    def _build_args(self, prompt: str, request: ExecutionRequest) -> list[str]:
        return self.args_template[:]

    def _strip_ansi(self, text: str) -> str:
        return _ANSI_RE.sub("", text)

    def _process_line(self, text: str, stream: str) -> str | None:
        """Hook for providers to transform or drop captured lines.

        Return None to exclude the line from output/console entirely.
        """
        cleaned = self._strip_ansi(text)
        return cleaned if cleaned else None

    def _begin_execution(self, request: ExecutionRequest) -> None:
        """Provider hook: reset any per-execution state before spawning."""

    def _validate_output(
        self, stdout_lines: list[str], stderr_lines: list[str],
        request: ExecutionRequest,
    ) -> tuple[bool, str | None]:
        """Decide whether the captured output counts as a real response.

        Returns (ok, reason). Default: non-empty stdout required.
        """
        if not self.require_output:
            return True, None
        if stdout_lines:
            return True, None
        stderr_text = "\n".join(stderr_lines)
        reason = (
            "CLI exited 0 but produced no output "
            f"(silent failure, no task was performed). stderr: {stderr_text[:500]}"
        )
        return False, reason

    def _success_metadata(self) -> dict:
        """Provider hook: extra metadata to attach on success."""
        return {}

    async def _read_stream(self, stream, sink: list[str], tag: str,
                           log_sink=None) -> None:
        while True:
            line = await stream.readline()
            if not line:
                break
            text = self._process_line(
                line.decode(errors="replace").rstrip("\n"), tag
            )
            if text is None:
                continue
            sink.append(text)
            logger.info("[%s %s] %s", self.command, tag, text)
            if log_sink is not None:
                try:
                    await log_sink(text, tag)
                except Exception:
                    logger.exception("log_sink failed")

    def resolve_command(self) -> str:
        return self.command

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        prompt = self._build_prompt(request)
        args = self._build_args(prompt, request)
        cwd = request.working_directory
        timeout = request.timeout

        command = self.resolve_command() or self.command
        resolved = shutil.which(command) or command
        cmd = [resolved] + args
        # P2-2: 完整 prompt（含需求/系统提示词）不落日志，只打命令头（截断）。
        logger.info("Executing CLI: %s (cwd=%s, timeout=%s)",
                    " ".join(cmd)[:300], cwd, timeout)

        stdin_mode = (
            asyncio.subprocess.PIPE if self.prompt_via_stdin
            else asyncio.subprocess.DEVNULL
        )
        self._begin_execution(request)

        try:
            proc = await asyncio.create_subprocess_exec(
                resolved,
                *args,
                stdin=stdin_mode,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                start_new_session=True,
            )
        except FileNotFoundError:
            if cwd and not os.path.isdir(cwd):
                return ExecutionResult(
                    success=False,
                    error=f"Working directory does not exist: {cwd}",
                    output={"stderr": f"exec: chdir: {cwd}: No such file or directory"},
                )
            return ExecutionResult(
                success=False,
                error=f"Command not found: {resolved}. Is it installed?",
            )
        except Exception as exc:
            logger.exception("Failed to launch CLI")
            return ExecutionResult(success=False, error=str(exc))

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        log_sink = getattr(request, "log_sink", None)

        # P0-1: 多行 prompt 通过 stdin 传给 CLI（替代 DEVNULL），绕开 cmd.exe
        # 对命令行参数的换行截断。stdin 写入放在后台任务，避免管道缓冲死锁。
        prompt_task = None
        if self.prompt_via_stdin:
            stdin = getattr(proc, "stdin", None)

            async def _write_prompt() -> None:
                if stdin is None:
                    return
                try:
                    stdin.write(prompt.encode("utf-8"))
                    await stdin.drain()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    try:
                        stdin.close()
                    except Exception:
                        pass

            prompt_task = asyncio.ensure_future(_write_prompt())

        def _kill_process_group() -> None:
            # CLI grandchildren (dev servers etc.) keep stdout/stderr pipes
            # open; killing just the direct child leaves them alive and the
            # pipes never reach EOF. Kill the whole process group instead.
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                proc.kill()

        async def _flush_remaining(stream, sink: list[str], tag: str,
                                   log_sink=None) -> None:
            # After the main process exits, grandchildren may still hold the
            # pipe write end open, so EOF never arrives. Drain line-by-line
            # with a per-line cap so we can never block forever.
            while True:
                try:
                    line = await asyncio.wait_for(stream.readline(), timeout=0.5)
                except Exception:
                    return
                if not line:
                    return
                text = self._process_line(
                    line.decode(errors="replace").rstrip("\n"), tag
                )
                if not text:
                    continue
                sink.append(text)
                logger.info("[%s %s] %s", self.command, tag, text[:500])
                if log_sink is not None:
                    try:
                        await log_sink(text, tag)
                    except Exception:
                        logger.exception("log_sink failed")

        async def _drain() -> None:
            readers = [
                asyncio.ensure_future(
                    self._read_stream(proc.stdout, stdout_lines, "stdout", log_sink)
                ),
                asyncio.ensure_future(
                    self._read_stream(proc.stderr, stderr_lines, "stderr", log_sink)
                ),
            ]
            try:
                # The main process exiting is the completion signal. Do NOT
                # wait for pipe EOF: CLI grandchildren (dev servers etc.)
                # inherit the pipe FDs, so EOF never arrives even after the
                # main process exits.
                await proc.wait()
            finally:
                for r in readers:
                    r.cancel()
                await asyncio.gather(*readers, return_exceptions=True)
                await asyncio.gather(
                    _flush_remaining(proc.stdout, stdout_lines, "stdout", log_sink),
                    _flush_remaining(proc.stderr, stderr_lines, "stderr", log_sink),
                )
                if prompt_task is not None:
                    # 确保 stdin 已写入（CLI 可能快速退出导致写入任务还没跑）
                    try:
                        await asyncio.wait_for(prompt_task, timeout=10)
                    except Exception:
                        pass

        async def _cleanup() -> None:
            for stream in (proc.stdout, proc.stderr):
                if stream is None:
                    continue
                try:
                    await asyncio.wait_for(stream.read(), timeout=5.0)
                except Exception:
                    break
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except Exception:
                pass

        try:
            await asyncio.wait_for(_drain(), timeout=timeout)
        except asyncio.TimeoutError:
            _kill_process_group()
            await _cleanup()
            if prompt_task is not None:
                prompt_task.cancel()
            return ExecutionResult(
                success=False,
                error=f"CLI execution timed out after {timeout}s",
                output={
                    "stdout": "\n".join(stdout_lines),
                    "stderr": "\n".join(stderr_lines),
                },
            )
        except asyncio.CancelledError:
            _kill_process_group()
            await _cleanup()
            if prompt_task is not None:
                prompt_task.cancel()
            raise
        except Exception as exc:
            logger.exception("CLI execution failed")
            return ExecutionResult(success=False, error=str(exc))

        if proc.returncode != 0:
            stderr_text = "\n".join(stderr_lines)
            # P2-1: 非零退出时透传 stderr；stderr 为空时附带 stdout 尾部，
            # 避免上游错误（如 401 包装成 UnknownError）完全不可见。
            detail = stderr_text
            if not detail:
                detail = "\n".join(stdout_lines[-5:])
            return ExecutionResult(
                success=False,
                error=f"CLI exited with code {proc.returncode}: {detail}",
                output={
                    "stdout": "\n".join(stdout_lines),
                    "stderr": stderr_text,
                },
            )

        output_text = "\n".join(stdout_lines)
        # P0-2: 空输出不得伪装成成功
        ok, reason = self._validate_output(stdout_lines, stderr_lines, request)
        if not ok:
            return ExecutionResult(
                success=False,
                error=reason,
                output={
                    "stdout": output_text,
                    "stderr": "\n".join(stderr_lines),
                },
                metadata={"return_code": proc.returncode},
            )
        metadata = {"return_code": proc.returncode}
        extra = self._success_metadata()
        if extra:
            metadata.update(extra)
        return ExecutionResult(
            success=True,
            output={"output": output_text, "stdout": output_text},
            metadata=metadata,
        )
