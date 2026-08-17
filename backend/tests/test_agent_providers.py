import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.executor.local_cli_executor import LocalCLIExecutor
from app.agent.executor.llm_executor import LLMExecutor
from app.agent.executor.router import ExecutorRouter
from app.agent.executor.types import ExecutionRequest, ExecutionResult
from app.agent.providers import (
    AgentProviderRegistry,
    LocalCLIProvider,
    OpenAIProvider,
    SUPPORTED_PROVIDERS,
)
from app.agent.providers.base import AgentProvider
from app.engine.types import NodeConfig


class StubProvider(AgentProvider):
    name = "stub"

    def __init__(self, result: dict):
        self._result = result
        self.calls = []

    async def execute(self, system_prompt, input_text, context, config):
        self.calls.append((system_prompt, input_text, context, config))
        return dict(self._result)


# ---------------------------------------------------------------------------
# AgentProvider interface
# ---------------------------------------------------------------------------

class TestAgentProviderBase:
    def test_base_raises_not_implemented(self):
        provider = AgentProvider()
        with pytest.raises(NotImplementedError):
            asyncio.run(provider.execute("s", "i", {}, {}))

    def test_supported_provider_names(self):
        assert SUPPORTED_PROVIDERS == [
            "openai",
            "opencode_cli",
            "claude_cli",
            "codex_cli",
            "local_model",
            "ensemble",
        ]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class TestAgentProviderRegistry:
    def test_register_and_get(self):
        registry = AgentProviderRegistry(default_provider="stub")
        provider = StubProvider({"status": "success", "output": "ok", "provider": "stub"})
        registry.register(provider)
        assert registry.get("stub") is provider
        assert registry.get_default() is provider

    def test_get_unknown_returns_none(self):
        registry = AgentProviderRegistry()
        assert registry.get("nope") is None

    def test_get_or_default(self):
        registry = AgentProviderRegistry(default_provider="stub")
        stub = StubProvider({})
        registry.register(stub)
        assert registry.get_or_default("missing") is stub

    def test_names(self):
        registry = AgentProviderRegistry()
        a = StubProvider({})
        a.name = "a"
        b = StubProvider({})
        b.name = "b"
        registry.register(a)
        registry.register(b)
        assert set(registry.names()) == {"a", "b"}


# ---------------------------------------------------------------------------
# OpenAIProvider
# ---------------------------------------------------------------------------

class TestOpenAIProvider:
    @pytest.fixture
    def llm_executor(self):
        gw = AsyncMock()
        gw.chat = AsyncMock(return_value={
            "content": "analysis result",
            "tool_calls": [],
            "usage": {},
        })
        return LLMExecutor(llm_gateway=gw, tool_registry=MagicMock(), agent_registry=None)

    @pytest.mark.asyncio
    async def test_execute_success(self, llm_executor):
        provider = OpenAIProvider(llm_executor)
        result = await provider.execute(
            system_prompt="You are an analyst",
            input_text="analyze this",
            context={"requirement": "calculator"},
            config={"model_params": {"temperature": 0.3}},
        )
        assert result["status"] == "success"
        assert result["provider"] == "openai"
        assert result["output"]["output"] == "analysis result"

    @pytest.mark.asyncio
    async def test_execute_failure_propagates_error(self):
        gw = AsyncMock()
        gw.chat = AsyncMock(side_effect=Exception("no key"))
        llm_executor = LLMExecutor(llm_gateway=gw, tool_registry=None, agent_registry=None)
        provider = OpenAIProvider(llm_executor)
        result = await provider.execute("s", "i", {}, {})
        assert result["status"] == "failed"
        assert "no key" in result["error"]


# ---------------------------------------------------------------------------
# LocalCLIProvider
# ---------------------------------------------------------------------------

class TestLocalCLIProvider:
    @pytest.mark.asyncio
    async def test_execute_success(self):
        provider = LocalCLIProvider(LocalCLIExecutor(), cli_provider="opencode")
        result = await provider.execute(
            system_prompt="You are a frontend dev",
            input_text="build calculator.html",
            context={"analysis": "simple"},
            config={"working_directory": "/tmp", "timeout": 5},
        )
        assert result["provider"] == "opencode_cli"
        assert result["status"] in ("success", "failed")

    def test_prompt_includes_system_and_context(self, monkeypatch):
        captured = {}

        class FakeStream:
            def __init__(self, chunks):
                self._chunks = list(chunks)

            async def readline(self):
                return self._chunks.pop(0) if self._chunks else b""

        class FakeProc:
            returncode = 0

            def __init__(self, prompt: str):
                self.stdout = FakeStream([prompt.encode()])
                self.stderr = FakeStream([])

            async def wait(self):
                return 0

        async def fake_spawn(*args, **kwargs):
            captured["cmd"] = list(args)
            captured["kwargs"] = kwargs
            return FakeProc(args[-1])

        monkeypatch.setattr(
            "app.agent.executor.providers.base_cli.asyncio.create_subprocess_exec",
            fake_spawn,
        )

        executor = LocalCLIExecutor()
        provider = LocalCLIProvider(executor, cli_provider="opencode")

        async def run():
            return await provider.execute(
                system_prompt="SYSTEM PROMPT",
                input_text="DO THE TASK",
                context={"key": "value"},
                config={},
            )

        result = asyncio.run(run())
        assert result["status"] == "success"
        assert result["provider"] == "opencode_cli"
        assert captured["cmd"][0].endswith("opencode")
        assert captured["cmd"][1] == "run"
        prompt = captured["cmd"][2]
        assert "SYSTEM PROMPT" in prompt
        assert "DO THE TASK" in prompt
        assert "value" in prompt


