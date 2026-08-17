import asyncio
import json
import logging
import os
import shutil
import signal

from app.agent.executor.base import BaseExecutor
from app.agent.executor.types import ExecutionRequest, ExecutionResult

logger = logging.getLogger(__name__)


class BaseCLIExecutor(BaseExecutor):
    command: str = ""
    args_template: list[str] = []

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

    async def _read_stream(self, stream, sink: list[str], tag: str,
                           log_sink=None) -> None:
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode(errors="replace").rstrip("\n")
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
        logger.info("Executing CLI: %s (cwd=%s, timeout=%s)", " ".join(cmd), cwd, timeout)

        try:
            proc = await asyncio.create_subprocess_exec(
                resolved,
                *args,
                stdin=asyncio.subprocess.DEVNULL,
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
                text = line.decode(errors="replace").rstrip("\n")
                if text:
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
            raise
        except Exception as exc:
            logger.exception("CLI execution failed")
            return ExecutionResult(success=False, error=str(exc))

        if proc.returncode != 0:
            return ExecutionResult(
                success=False,
                error=f"CLI exited with code {proc.returncode}: {'\n'.join(stderr_lines)}",
                output={
                    "stdout": "\n".join(stdout_lines),
                    "stderr": "\n".join(stderr_lines),
                },
            )

        output_text = "\n".join(stdout_lines)
        return ExecutionResult(
            success=True,
            output={"output": output_text, "stdout": output_text},
            metadata={"return_code": proc.returncode},
        )
