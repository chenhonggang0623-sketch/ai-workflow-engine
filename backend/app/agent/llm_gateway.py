import asyncio
import logging
import shutil

from openai import AsyncOpenAI, APIStatusError, APIError

from app.core.app_config import config_store
from app.core.config import settings

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = {"openai", "opencode_cli", "claude_cli", "codex_cli"}

# provider -> (config path key, CLI invocation args, model arg?)
CLI_PROVIDERS: dict[str, tuple[str, list[str], bool]] = {
    "opencode_cli": ("opencode_path", ["run"], False),
    "claude_cli": ("claude_code_path", ["-p", "--output-format", "text"], False),
    "codex_cli": ("codex_path", ["exec"], False),
}

CLI_TIMEOUT_SECONDS = 300


def _is_placeholder(key: str) -> bool:
    return not key or key in ("sk-your-key-here", "sk-your-api-key", "your-api-key")


def _resolve_cli_command(provider: str) -> str | None:
    cfg_key = CLI_PROVIDERS[provider][0]
    path = config_store.get(cfg_key, getattr(settings, cfg_key))
    if not path:
        return None
    resolved = shutil.which(path)
    if resolved is None:
        logger.warning("CLI provider %s: command '%s' not found on PATH", provider, path)
        return None
    return resolved


def available_cli_providers() -> list[str]:
    return [p for p in CLI_PROVIDERS if _resolve_cli_command(p)]


def default_model_config() -> dict:
    """默认模型配置：DB 覆盖（config_store）优先于 .env 默认值。"""
    return {
        "model": config_store.get("default_llm_model", settings.default_llm_model),
        "provider": config_store.get("default_llm_provider", settings.default_llm_provider),
        "base_url": config_store.get("openai_base_url", settings.openai_base_url),
        "api_key": config_store.get("openai_api_key", settings.openai_api_key),
    }


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

        if provider in CLI_PROVIDERS:
            return await self._chat_via_cli(provider, messages)

        if provider not in SUPPORTED_PROVIDERS:
            raise ValueError(f"Unsupported LLM provider: {provider}")

        api_key = model_config.get("api_key")
        if provider == "openai" and _is_placeholder(api_key):
            api_key = config_store.get("openai_api_key", settings.openai_api_key)
        if provider == "openai" and _is_placeholder(api_key):
            # 无 API key → 自动降级到本地 CLI 通道，保证 provider 至少可用一个
            cli = available_cli_providers()
            if not cli:
                raise RuntimeError(
                    "No usable LLM provider: openai API key is missing and no "
                    "local CLI (opencode/claude/codex) is available"
                )
            logger.warning(
                "openai API key missing; falling back to local CLI provider: %s", cli[0]
            )
            return await self._chat_via_cli(cli[0], messages)

        base_url = model_config.get("base_url")
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

    async def _chat_via_cli(self, provider: str, messages: list[dict]) -> dict:
        command = _resolve_cli_command(provider)
        if command is None:
            raise RuntimeError(f"CLI provider {provider} is not available")
        args = CLI_PROVIDERS[provider][1]

        prompt_parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content") or ""
            if role == "system":
                prompt_parts.append(f"System instructions:\n{content}")
            else:
                prompt_parts.append(content)
        prompt = "\n\n".join(prompt_parts)

        proc = await asyncio.create_subprocess_exec(
            command, *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(prompt.encode("utf-8")), CLI_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(f"CLI provider {provider} timed out after {CLI_TIMEOUT_SECONDS}s")

        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            detail = stderr_text or stdout_text[-500:]
            raise RuntimeError(
                f"CLI provider {provider} exited with code {proc.returncode}: {detail[:500]}"
            )
        if not stdout_text:
            raise RuntimeError(f"CLI provider {provider} returned empty output")

        return {
            "content": stdout_text,
            "tool_calls": [],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            "provider": provider,
        }

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
