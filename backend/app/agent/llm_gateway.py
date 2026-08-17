import asyncio
import logging

from openai import AsyncOpenAI, APIStatusError, APIError

from app.core.app_config import config_store
from app.core.config import settings

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = {"openai"}


class LLMGateway:
    def __init__(self):
        self._clients: dict[str, AsyncOpenAI] = {}

    def _get_client(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> AsyncOpenAI:
        base_url = base_url or config_store.get("openai_base_url", settings.openai_base_url)
        api_key = api_key or config_store.get("openai_api_key", settings.openai_api_key)
        key = f"{base_url}::{api_key}"
        if key not in self._clients:
            self._clients[key] = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
            )
        return self._clients[key]

    async def chat(
        self,
        model_config: dict,
        messages: list[dict],
        tools: list[dict] | None = None,
        stream: bool = False,
    ) -> dict:
        provider = model_config.get("provider", settings.default_llm_provider)
        model = model_config.get("model", settings.default_llm_model)
        temperature = model_config.get("temperature", 0.7)
        max_tokens = model_config.get("max_tokens", 4096)

        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"Unsupported LLM provider: {provider}")

        base_url = model_config.get("base_url")
        api_key = model_config.get("api_key")
        client = self._get_client(base_url, api_key)

        kwargs = dict(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if tools:
            kwargs["tools"] = tools

        last_error = None
        for attempt in range(3):
            try:
                if stream:
                    return await self._handle_stream(client, **kwargs)

                response = await client.chat.completions.create(**kwargs)
                return self._parse_response(response)

            except APIStatusError as e:
                last_error = e
                status = e.response.status_code
                if status in (429, 500, 502, 503):
                    wait = 2 ** attempt
                    logger.warning(
                        "LLM API error (attempt %d/3): %s. Retrying in %ds...",
                        attempt + 1, e, wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                raise
            except APIError as e:
                last_error = e
                logger.warning("LLM API error (attempt %d/3): %s", attempt + 1, e)
                await asyncio.sleep(2 ** attempt)

        raise last_error or RuntimeError("LLM chat failed after 3 retries")

    async def chat_stream(
        self,
        model_config: dict,
        messages: list[dict],
        tools: list[dict] | None = None,
    ):
        provider = model_config.get("provider", settings.default_llm_provider)
        model = model_config.get("model", settings.default_llm_model)
        temperature = model_config.get("temperature", 0.7)
        max_tokens = model_config.get("max_tokens", 4096)

        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"Unsupported LLM provider: {provider}")

        base_url = model_config.get("base_url")
        client = self._get_client(base_url)

        kwargs = dict(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        if tools:
            kwargs["tools"] = tools

        response = await client.chat.completions.create(**kwargs)

        partial_tool_calls: dict[int, dict] = {}
        async for chunk in response:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            if delta.content:
                yield {"type": "text", "content": delta.content}

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in partial_tool_calls:
                        partial_tool_calls[idx] = {
                            "id": tc.id or "",
                            "function": {"name": "", "arguments": ""},
                        }
                    if tc.id:
                        partial_tool_calls[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            partial_tool_calls[idx]["function"]["name"] = tc.function.name
                        if tc.function.arguments:
                            partial_tool_calls[idx]["function"]["arguments"] += tc.function.arguments

        for tc in partial_tool_calls.values():
            yield {"type": "tool_call", "content": tc}

    def _parse_response(self, response) -> dict:
        choice = response.choices[0]
        message = choice.message

        result = {
            "content": message.content or "",
            "tool_calls": [],
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            },
        }

        if message.tool_calls:
            for tc in message.tool_calls:
                result["tool_calls"].append({
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                })

        return result

    async def _handle_stream(self, client, **kwargs) -> dict:
        kwargs["stream"] = True
        response = await client.chat.completions.create(**kwargs)

        content_parts: list[str] = []
        async for chunk in response:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                content_parts.append(delta.content)

        return {
            "content": "".join(content_parts),
            "tool_calls": [],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }
