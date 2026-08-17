import json
import logging

from app.agent.executor.types import ExecutionRequest
from app.agent.executor.llm_executor import LLMExecutor
from app.agent.providers.base import AgentProvider

logger = logging.getLogger(__name__)


class OpenAIProvider(AgentProvider):
    """Runs the agent through the OpenAI-compatible LLM API."""

    name = "openai"

    def __init__(self, executor: LLMExecutor):
        self._executor = executor

    async def execute(
        self,
        system_prompt: str,
        input_text: str,
        context: dict,
        config: dict,
    ) -> dict:
        request = ExecutionRequest(
            task={"prompt": input_text},
            context=context,
            config={
                "system_prompt": system_prompt,
                **config,
            },
        )
        try:
            result = await self._executor.execute(request)
        except Exception as exc:
            logger.exception("OpenAI provider execution failed")
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
                "error": result.error or "OpenAI provider execution failed",
            }

        return {
            "status": "success",
            "output": result.output,
            "provider": self.name,
            "error": None,
        }
