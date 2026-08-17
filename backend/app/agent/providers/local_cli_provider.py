import json
import logging
from typing import Awaitable, Callable

from app.agent.executor.types import ExecutionRequest
from app.agent.executor.local_cli_executor import LocalCLIExecutor
from app.agent.providers.base import AgentProvider

logger = logging.getLogger(__name__)


class LocalCLIProvider(AgentProvider):
    """Runs the agent through a local CLI agent (OpenCode / Claude Code).

    Subprocess is launched with asyncio and stdout is streamed line by line.
    """

    name = "opencode_cli"

    def __init__(
        self,
        executor: LocalCLIExecutor,
        cli_provider: str = "opencode",
        name: str | None = None,
    ):
        self._executor = executor
        self._cli_provider = cli_provider
        if name:
            self.name = name

    async def execute(
        self,
        system_prompt: str,
        input_text: str,
        context: dict,
        config: dict,
        log_sink: Callable[[str, str], Awaitable[None]] | None = None,
    ) -> dict:
        prompt_parts = [input_text]
        if system_prompt:
            prompt_parts.insert(0, system_prompt)
        if context:
            prompt_parts.append(
                f"\nContext:\n{json.dumps(context, ensure_ascii=False, indent=2)}"
            )
        prompt = "\n\n".join(prompt_parts)

        request = ExecutionRequest(
            task={"prompt": prompt},
            context=context,
            config={
                "system_prompt": system_prompt,
                "provider": self.name,
                **config,
            },
            working_directory=config.get("working_directory"),
            timeout=int(config.get("timeout") or config.get("timeout_seconds") or 300),
            log_sink=log_sink,
        )
        try:
            result = await self._executor.execute(request)
        except Exception as exc:
            logger.exception("Local CLI provider execution failed")
            return {
                "status": "failed",
                "output": {},
                "provider": self.name,
                "error": str(exc),
            }

        if not result.success:
            return {
                "status": "failed",
                "output": result.output or {},
                "provider": self.name,
                "error": result.error or "Local CLI provider execution failed",
            }

        return {
            "status": "success",
            "output": result.output,
            "provider": self.name,
            "error": None,
        }
