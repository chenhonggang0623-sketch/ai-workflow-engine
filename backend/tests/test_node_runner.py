from unittest.mock import AsyncMock, MagicMock

import pytest
from app.engine.node_runner import NodeRunner
from app.engine.types import (
    NodeDefinition, NodeConfig, NodeType, NodeStatus,
    InputMapping, OutputMapping, RetryConfig,
)


def _make_node(
    node_id: str = "n1",
    node_type: NodeType = NodeType.AGENT,
    label: str = "Test",
    config: NodeConfig | None = None,
    input_mapping: list[InputMapping] | None = None,
    output_mapping: list[OutputMapping] | None = None,
) -> NodeDefinition:
    return NodeDefinition(
        id=node_id,
        type=node_type,
        label=label,
        config=config or NodeConfig(),
        input_mapping=input_mapping or [],
        output_mapping=output_mapping or [],
    )


@pytest.fixture
def mock_agent():
    agent = AsyncMock()
    agent.execute = AsyncMock(return_value={
        "output": "mock agent result",
        "tool_calls": [],
        "usage": {},
    })
    return agent


@pytest.fixture
def mock_tools():
    tools = MagicMock()
    tools.execute = AsyncMock(return_value={"result": "mock tool result"})
    return tools


@pytest.fixture
def runner(mock_agent, mock_tools):
    return NodeRunner(agent_executor=mock_agent, tool_registry=mock_tools)


@pytest.mark.asyncio
async def test_agent_node_calls_executor(runner, mock_agent):
    node = _make_node(node_type=NodeType.AGENT)
    result = await runner.handle_node(node, {})
    assert result.status == NodeStatus.SUCCEEDED
    mock_agent.execute.assert_called_once()


@pytest.mark.asyncio
async def test_agent_node_passes_system_prompt(runner, mock_agent):
    node = _make_node(
        node_type=NodeType.AGENT,
        config=NodeConfig(system_prompt="You are a poet"),
    )
    await runner.handle_node(node, {})
    _, kwargs = mock_agent.execute.call_args
    assert kwargs["system_prompt"] == "You are a poet"


@pytest.mark.asyncio
async def test_tool_node_calls_tool_registry(runner, mock_tools):
    node = _make_node(
        node_type=NodeType.TOOL,
        config=NodeConfig(tool_id="shell"),
    )
    result = await runner.handle_node(node, {})
    assert result.status == NodeStatus.SUCCEEDED
    mock_tools.execute.assert_called_once()


@pytest.mark.asyncio
async def test_condition_node(runner):
    node = _make_node(
        node_type=NodeType.CONDITION,
        config=NodeConfig(expression="x > 5"),
    )
    result = await runner.handle_node(node, {"x": 10})
    assert result.status == NodeStatus.SUCCEEDED
    assert result.output.get("condition_result") is True


@pytest.mark.asyncio
async def test_condition_node_false(runner):
    node = _make_node(
        node_type=NodeType.CONDITION,
        config=NodeConfig(expression="x > 5"),
    )
    result = await runner.handle_node(node, {"x": 1})
    assert result.status == NodeStatus.SUCCEEDED
    assert result.output.get("condition_result") is False


@pytest.mark.asyncio
async def test_loop_node(runner):
    node = _make_node(
        node_type=NodeType.LOOP,
        config=NodeConfig(max_iterations=3, body_node_ids=["b1", "b2"]),
    )
    result = await runner.handle_node(node, {})
    assert result.status == NodeStatus.SUCCEEDED
    assert result.output["iterations"] == 3
    assert result.output["body_nodes"] == ["b1", "b2"]


@pytest.mark.asyncio
async def test_human_node(runner):
    node = _make_node(node_type=NodeType.HUMAN)
    result = await runner.handle_node(node, {"prompt": "approve?"})
    assert result.status == NodeStatus.SUCCEEDED
    assert result.output["status"] == "awaiting_input"


@pytest.mark.asyncio
async def test_planner_node(runner):
    node = _make_node(node_type=NodeType.PLANNER)
    result = await runner.handle_node(node, {"goal": "build x"})
    assert result.status == NodeStatus.SUCCEEDED
    assert "plan" in result.output


@pytest.mark.asyncio
async def test_input_mapping(runner):
    node = _make_node(
        node_type=NodeType.AGENT,
        input_mapping=[InputMapping(source="$.user.name", target="name")],
    )
    result = await runner.handle_node(node, {"user": {"name": "Alice"}})
    assert result.status == NodeStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_output_mapping(runner):
    node = _make_node(
        node_type=NodeType.AGENT,
        output_mapping=[OutputMapping(source="output", target="$.output_data")],
    )
    result = await runner.handle_node(node, {})
    assert result.status == NodeStatus.SUCCEEDED
    updated_context = runner.apply_output_mapping(node, result.output, {"existing": True})
    assert updated_context["existing"] is True
    assert "output_data" in updated_context


@pytest.mark.asyncio
async def test_timeout(runner):
    config = NodeConfig(timeout_seconds=1, retry_config=RetryConfig(max_retries=0))
    node = _make_node(node_type=NodeType.AGENT, config=config)
    result = await runner.handle_node(node, {})
    assert result.status == NodeStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_unknown_node_type(runner):
    class UnknownNode:
        id = "x"
        type = "unknown"
        label = "X"
        config = NodeConfig()
        input_mapping = []
        output_mapping = []

    result = await runner.handle_node(UnknownNode(), {})  # type: ignore
    assert result.status == NodeStatus.FAILED
    assert "No handler" in (result.error or "")
