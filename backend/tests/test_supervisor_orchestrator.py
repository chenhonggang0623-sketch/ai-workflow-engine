import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.supervisor.orchestrator import SupervisorOrchestrator
from app.supervisor.evaluation import EvaluationEngine
from app.supervisor.quality_gate import QualityGate
from app.supervisor.recovery import RecoveryManager
from app.engine.types import NodeStatus


@pytest.fixture
def mock_db():
    session = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none = MagicMock(return_value=None)

    async def execute_side(*args, **kwargs):
        return scalar_result
    session.execute = AsyncMock(side_effect=execute_side)
    return session


@pytest.fixture
def mock_components(mock_db):
    eval_engine = EvaluationEngine(db_session=mock_db)
    eval_engine._update_agent_performance = AsyncMock()
    gate = QualityGate(eval_engine)
    cm = AsyncMock()
    cm.create = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
    cm.complete = AsyncMock()
    recovery = AsyncMock(spec=RecoveryManager)
    recovery.handle_failure = AsyncMock(return_value={"action": "skip", "detail": "test"})
    broker = AsyncMock()
    broker.broadcast = AsyncMock()
    executor = AsyncMock()
    executor.execute = AsyncMock(return_value={"code": "print('hello')", "tool_calls": [], "usage": {}})
    ctx = AsyncMock()
    ctx.get = AsyncMock(return_value={"key": "value"})
    ctx.set_value = AsyncMock()
    artifact = AsyncMock()
    artifact.store = AsyncMock()
    return {
        "db": mock_db,
        "eval": eval_engine,
        "gate": gate,
        "cm": cm,
        "recovery": recovery,
        "broker": broker,
        "executor": executor,
        "ctx": ctx,
        "artifact": artifact,
    }


@pytest.fixture
def orchestrator(mock_components):
    return SupervisorOrchestrator(
        db_session=mock_components["db"],
        evaluation_engine=mock_components["eval"],
        quality_gate=mock_components["gate"],
        recovery_manager=mock_components["recovery"],
        contract_manager=mock_components["cm"],
        comm_broker=mock_components["broker"],
        agent_executor=mock_components["executor"],
        context_manager=mock_components["ctx"],
        artifact_manager=mock_components["artifact"],
    )


class TestSupervisorOrchestrator:
    @pytest.mark.asyncio
    async def test_supervise_node_success(self, orchestrator, mock_components):
        execution_id = uuid.uuid4()
        node_exec = {
            "id": "node-1",
            "label": "Write Code",
            "execution_id": str(execution_id),
            "agent_id": "developer_agent",
            "input_schema": {"task": "string"},
            "output_schema": {"code": "string"},
            "acceptance_criteria": [],
            "input": {"task": "write hello world"},
        }
        context = {"execution_id": str(execution_id)}

        result = await orchestrator.supervise_node(node_exec, context)
        assert result["status"] == NodeStatus.SUCCEEDED.value
        assert "output" in result

    @pytest.mark.asyncio
    async def test_supervise_node_no_agent(self, orchestrator):
        node_exec = {
            "id": "node-1",
            "execution_id": str(uuid.uuid4()),
        }
        result = await orchestrator.supervise_node(node_exec, {})
        assert result["status"] == NodeStatus.SKIPPED.value

    @pytest.mark.asyncio
    async def test_supervise_node_agent_error(self, orchestrator, mock_components):
        mock_components["executor"].execute.return_value = {"error": "LLM unavailable"}
        mock_components["recovery"].handle_failure.return_value = {
            "action": "skip", "detail": "LLM unavailable, skipping"
        }

        node_exec = {
            "id": "node-1",
            "label": "Test",
            "execution_id": str(uuid.uuid4()),
            "agent_id": "developer_agent",
            "input_schema": {},
            "output_schema": {},
            "acceptance_criteria": [],
        }
        result = await orchestrator.supervise_node(node_exec, {})
        assert result["status"] == NodeStatus.SKIPPED.value
        assert "recovery" in result

    @pytest.mark.asyncio
    async def test_supervise_node_recovery_retry(self, orchestrator, mock_components):
        mock_components["executor"].execute.return_value = {"error": "timeout"}
        mock_components["recovery"].handle_failure.return_value = {
            "action": "retry", "detail": "Retrying..."
        }

        node_exec = {
            "id": "node-1",
            "label": "Test",
            "execution_id": str(uuid.uuid4()),
            "agent_id": "developer_agent",
            "input_schema": {},
            "output_schema": {},
            "acceptance_criteria": [],
        }
        result = await orchestrator.supervise_node(node_exec, {})
        assert "recovery" in result
        assert result["recovery"]["action"] == "retry"

    @pytest.mark.asyncio
    async def test_supervise_node_recovery_pause(self, orchestrator, mock_components):
        mock_components["executor"].execute.return_value = {"error": "needs human"}
        mock_components["recovery"].handle_failure.return_value = {
            "action": "pause", "detail": "Waiting for human"
        }

        node_exec = {
            "id": "node-1",
            "label": "Test",
            "execution_id": str(uuid.uuid4()),
            "agent_id": "developer_agent",
            "input_schema": {},
            "output_schema": {},
            "acceptance_criteria": [],
        }
        result = await orchestrator.supervise_node(node_exec, {})
        assert result["status"] == NodeStatus.WAITING.value

    @pytest.mark.asyncio
    async def test_get_progress_not_found(self, orchestrator):
        progress = await orchestrator.get_progress(uuid.uuid4())
        assert progress["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_get_progress_in_memory(self, orchestrator):
        exec_id = uuid.uuid4()
        orchestrator._progress[exec_id] = {
            "total": 5, "completed": 2, "failed": 0, "skipped": 0,
            "status": "running", "started_at": "now",
        }
        progress = await orchestrator.get_progress(exec_id)
        assert progress["total"] == 5
        assert progress["completed"] == 2
