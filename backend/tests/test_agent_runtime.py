import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.agent.registry import AgentRegistry
from app.agent.llm_gateway import LLMGateway
from app.agent.prompt_template import PromptTemplate
from app.agent.comm_client import AgentCommClient
from app.agent.runtime import AgentExecutor, BUILTIN_AGENTS, register_builtin_agents
from app.models.agent import Agent
from app.models.message import AgentMessage


@pytest.fixture
def mock_db():
    session = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()

    def make_execute_result(**attrs):
        result = MagicMock()
        for k, v in attrs.items():
            setattr(result, k, v)
        session.execute = AsyncMock(return_value=result)
        return result

    session._make_execute_result = make_execute_result
    return session


class TestPromptTemplate:
    def test_render_simple(self):
        result = PromptTemplate.render("Hello {{ name }}", {"name": "World"})
        assert result == "Hello World"

    def test_render_multiple(self):
        result = PromptTemplate.render(
            "{{greeting}}, {{name}}!", {"greeting": "Hi", "name": "Alice"}
        )
        assert result == "Hi, Alice!"

    def test_render_missing_var_keeps_placeholder(self):
        result = PromptTemplate.render("Hello {{ name }}", {})
        assert result == "Hello {{ name }}"

    def test_render_empty_template(self):
        result = PromptTemplate.render("", {"x": "y"})
        assert result == ""

    def test_render_no_variables(self):
        result = PromptTemplate.render("Hello World", {})
        assert result == "Hello World"


class TestAgentRegistry:
    @pytest.mark.asyncio
    async def test_register_new_agent(self, mock_db):
        mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
        registry = AgentRegistry(mock_db)
        agent = await registry.register("test_agent", "Test", "A test agent", {"key": "val"})
        assert mock_db.add.called
        assert isinstance(agent, Agent)
        assert agent.id == "test_agent"

    @pytest.mark.asyncio
    async def test_get_agent_found(self, mock_db):
        agent = Agent(id="agent1", name="Agent1", description="Desc", definition={}, status="active")
        mock_db._make_execute_result(scalar_one_or_none=MagicMock(return_value=agent))
        registry = AgentRegistry(mock_db)
        result = await registry.get("agent1")
        assert result is not None
        assert result["id"] == "agent1"
        assert result["name"] == "Agent1"

    @pytest.mark.asyncio
    async def test_get_agent_not_found(self, mock_db):
        mock_db._make_execute_result(scalar_one_or_none=MagicMock(return_value=None))
        registry = AgentRegistry(mock_db)
        result = await registry.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_agents(self, mock_db):
        agents = [
            Agent(id="a1", name="A1", description="D1", definition={}, status="active"),
            Agent(id="a2", name="A2", description="D2", definition={}, status="active"),
        ]
        scalars_mock = MagicMock()
        scalars_mock.all = MagicMock(return_value=agents)
        mock_db._make_execute_result(scalars=MagicMock(return_value=scalars_mock))
        registry = AgentRegistry(mock_db)
        result = await registry.list_agents()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_agents_filtered_by_status(self, mock_db):
        mock_db._make_execute_result(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
        registry = AgentRegistry(mock_db)
        result = await registry.list_agents(status="inactive")
        assert result == []

    @pytest.mark.asyncio
    async def test_delete_agent(self, mock_db):
        registry = AgentRegistry(mock_db)
        await registry.delete("agent1")
        assert mock_db.execute.called


class TestBuildinAgents:
    def test_builtin_agents_defined(self):
        assert "pm_agent" in BUILTIN_AGENTS
        assert "architect_agent" in BUILTIN_AGENTS
        assert "developer_agent" in BUILTIN_AGENTS
        assert "qa_agent" in BUILTIN_AGENTS
        assert "devops_agent" in BUILTIN_AGENTS

    def test_builtin_agents_have_required_fields(self):
        for agent_id, spec in BUILTIN_AGENTS.items():
            assert "name" in spec
            assert "description" in spec
            assert "system_prompt" in spec
            assert len(spec["system_prompt"]) > 0

    @pytest.mark.asyncio
    async def test_register_builtin_agents(self, mock_db):
        mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
        registry = AgentRegistry(mock_db)
        await register_builtin_agents(registry)
        assert mock_db.add.call_count >= 5


class TestLLMGateway:
    @pytest.fixture
    def gateway(self):
        return LLMGateway()

    @pytest.mark.asyncio
    async def test_chat_with_invalid_provider(self, gateway):
        with pytest.raises(ValueError, match="Unsupported LLM provider"):
            await gateway.chat({"provider": "unsupported"}, [{"role": "user", "content": "hi"}])

    @pytest.mark.asyncio
    async def test_chat_retries_on_429(self, gateway):
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "retried successfully"
        mock_message.tool_calls = None
        mock_choice.message = mock_message
        mock_response.choices = [mock_choice]
        mock_response.usage = MagicMock(prompt_tokens=1, completion_tokens=1)

        from openai import APIStatusError

        error_429 = APIStatusError("Too Many Requests", response=MagicMock(status_code=429), body={"error": "rate limit"})

        mock_client.chat.completions.create = AsyncMock(side_effect=[error_429, error_429, mock_response])

        with patch.object(gateway, "_get_client", return_value=mock_client):
            result = await gateway.chat(
                {"provider": "openai", "model": "gpt-4o-mini", "api_key": "sk-test-not-placeholder"},
                [{"role": "user", "content": "hi"}],
            )
            assert result["content"] == "retried successfully"

    def test_parse_response_with_tool_calls(self, gateway):
        mock_response = MagicMock()
        mock_choice = MagicMock()
        mock_message = MagicMock()
        mock_tc = MagicMock()
        mock_tc.id = "call_123"
        mock_tc.function.name = "test_tool"
        mock_tc.function.arguments = '{"key": "value"}'

        mock_message.content = "Using tool"
        mock_message.tool_calls = [mock_tc]
        mock_choice.message = mock_message
        mock_response.choices = [mock_choice]
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 20

        result = gateway._parse_response(mock_response)
        assert result["content"] == "Using tool"
        assert len(result["tool_calls"]) == 1
        assert result["tool_calls"][0]["id"] == "call_123"
        assert result["usage"]["prompt_tokens"] == 10


class TestAgentCommClient:
    @pytest.fixture
    def comm_client(self, mock_db):
        return AgentCommClient(
            agent_id="test_agent",
            execution_id=uuid.uuid4(),
            db_session=mock_db,
        )

    @pytest.mark.asyncio
    async def test_send(self, comm_client, mock_db):
        await comm_client.send("target", "test.subject", {"data": 1})
        assert mock_db.add.called
        added = mock_db.add.call_args[0][0]
        assert isinstance(added, AgentMessage)
        assert added.subject == "test.subject"
        assert added.sender_id == "test_agent"
        assert added.target_id == "target"

    @pytest.mark.asyncio
    async def test_broadcast(self, comm_client, mock_db):
        await comm_client.broadcast("broadcast.subject", {"data": 2})
        added = mock_db.add.call_args[0][0]
        assert added.target_id == "*"
        assert added.message_type == "broadcast"

    @pytest.mark.asyncio
    async def test_request_timeout(self, comm_client, mock_db):
        mock_db._make_execute_result(scalar_one_or_none=MagicMock(return_value=None))
        with pytest.raises(TimeoutError):
            await comm_client.request("target", "req.subject", {"q": 1}, timeout=1)

    def test_on_subscribe(self, comm_client):
        handler = MagicMock()
        comm_client.on("my.subject", handler)
        assert len(comm_client._handlers["my.subject"]) == 1
        assert comm_client._handlers["my.subject"][0] == handler

    def test_on_wildcard(self, comm_client):
        handler = MagicMock()
        comm_client.on("*", handler)
        assert len(comm_client._handlers["*"]) == 1

    def test_stop(self, comm_client):
        assert comm_client._running is False
        comm_client.stop()
        assert comm_client._running is False

    @pytest.mark.asyncio
    async def test_reply(self, comm_client, mock_db):
        corr_id = uuid.uuid4()
        await comm_client.reply("requester", corr_id, {"result": "done"})
        added = mock_db.add.call_args[0][0]
        assert added.message_type == "response"
        assert added.correlation_id == corr_id


class TestAgentExecutor:
    @pytest.fixture
    def registry(self, mock_db):
        return AgentRegistry(mock_db)

    @pytest.fixture
    def llm_gateway(self):
        return LLMGateway()

    @pytest.fixture
    def tool_registry(self):
        tools = MagicMock()
        tools.list = MagicMock(return_value=[])
        tools.execute = AsyncMock(return_value={"result": "tool_output"})
        return tools

    @pytest.mark.asyncio
    async def test_execute_agent_not_found(self, registry, llm_gateway, tool_registry, mock_db):
        mock_db._make_execute_result(scalar_one_or_none=MagicMock(return_value=None))
        executor = AgentExecutor(registry, llm_gateway, tool_registry)
        result = await executor.execute("nonexistent", {"input": "test"}, {})
        assert "error" in result
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_success(self, registry, llm_gateway, tool_registry, mock_db):
        agent = Agent(
            id="pm_agent",
            name="PM",
            description="PM agent",
            definition={
                "system_prompt": "You are a {{ role }}",
                "model_config": {"provider": "openai", "model": "gpt-4o-mini"},
            },
            status="active",
        )
        mock_db._make_execute_result(scalar_one_or_none=MagicMock(return_value=agent))

        mock_response = {
            "content": "Here is the PRD",
            "tool_calls": [],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        }

        with patch.object(llm_gateway, "chat", AsyncMock(return_value=mock_response)):
            executor = AgentExecutor(registry, llm_gateway, tool_registry)
            result = await executor.execute(
                "pm_agent",
                {"requirement": "Build a login system"},
                {"role": "product manager"},
            )
            assert result["output"] == "Here is the PRD"
            assert result["usage"]["completion_tokens"] == 20

    @pytest.mark.asyncio
    async def test_execute_with_tool_calls(self, registry, llm_gateway, tool_registry, mock_db):
        agent = Agent(
            id="dev_agent",
            name="Developer",
            description="Dev agent",
            definition={
                "system_prompt": "Write code",
                "model_config": {"provider": "openai", "model": "gpt-4o-mini"},
            },
            status="active",
        )
        mock_db._make_execute_result(scalar_one_or_none=MagicMock(return_value=agent))

        first_response = {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "file_write", "arguments": '{"path": "/tmp/test.py", "content": "print(1)"}'},
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 5},
        }
        second_response = {
            "content": "Code written successfully",
            "tool_calls": [],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

        mock_chat = AsyncMock(side_effect=[first_response, second_response])
        with patch.object(llm_gateway, "chat", mock_chat):
            executor = AgentExecutor(registry, llm_gateway, tool_registry)
            result = await executor.execute(
                "dev_agent", {"task": "Write hello.py"}, {}
            )
            assert result["output"] == "Code written successfully"
            assert len(result["tool_calls"]) == 1
            assert result["tool_calls"][0]["tool_name"] == "file_write"
            assert mock_chat.call_count == 2
