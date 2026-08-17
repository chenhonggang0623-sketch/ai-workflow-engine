from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.executor.base import BaseExecutor
from app.agent.executor.types import ExecutorType, ExecutionRequest, ExecutionResult
from app.agent.executor.router import ExecutorRouter
from app.agent.executor.llm_executor import LLMExecutor
from app.agent.executor.local_cli_executor import LocalCLIExecutor
from app.agent.executor.local_model_executor import LocalModelExecutor
from app.agent.executor.human_executor import HumanExecutor
from app.agent.executor.mcp_executor import MCPExecutor
from app.engine.types import NodeConfig, NodeType, NodeDefinition, NodeStatus
from app.engine.node_runner import NodeRunner


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_llm_gateway():
    gw = AsyncMock()
    gw.chat = AsyncMock(return_value={
        "content": "llm response",
        "tool_calls": [],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    })
    return gw


@pytest.fixture
def mock_tool_registry():
    tr = MagicMock()
    tr.list = MagicMock(return_value=[])
    tr.execute = AsyncMock(return_value={"result": "ok"})
    return tr


@pytest.fixture
def mock_bridge():
    bridge = AsyncMock()
    bridge.call_tool = AsyncMock(return_value={"result": "mcp result"})
    return bridge


@pytest.fixture
def llm_executor(mock_llm_gateway, mock_tool_registry):
    return LLMExecutor(
        llm_gateway=mock_llm_gateway,
        tool_registry=mock_tool_registry,
        agent_registry=None,
    )


@pytest.fixture
def router(llm_executor, mock_llm_gateway, mock_tool_registry):
    return ExecutorRouter(
        llm_executor=llm_executor,
        local_cli_executor=LocalCLIExecutor(),
        local_model_executor=LocalModelExecutor(
            llm_gateway=mock_llm_gateway,
            tool_registry=mock_tool_registry,
        ),
        human_executor=HumanExecutor(),
        mcp_executor=MCPExecutor(bridge=None),
    )


# ---------------------------------------------------------------------------
# Router type-to-executor mapping
# ---------------------------------------------------------------------------

class TestExecutorRouter:

    def test_get_llm_api_executor(self, router):
        executor = router.get_executor(ExecutorType.LLM_API)
        assert isinstance(executor, LLMExecutor)

    def test_get_local_cli_executor(self, router):
        executor = router.get_executor(ExecutorType.LOCAL_CLI)
        assert isinstance(executor, LocalCLIExecutor)

    def test_get_local_model_executor(self, router):
        executor = router.get_executor(ExecutorType.LOCAL_MODEL)
        assert isinstance(executor, LocalModelExecutor)

    def test_get_human_executor(self, router):
        executor = router.get_executor(ExecutorType.HUMAN)
        assert isinstance(executor, HumanExecutor)

    def test_get_mcp_executor(self, router):
        executor = router.get_executor(ExecutorType.MCP)
        assert isinstance(executor, MCPExecutor)

    def test_get_by_string(self, router):
        executor = router.get_executor("llm_api")
        assert isinstance(executor, LLMExecutor)

    def test_get_unknown_type(self, router):
        executor = router.get_executor("nonexistent")
        assert executor is None


# ---------------------------------------------------------------------------
# Router.execute()
# ---------------------------------------------------------------------------

class TestRouterExecute:

    @pytest.mark.asyncio
    async def test_llm_api_execute(self, router):
        request = ExecutionRequest(task={"prompt": "hello"}, config={})
        result = await router.execute(ExecutorType.LLM_API, request)
        assert result.success is True
        assert "output" in result.output

    @pytest.mark.asyncio
    async def test_mcp_no_bridge_returns_error(self, router):
        request = ExecutionRequest(
            task={},
            config={"tool_id": "some_tool"},
        )
        result = await router.execute(ExecutorType.MCP, request)
        assert result.success is False
        assert "MCPBridge not configured" in (result.error or "")

    @pytest.mark.asyncio
    async def test_human_returns_awaiting(self, router):
        request = ExecutionRequest(task={"prompt": "hello"})
        result = await router.execute(ExecutorType.HUMAN, request)
        assert result.success is True
        assert result.output.get("status") == "awaiting_input"

    @pytest.mark.asyncio
    async def test_local_model_execute(self, router, mock_llm_gateway):
        request = ExecutionRequest(
            task={"prompt": "hello"},
            config={
                "executor_config": {
                    "model": "qwen2.5-coder:7b",
                    "base_url": "http://localhost:11434/v1",
                },
            },
        )
        result = await router.execute(ExecutorType.LOCAL_MODEL, request)
        assert result.success is True
        _, kwargs = mock_llm_gateway.chat.call_args
        assert kwargs["model_config"]["model"] == "qwen2.5-coder:7b"

    @pytest.mark.asyncio
    async def test_unknown_type_returns_error(self, router):
        request = ExecutionRequest(task={})
        result = await router.execute("bogus", request)
        assert result.success is False
        assert "No executor available" in (result.error or "")


