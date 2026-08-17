from typing import Any, Awaitable, Callable


class AgentProvider:
    """Unified interface for all agent execution backends.

    Implementations turn a (system_prompt, input_text, context, config)
    tuple into a provider result dict:

        {
            "status": "success" | "failed",
            "output": <provider output, usually str or dict>,
            "provider": "<provider name>",
            "error": <error message when failed>,
        }
    """

    name: str = "base"

    async def execute(
        self,
        system_prompt: str,
        input_text: str,
        context: dict[str, Any],
        config: dict[str, Any],
        log_sink: Callable[[str, str], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError
