import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from app.engine.execution_manager import ExecutionManager
from app.engine.state_machine import ExecutionStateMachine
from app.engine.node_runner import NodeRunner
from app.engine.types import (
    WorkflowDefinition, NodeDefinition, EdgeDefinition,
    NodeType, NodeConfig, ExecutionStatus, NodeStatus, NodeResult,
)
from app.models.workflow import NodeExecution as NodeExecutionModel


def _make_linear_workflow() -> WorkflowDefinition:
    return WorkflowDefinition(
        id="wf1",
        name="linear",
        nodes=[
            NodeDefinition(id="n1", type=NodeType.AGENT, label="N1"),
            NodeDefinition(id="n2", type=NodeType.AGENT, label="N2"),
            NodeDefinition(id="n3", type=NodeType.AGENT, label="N3"),
        ],
        edges=[
            EdgeDefinition(id="e1", source="n1", target="n2"),
            EdgeDefinition(id="e2", source="n2", target="n3"),
        ],
    )


def _make_diamond_workflow() -> WorkflowDefinition:
    return WorkflowDefinition(
        id="wf2",
        name="diamond",
        nodes=[
            NodeDefinition(id="a", type=NodeType.AGENT, label="A"),
            NodeDefinition(id="b", type=NodeType.AGENT, label="B"),
            NodeDefinition(id="c", type=NodeType.AGENT, label="C"),
            NodeDefinition(id="d", type=NodeType.AGENT, label="D"),
        ],
        edges=[
            EdgeDefinition(id="e1", source="a", target="b"),
            EdgeDefinition(id="e2", source="a", target="c"),
            EdgeDefinition(id="e3", source="b", target="d"),
            EdgeDefinition(id="e4", source="c", target="d"),
        ],
    )


@pytest.fixture
def mock_node_runner():
    runner = AsyncMock(spec=NodeRunner)
    runner.handle_node = AsyncMock(return_value=NodeResult(
        node_id="n1",
        status=NodeStatus.SUCCEEDED,
        output={"result": "ok"},
    ))
    return runner


@pytest.fixture
def mock_db_factory():
    """Creates a mock async_session_factory that returns an async ctx mgr."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.get = AsyncMock(return_value=AsyncMock())

    class MockCtxMgr:
        async def __aenter__(self):
            return session
        async def __aexit__(self, *args):
            pass

    factory = MagicMock()
    factory.return_value = MockCtxMgr()
    return factory


def test_instantiation():
    runner = AsyncMock(spec=NodeRunner)
    mgr = ExecutionManager(node_runner=runner, max_concurrency=5)
    assert mgr is not None


@pytest.mark.asyncio
async def test_execute_linear_workflow(mock_node_runner, mock_db_factory):
    mgr = ExecutionManager(node_runner=mock_node_runner, max_concurrency=5)
    exec_id = uuid4()
    mock_node_runner.handle_node = AsyncMock(return_value=NodeResult(
        node_id="n1", status=NodeStatus.SUCCEEDED, output={"result": "ok"},
    ))
    result = await mgr.execute_workflow(
        _make_linear_workflow(), exec_id, mock_db_factory, {"initial": "data"},
    )
    assert result.status == ExecutionStatus.SUCCEEDED
    assert result.context.get("initial") == "data"


@pytest.mark.asyncio
async def test_execute_diamond_workflow(mock_node_runner, mock_db_factory):
    mgr = ExecutionManager(node_runner=mock_node_runner, max_concurrency=5)
    exec_id = uuid4()
    mock_node_runner.handle_node = AsyncMock(return_value=NodeResult(
        node_id="n", status=NodeStatus.SUCCEEDED, output={},
    ))
    result = await mgr.execute_workflow(_make_diamond_workflow(), exec_id, mock_db_factory)
    assert result.status == ExecutionStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_execute_empty_workflow(mock_node_runner, mock_db_factory):
    mgr = ExecutionManager(node_runner=mock_node_runner, max_concurrency=5)
    exec_id = uuid4()
    wf = WorkflowDefinition(name="empty", nodes=[], edges=[])
    result = await mgr.execute_workflow(wf, exec_id, mock_db_factory)
    assert result.status == ExecutionStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_execute_single_node(mock_node_runner, mock_db_factory):
    mgr = ExecutionManager(node_runner=mock_node_runner, max_concurrency=5)
    exec_id = uuid4()
    mock_node_runner.handle_node = AsyncMock(return_value=NodeResult(
        node_id="n1", status=NodeStatus.SUCCEEDED, output={},
    ))
    wf = WorkflowDefinition(
        name="single",
        nodes=[NodeDefinition(id="n1", type=NodeType.AGENT, label="N1")],
        edges=[],
    )
    result = await mgr.execute_workflow(wf, exec_id, mock_db_factory)
    assert result.status == ExecutionStatus.SUCCEEDED
    assert len(result.node_results) == 1


@pytest.mark.asyncio
async def test_parallel_staggered_completion(mock_node_runner, mock_db_factory):
    """Regression: parallel nodes finishing at different times must not call
    result() on pending tasks (InvalidStateError) and must all complete."""
    mgr = ExecutionManager(node_runner=mock_node_runner, max_concurrency=5)
    exec_id = uuid4()
    delays = {"a": 0.05, "b": 0.2, "c": 0.35}

    async def fake_handle(node, context, log_sink=None):
        await asyncio.sleep(delays.get(node.id, 0))
        return NodeResult(
            node_id=node.id, status=NodeStatus.SUCCEEDED,
            output={"result": node.id},
        )

    mock_node_runner.handle_node = fake_handle
    wf = WorkflowDefinition(
        name="parallel-staggered",
        nodes=[
            NodeDefinition(id="a", type=NodeType.AGENT, label="A"),
            NodeDefinition(id="b", type=NodeType.AGENT, label="B"),
            NodeDefinition(id="c", type=NodeType.AGENT, label="C"),
            NodeDefinition(id="d", type=NodeType.AGENT, label="D"),
        ],
        edges=[
            EdgeDefinition(id="e1", source="a", target="d"),
            EdgeDefinition(id="e2", source="b", target="d"),
            EdgeDefinition(id="e3", source="c", target="d"),
        ],
    )
    result = await mgr.execute_workflow(wf, exec_id, mock_db_factory)
    assert result.status == ExecutionStatus.SUCCEEDED
    assert len(result.node_results) == 4
    assert {r.node_id for r in result.node_results} == {"a", "b", "c", "d"}
    assert all(r.status == NodeStatus.SUCCEEDED for r in result.node_results)


@pytest.mark.asyncio
async def test_parallel_partial_failure_stops_downstream(mock_node_runner, mock_db_factory):
    """One parallel node failing must abort the batch and never start downstream."""
    mgr = ExecutionManager(node_runner=mock_node_runner, max_concurrency=5)
    exec_id = uuid4()
    executed: list[str] = []

    async def fake_handle(node, context, log_sink=None):
        executed.append(node.id)
        await asyncio.sleep({}.get(node.id, 0))
        if node.id == "b":
            return NodeResult(
                node_id="b", status=NodeStatus.FAILED, error="boom",
            )
        return NodeResult(
            node_id=node.id, status=NodeStatus.SUCCEEDED, output={},
        )

    mock_node_runner.handle_node = fake_handle
    wf = WorkflowDefinition(
        name="parallel-partial-fail",
        nodes=[
            NodeDefinition(id="a", type=NodeType.AGENT, label="A"),
            NodeDefinition(id="b", type=NodeType.AGENT, label="B"),
            NodeDefinition(id="c", type=NodeType.AGENT, label="C"),
        ],
        edges=[
            EdgeDefinition(id="e1", source="a", target="c"),
            EdgeDefinition(id="e2", source="b", target="c"),
        ],
    )
    result = await mgr.execute_workflow(wf, exec_id, mock_db_factory)
    assert result.status == ExecutionStatus.FAILED
    assert "c" not in executed
    failed = [r for r in result.node_results if r.status == NodeStatus.FAILED]
    assert len(failed) == 1 and failed[0].error == "boom"


@pytest.mark.asyncio
async def test_cyclic_workflow_raises(mock_node_runner, mock_db_factory):
    mgr = ExecutionManager(node_runner=mock_node_runner, max_concurrency=5)
    exec_id = uuid4()
    wf = WorkflowDefinition(
        name="cycle",
        nodes=[
            NodeDefinition(id="a", type=NodeType.AGENT, label="A"),
            NodeDefinition(id="b", type=NodeType.AGENT, label="B"),
        ],
        edges=[
            EdgeDefinition(id="e1", source="a", target="b"),
            EdgeDefinition(id="e2", source="b", target="a"),
        ],
    )
    with pytest.raises(ValueError, match="cycle"):
        await mgr.execute_workflow(wf, exec_id, mock_db_factory)


@pytest.mark.asyncio
async def test_pause_completed_raises(mock_node_runner, mock_db_factory):
    mgr = ExecutionManager(node_runner=mock_node_runner, max_concurrency=5)
    exec_id = uuid4()
    mock_node_runner.handle_node = AsyncMock(return_value=NodeResult(
        node_id="n1", status=NodeStatus.SUCCEEDED, output={},
    ))
    result = await mgr.execute_workflow(_make_linear_workflow(), exec_id, mock_db_factory)
    with pytest.raises(ValueError, match="not found"):
        await mgr.pause(result.execution_id)


@pytest.mark.asyncio
async def test_pause_resume_lifecycle(mock_node_runner, mock_db_factory):
    mgr = ExecutionManager(node_runner=mock_node_runner, max_concurrency=5)
    exec_id = uuid4()
    sm = ExecutionStateMachine(execution_id=exec_id)
    sm.start(3)
    mgr._state_machines[exec_id] = sm
    await mgr.pause(exec_id)
    assert sm.status == ExecutionStatus.PAUSED
    await mgr.resume(exec_id)
    assert sm.status == ExecutionStatus.RUNNING


@pytest.mark.asyncio
async def test_cancel(mock_node_runner, mock_db_factory):
    mgr = ExecutionManager(node_runner=mock_node_runner, max_concurrency=5)
    exec_id = uuid4()
    mock_node_runner.handle_node = AsyncMock(return_value=NodeResult(
        node_id="n1", status=NodeStatus.SUCCEEDED, output={},
    ))
    task = asyncio.create_task(
        mgr.execute_workflow(_make_linear_workflow(), exec_id, mock_db_factory)
    )
    await asyncio.sleep(0.02)
    found_id = next(iter(mgr._state_machines), None)
    if found_id:
        await mgr.cancel(found_id)
    result = await task
    assert result.status in (ExecutionStatus.SUCCEEDED, ExecutionStatus.CANCELLED)


@pytest.mark.asyncio
async def test_cancel_interrupts_running_node(mock_node_runner, mock_db_factory):
    """cancel 必须中断正在运行的节点，而不是等待其自然结束。"""
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_handler(node_def, context, log_sink=None):
        started.set()
        await release.wait()
        return NodeResult(node_id=node_def.id, status=NodeStatus.SUCCEEDED, output={})

    mock_node_runner.handle_node = slow_handler
    mgr = ExecutionManager(node_runner=mock_node_runner, max_concurrency=5)
    exec_id = uuid4()
    wf = WorkflowDefinition(
        name="slow",
        nodes=[NodeDefinition(id="n1", type=NodeType.AGENT, label="N1")],
        edges=[],
    )
    task = asyncio.create_task(
        mgr.execute_workflow(wf, exec_id, mock_db_factory)
    )
    await started.wait()
    found_id = next(iter(mgr._state_machines), None)
    await mgr.cancel(found_id)
    result = await asyncio.wait_for(task, timeout=2)
    release.set()
    assert result.status == ExecutionStatus.CANCELLED
    assert not result.node_results
    assert mgr.is_cancel_requested(found_id)


@pytest.mark.asyncio
async def test_get_status_after_completion_raises(mock_node_runner, mock_db_factory):
    mgr = ExecutionManager(node_runner=mock_node_runner, max_concurrency=5)
    exec_id = uuid4()
    mock_node_runner.handle_node = AsyncMock(return_value=NodeResult(
        node_id="n1", status=NodeStatus.SUCCEEDED, output={},
    ))
    result = await mgr.execute_workflow(_make_linear_workflow(), exec_id, mock_db_factory)
    with pytest.raises(ValueError, match="not found"):
        mgr.get_status(result.execution_id)


@pytest.mark.asyncio
async def test_get_status_not_found(mock_node_runner, mock_db_factory):
    mgr = ExecutionManager(node_runner=mock_node_runner, max_concurrency=5)
    with pytest.raises(ValueError):
        mgr.get_status(uuid4())


@pytest.mark.asyncio
async def test_pause_not_found(mock_node_runner, mock_db_factory):
    mgr = ExecutionManager(node_runner=mock_node_runner, max_concurrency=5)
    with pytest.raises(ValueError):
        await mgr.pause(uuid4())


@pytest.mark.asyncio
async def test_context_propagation(mock_node_runner, mock_db_factory):
    mgr = ExecutionManager(node_runner=mock_node_runner, max_concurrency=5)
    exec_id = uuid4()
    mock_node_runner.handle_node = AsyncMock(return_value=NodeResult(
        node_id="n1", status=NodeStatus.SUCCEEDED, output={},
    ))
    result = await mgr.execute_workflow(
        _make_linear_workflow(), exec_id, mock_db_factory, {"user": "alice"},
    )
    assert result.context.get("user") == "alice"


def _audit_output(recommend: bool) -> dict:
    return {
        "findings": [{"severity": "critical", "issue": "nope"}],
        "_executor_metadata": {
            "provider": "ensemble",
            "status": "success",
            "ensemble": {
                "mode": "audit",
                "critical_count": 1 if recommend else 0,
                "recommend_rerun": recommend,
                "findings": [{"severity": "critical", "issue": "nope"}],
                "reviewers": ["auditor1"],
            },
        },
    }


@pytest.mark.asyncio
async def test_audit_recommend_rerun_surfaces_signal(mock_node_runner, mock_db_factory):
    mgr = ExecutionManager(node_runner=mock_node_runner, max_concurrency=5)
    exec_id = uuid4()
    mock_node_runner.handle_node = AsyncMock(return_value=NodeResult(
        node_id="n1", status=NodeStatus.SUCCEEDED, output=_audit_output(True),
    ))
    result = await mgr.execute_workflow(_make_linear_workflow(), exec_id, mock_db_factory)
    assert result.status == ExecutionStatus.SUCCEEDED
    assert len(result.rerun_recommendations) == 3
    rec = result.rerun_recommendations[0]
    assert rec["node_id"] == "n1"
    assert rec["critical_count"] == 1
    assert rec["reviewers"] == ["auditor1"]
    assert result.context["_rerun_recommendations"] == result.rerun_recommendations


@pytest.mark.asyncio
async def test_audit_no_recommend_when_clean(mock_node_runner, mock_db_factory):
    mgr = ExecutionManager(node_runner=mock_node_runner, max_concurrency=5)
    exec_id = uuid4()
    mock_node_runner.handle_node = AsyncMock(return_value=NodeResult(
        node_id="n1", status=NodeStatus.SUCCEEDED, output=_audit_output(False),
    ))
    result = await mgr.execute_workflow(_make_linear_workflow(), exec_id, mock_db_factory)
    assert result.status == ExecutionStatus.SUCCEEDED
    assert result.rerun_recommendations == []


@pytest.mark.asyncio
async def test_no_rerun_signal_for_non_audit_nodes(mock_node_runner, mock_db_factory):
    mgr = ExecutionManager(node_runner=mock_node_runner, max_concurrency=5)
    exec_id = uuid4()
    mock_node_runner.handle_node = AsyncMock(return_value=NodeResult(
        node_id="n1", status=NodeStatus.SUCCEEDED, output={"result": "ok"},
    ))
    result = await mgr.execute_workflow(_make_linear_workflow(), exec_id, mock_db_factory)
    assert result.status == ExecutionStatus.SUCCEEDED
    assert result.rerun_recommendations == []