# ---------------------------------------------------------------------------
# LLMExecutor
# ---------------------------------------------------------------------------

class TestLLMExecutor:

    @pytest.mark.asyncio
    async def test_execute_success(self, llm_executor, mock_llm_gateway):
        request = ExecutionRequest(
            task={"prompt": "write a poem"},
            config={"system_prompt": "You are a poet"},
        )
        result = await llm_executor.execute(request)
        assert result.success is True
        assert result.output["output"] == "llm response"
        mock_llm_gateway.chat.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_with_model_config(self, llm_executor, mock_llm_gateway):
        request = ExecutionRequest(
            task={"prompt": "hello"},
            config={
                "model_params": {
                    "model": "gpt-4",
                    "temperature": 0.5,
                    "provider": "openai",
                },
            },
        )
        result = await llm_executor.execute(request)
        assert result.success is True
        _, kwargs = mock_llm_gateway.chat.call_args
        assert kwargs["model_config"]["model"] == "gpt-4"


# ---------------------------------------------------------------------------
# MCPExecutor
# ---------------------------------------------------------------------------

class TestMCPExecutor:

    @pytest.mark.asyncio
    async def test_execute_success(self, mock_bridge):
        executor = MCPExecutor(bridge=mock_bridge)
        request = ExecutionRequest(
            task={"command": "ls"},
            config={"tool_id": "shell", "server_name": "default"},
        )
        result = await executor.execute(request)
        assert result.success is True
        assert result.output["result"] == {"result": "mcp result"}
        mock_bridge.call_tool.assert_called_once_with(
            server_name="default", tool_name="shell", arguments={"command": "ls"},
        )

    @pytest.mark.asyncio
    async def test_execute_no_tool_name(self):
        executor = MCPExecutor(bridge=MagicMock())
        request = ExecutionRequest(task={}, config={})
        result = await executor.execute(request)
        assert result.success is False
        assert "tool_id" in (result.error or "")

    @pytest.mark.asyncio
    async def test_execute_no_bridge(self):
        executor = MCPExecutor(bridge=None)
        request = ExecutionRequest(
            task={}, config={"tool_id": "shell"},
        )
        result = await executor.execute(request)
        assert result.success is False
        assert "MCPBridge not configured" in (result.error or "")


# ---------------------------------------------------------------------------
# HumanExecutor
# ---------------------------------------------------------------------------

class TestHumanExecutor:

    @pytest.mark.asyncio
    async def test_execute_returns_awaiting(self):
        executor = HumanExecutor()
        request = ExecutionRequest(task={"prompt": "approve this"})
        result = await executor.execute(request)
        assert result.success is True
        assert result.output["status"] == "awaiting_input"
        assert result.metadata.get("requires_input") is True

    @pytest.mark.asyncio
    async def test_execute_with_prompt_message(self):
        executor = HumanExecutor()
        request = ExecutionRequest(
            task={"data": "test"},
            config={"executor_config": {"prompt_message": "Please check this"}},
        )
        result = await executor.execute(request)
        assert result.output["prompt_message"] == "Please check this"


# ---------------------------------------------------------------------------
# LocalCLIExecutor
# ---------------------------------------------------------------------------

class TestLocalCLIExecutor:

    @pytest.mark.asyncio
    async def test_unknown_provider(self):
        executor = LocalCLIExecutor()
        request = ExecutionRequest(
            task={"prompt": "hello"},
            config={"agent_provider": "unknown_cli"},
        )
        result = await executor.execute(request)
        assert result.success is False
        assert "Unknown CLI provider" in (result.error or "")

    @pytest.mark.asyncio
    async def test_opencode_provider_missing_binary(self, monkeypatch):
        from app.agent.executor.providers.opencode import OpenCodeExecutor

        monkeypatch.setattr("app.core.config.settings.opencode_path", "/nonexistent/opencode")
        executor = LocalCLIExecutor()
        request = ExecutionRequest(
            task={"prompt": "hello"},
            config={"agent_provider": "opencode"},
            timeout=5,
        )
        result = await executor.execute(request)
        assert result.success is False
        assert "Command not found" in (result.error or "")


# ---------------------------------------------------------------------------
# NodeRunner with ExecutorRouter
# ---------------------------------------------------------------------------

class TestNodeRunnerWithRouter:

    @pytest.fixture
    def mock_tools(self):
        tools = MagicMock()
        tools.execute = AsyncMock(return_value={"result": "mock tool result"})
        return tools

    @pytest.fixture
    def mock_agent(self):
        agent = AsyncMock()
        agent.execute = AsyncMock(return_value={
            "output": "mock agent result",
            "tool_calls": [],
            "usage": {},
        })
        return agent

    @pytest.fixture
    def mock_router(self):
        router = MagicMock(spec=ExecutorRouter)
        router.execute = AsyncMock(return_value=ExecutionResult(
            success=True,
            output={"output": "router result"},
            metadata={"usage": {}},
        ))
        return router

    @pytest.mark.asyncio
    async def test_agent_node_uses_router(self, mock_router, mock_tools):
        runner = NodeRunner(
            agent_executor=None,
            tool_registry=mock_tools,
            executor_router=mock_router,
        )
        node = NodeDefinition(
            id="n1",
            type=NodeType.AGENT,
            label="Test",
            config=NodeConfig(
                executor_type="llm_api",
                system_prompt="You are a helper",
            ),
        )
        result = await runner.handle_node(node, {})
        assert result.status == NodeStatus.SUCCEEDED
        assert result.output["output"] == "router result"
        mock_router.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_agent_node_router_config(self, mock_router, mock_tools):
        runner = NodeRunner(
            agent_executor=None,
            tool_registry=mock_tools,
            executor_router=mock_router,
        )
        node = NodeDefinition(
            id="n1",
            type=NodeType.AGENT,
            label="CLI Agent",
            config=NodeConfig(
                executor_type="local_cli",
                agent_provider="opencode",
                working_directory="/workspace/project",
                executor_config={"provider": "opencode", "model": "claude-sonnet-4-20250514"},
            ),
        )
        await runner.handle_node(node, {})
        call_args = mock_router.execute.call_args[0]
        executor_type, req = call_args[0], call_args[1]
        assert executor_type == "local_cli"
        assert req.config.get("executor_type") == "local_cli"
        assert req.config.get("agent_provider") == "opencode"
        assert req.config.get("working_directory") == "/workspace/project"
        assert req.config.get("executor_config", {}).get("provider") == "opencode"

    @pytest.mark.asyncio
    async def test_agent_node_router_failure(self, mock_router, mock_tools):
        mock_router.execute = AsyncMock(return_value=ExecutionResult(
            success=False, error="LLM API key not configured",
        ))
        runner = NodeRunner(
            agent_executor=None,
            tool_registry=mock_tools,
            executor_router=mock_router,
        )
        node = NodeDefinition(
            id="n1",
            type=NodeType.AGENT,
            label="Test",
            config=NodeConfig(executor_type="llm_api"),
        )
        result = await runner.handle_node(node, {})
        assert result.status == NodeStatus.FAILED
        assert "LLM API key not configured" in (result.error or "")

    @pytest.mark.asyncio
    async def test_fallback_to_legacy_agent_when_no_router(self, mock_agent, mock_tools):
        runner = NodeRunner(
            agent_executor=mock_agent,
            tool_registry=mock_tools,
            executor_router=None,
        )
        node = NodeDefinition(
            id="n1",
            type=NodeType.AGENT,
            label="Test",
            config=NodeConfig(),
        )
        result = await runner.handle_node(node, {})
        assert result.status == NodeStatus.SUCCEEDED
        assert result.output["output"] == "mock agent result"
        mock_agent.execute.assert_called_once()