# ---------------------------------------------------------------------------
# Router provider dispatch
# ---------------------------------------------------------------------------

class TestRouterProviderDispatch:
    @pytest.fixture
    def stub(self):
        return StubProvider({
            "status": "success",
            "output": {"output": "provider result"},
            "provider": "stub",
            "error": None,
        })

    @pytest.mark.asyncio
    async def test_provider_config_takes_precedence(self, stub):
        router = ExecutorRouter(provider_registry=AgentProviderRegistry(default_provider="stub"))
        router._provider_registry.register(stub)
        request = ExecutionRequest(
            task={"prompt": "hello"},
            config={"provider": "stub", "system_prompt": "You are X"},
        )
        result = await router.execute("llm_api", request)
        assert result.success is True
        assert result.output["output"] == "provider result"
        assert result.metadata["provider"] == "stub"
        system_prompt, input_text, _, _ = stub.calls[0]
        assert system_prompt == "You are X"
        assert input_text == "hello"

    @pytest.mark.asyncio
    async def test_provider_failure_returns_failed_result(self):
        stub = StubProvider({
            "status": "failed",
            "output": {},
            "provider": "stub",
            "error": "provider exploded",
        })
        registry = AgentProviderRegistry(default_provider="stub")
        registry.register(stub)
        router = ExecutorRouter(provider_registry=registry)
        request = ExecutionRequest(
            task={"prompt": "hello"},
            config={"provider": "stub"},
        )
        result = await router.execute("llm_api", request)
        assert result.success is False
        assert "provider exploded" in (result.error or "")

    @pytest.mark.asyncio
    async def test_unknown_provider_falls_back_to_executor_type(self):
        registry = AgentProviderRegistry()
        router = ExecutorRouter(
            llm_executor=LLMExecutor(
                llm_gateway=AsyncMock(chat=AsyncMock(return_value={
                    "content": "llm ok",
                    "tool_calls": [],
                    "usage": {},
                })),
                tool_registry=None,
                agent_registry=None,
            ),
            provider_registry=registry,
        )
        request = ExecutionRequest(
            task={"prompt": "hello"},
            config={"provider": "not_registered"},
        )
        result = await router.execute("llm_api", request)
        assert result.success is True
        assert result.output["output"] == "llm ok"

    def test_resolve_provider_name(self):
        router = ExecutorRouter()
        assert router.resolve_provider_name({"provider": "opencode_cli"}) == "opencode_cli"
        assert router.resolve_provider_name({"agent_provider": "openai"}) == "openai"
        assert router.resolve_provider_name({"executor_type": "local_cli"}) == "opencode_cli"
        assert router.resolve_provider_name({"executor_type": "llm_api"}) is None


# ---------------------------------------------------------------------------
# NodeConfig provider field + full pipeline
# ---------------------------------------------------------------------------

class TestNodeConfigProvider:
    def test_provider_field(self):
        config = NodeConfig(provider="opencode_cli", system_prompt="dev")
        dumped = config.model_dump()
        assert dumped["provider"] == "opencode_cli"
        assert dumped["executor_type"] == "llm_api"

    @pytest.mark.asyncio
    async def test_node_runner_dispatch_with_provider(self):
        stub = StubProvider({
            "status": "success",
            "output": {"output": "via provider"},
            "provider": "stub",
            "error": None,
        })
        registry = AgentProviderRegistry(default_provider="stub")
        registry.register(stub)
        router = ExecutorRouter(provider_registry=registry)

        from app.engine.types import NodeDefinition, NodeType, NodeStatus
        from app.engine.node_runner import NodeRunner

        runner = NodeRunner(agent_executor=None, tool_registry=None, executor_router=router)
        node = NodeDefinition(
            id="n1",
            type=NodeType.AGENT,
            label="Agent",
            config=NodeConfig(
                provider="stub",
                system_prompt="You are a dev",
                input_schema=None,
            ),
        )
        result = await runner.handle_node(node, {})
        assert result.status == NodeStatus.SUCCEEDED
        assert result.output["output"] == "via provider"
        assert result.output["_executor_metadata"]["provider"] == "stub"
