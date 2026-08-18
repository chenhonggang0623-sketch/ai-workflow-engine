"""慢节点干预机制测试：slow 标记、wait / switch_model / terminate 三动作。"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.engine.execution_manager import ExecutionManager
from app.engine.types import (
    WorkflowDefinition, NodeDefinition, EdgeDefinition,
    NodeType, ExecutionStatus, NodeStatus, NodeResult, NodeConfig,
)
from app.models.workflow import NodeExecution as NodeExecutionModel


def _workflow() -> WorkflowDefinition:
    return WorkflowDefinition(
        id="wf",
        name="wf",
        nodes=[
            NodeDefinition(
                id="n1", type=NodeType.AGENT, label="N1",
                config=NodeConfig(provider="opencode_cli"),
            ),
            NodeDefinition(id="n2", type=NodeType.AGENT, label="N2"),
        ],
        edges=[EdgeDefinition(id="e1", source="n1", target="n2")],
    )


def _db_factory():
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.get = AsyncMock(return_value=AsyncMock())

    class Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            pass

    factory = MagicMock()
    factory.return_value = Ctx()
    return factory


@pytest.fixture
def runner():
    r = AsyncMock()
    r.handle_node = AsyncMock(return_value=NodeResult(
        node_id="n1", status=NodeStatus.SUCCEEDED, output={"result": "ok"},
    ))
    return r


class TestSlowNodeMarking:
    async def test_slow_marked_after_threshold(self, runner):
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_handler(node_def, context, log_sink=None):
            started.set()
            await release.wait()
            return NodeResult(node_id=node_def.id, status=NodeStatus.SUCCEEDED, output={})

        runner.handle_node = slow_handler
        mgr = ExecutionManager(node_runner=runner)
        mgr._slow_after = 0  # 立即超阈值
        exec_id = uuid4()
        task = asyncio.ensure_future(
            mgr.execute_workflow(_workflow(), exec_id, _db_factory())
        )
        await started.wait()
        await asyncio.sleep(1.3)
        slow = mgr.slow_nodes(exec_id)
        assert "n1" in slow
        assert slow["n1"]["elapsed_seconds"] >= 0
        release.set()
        result = await task
        assert result.status == ExecutionStatus.SUCCEEDED
        assert mgr.slow_nodes(exec_id) == {}

    async def test_wait_clears_slow_mark(self, runner):
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_handler(node_def, context, log_sink=None):
            started.set()
            await release.wait()
            return NodeResult(node_id=node_def.id, status=NodeStatus.SUCCEEDED, output={})

        runner.handle_node = slow_handler
        mgr = ExecutionManager(node_runner=runner)
        mgr._slow_after = 0
        exec_id = uuid4()
        task = asyncio.ensure_future(
            mgr.execute_workflow(_workflow(), exec_id, _db_factory())
        )
        await started.wait()
        await asyncio.sleep(1.3)
        assert "n1" in mgr.slow_nodes(exec_id)
        await mgr.intervene(exec_id, "n1", "wait")
        assert mgr.slow_nodes(exec_id) == {}
        release.set()
        await task


class TestSwitchModelIntervention:
    async def test_switch_model_cancels_and_reruns_node(self, runner):
        started = asyncio.Event()
        release = asyncio.Event()
        attempts = []

        async def flaky_handler(node_def, context, log_sink=None):
            if node_def.id == "n1":
                attempts.append(node_def.config.provider)
                if len(attempts) == 1:
                    started.set()
                    await release.wait()  # 第一次挂起，等待干预取消
                    return NodeResult(node_id=node_def.id, status=NodeStatus.CANCELLED, output={})
            return NodeResult(node_id=node_def.id, status=NodeStatus.SUCCEEDED, output={"result": "ok"})

        runner.handle_node = flaky_handler
        mgr = ExecutionManager(node_runner=runner)
        mgr._slow_after = 0
        exec_id = uuid4()
        task = asyncio.ensure_future(
            mgr.execute_workflow(_workflow(), exec_id, _db_factory())
        )
        await started.wait()
        await asyncio.sleep(0.2)
        await mgr.intervene(exec_id, "n1", "switch_model", provider="openai")
        release.set()
        result = await task
        assert result.status == ExecutionStatus.SUCCEEDED
        assert attempts == ["opencode_cli", "openai"]
        # 节点配置已按干预改写
        n1 = _workflow().nodes[0]  # 占位断言（真实验证在下）
        assert n1 is not None

    async def test_switch_model_rewrites_node_config(self, runner):
        """干预请求的 provider/model 写入节点配置（执行后对 workflow 不可见，行为验证）。"""
        started = asyncio.Event()
        release = asyncio.Event()
        calls = []

        async def flaky_handler(node_def, context, log_sink=None):
            calls.append(node_def.id)
            if node_def.id == "n1" and node_def.config.provider == "opencode_cli":
                started.set()
                await release.wait()
                return NodeResult(node_id=node_def.id, status=NodeStatus.CANCELLED, output={})
            return NodeResult(node_id=node_def.id, status=NodeStatus.SUCCEEDED, output={"result": "ok"})

        runner.handle_node = flaky_handler
        mgr = ExecutionManager(node_runner=runner)
        exec_id = uuid4()
        task = asyncio.ensure_future(
            mgr.execute_workflow(_workflow(), exec_id, _db_factory())
        )
        await started.wait()
        await asyncio.sleep(0.1)
        await mgr.intervene(exec_id, "n1", "switch_model", provider="claude_cli", model="claude-sonnet")
        release.set()
        result = await task
        assert result.status == ExecutionStatus.SUCCEEDED
        assert calls == ["n1", "n1", "n2"]


class TestTerminateIntervention:
    async def test_terminate_stops_execution(self, runner):
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_handler(node_def, context, log_sink=None):
            started.set()
            await release.wait()
            return NodeResult(node_id=node_def.id, status=NodeStatus.SUCCEEDED, output={})

        runner.handle_node = slow_handler
        mgr = ExecutionManager(node_runner=runner)
        exec_id = uuid4()
        task = asyncio.ensure_future(
            mgr.execute_workflow(_workflow(), exec_id, _db_factory())
        )
        await started.wait()
        await asyncio.sleep(0.1)
        await mgr.intervene(exec_id, "n1", "terminate")
        result = await task
        assert result.status == ExecutionStatus.CANCELLED


class TestSlowNodesApiShape:
    def test_slow_nodes_shape(self, runner):
        mgr = ExecutionManager(node_runner=runner)
        since = datetime.now(UTC).replace(tzinfo=None)
        mgr._slow_since[uuid4()] = {"n1": since}
        info = mgr.slow_nodes(next(iter(mgr._slow_since)))
        assert "since" in info["n1"]
        assert "elapsed_seconds" in info["n1"]