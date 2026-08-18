import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.supervisor.recovery import RecoveryManager, BACKOFF_DELAYS


@pytest.fixture
def mock_cm():
    cm = AsyncMock()
    cm.fail = AsyncMock()
    cm.get = AsyncMock()
    cm.db = MagicMock()
    cm.db.add = MagicMock()
    cm.db.flush = AsyncMock()
    return cm


@pytest.fixture
def mock_registry():
    reg = AsyncMock()
    reg.list = AsyncMock(return_value=[
        {"id": "agent-1", "name": "Agent 1", "status": "active"},
        {"id": "agent-2", "name": "Agent 2", "status": "active"},
    ])
    return reg


@pytest.fixture
def recovery(mock_cm, mock_registry):
    return RecoveryManager(contract_manager=mock_cm, agent_registry=mock_registry)


class TestRecoveryManager:
    @pytest.mark.asyncio
    async def test_handle_failure_contract_not_found(self, recovery, mock_cm):
        mock_cm.get.return_value = None
        result = await recovery.handle_failure(
            contract_id=uuid.uuid4(), error="error"
        )
        assert result["action"] == "pause"

    @pytest.mark.asyncio
    async def test_handle_failure_auto_retry(self, recovery, mock_cm):
        contract = MagicMock()
        contract.id = uuid.uuid4()
        contract.executor_id = "agent-1"
        mock_cm.get.return_value = contract

        result = await recovery.handle_failure(
            contract_id=contract.id, error="timeout", strategy="auto"
        )
        assert result["action"] == "retry"
        assert "attempt 1" in result["detail"]

    @pytest.mark.asyncio
    async def test_retry_exponential_backoff(self, recovery, mock_cm):
        contract = MagicMock()
        contract.id = uuid.uuid4()
        contract.executor_id = "agent-1"
        contract.status = "failed"
        contract.result = {"error": "fail"}
        mock_cm.get.return_value = contract

        for i, expected_delay in enumerate(BACKOFF_DELAYS):
            result = await recovery.retry(contract.id)
            assert result["action"] == "retry"
            assert result["delay"] == expected_delay

        result = await recovery.retry(contract.id)
        assert result["action"] == "pause"
        assert "exhausted" in result["detail"]

    @pytest.mark.asyncio
    async def test_replace_agent(self, recovery, mock_cm):
        contract_id = uuid.uuid4()
        contract = MagicMock()
        mock_cm.get.return_value = contract

        result = await recovery.replace_agent(contract_id, "agent-2")
        assert result["action"] == "replace"
        assert "agent-2" in result["detail"]

    @pytest.mark.asyncio
    async def test_handle_failure_replace_strategy(self, recovery, mock_cm):
        contract = MagicMock()
        contract.id = uuid.uuid4()
        contract.executor_id = "agent-1"
        mock_cm.get.return_value = contract

        recovery._retry_counts[contract.id] = len(BACKOFF_DELAYS)

        result = await recovery.handle_failure(
            contract_id=contract.id, error="fail", strategy="replace"
        )
        assert result["action"] == "replace"

    @pytest.mark.asyncio
    async def test_handle_failure_skip_strategy(self, recovery, mock_cm):
        contract = MagicMock()
        contract.id = uuid.uuid4()
        mock_cm.get.return_value = contract

        result = await recovery.handle_failure(
            contract_id=contract.id, error="error", strategy="skip"
        )
        assert result["action"] == "skip"

    @pytest.mark.asyncio
    async def test_handle_failure_pause_strategy(self, recovery, mock_cm):
        contract = MagicMock()
        contract.id = uuid.uuid4()
        mock_cm.get.return_value = contract

        result = await recovery.handle_failure(
            contract_id=contract.id, error="error", strategy="pause"
        )
        assert result["action"] == "pause"

    @pytest.mark.asyncio
    async def test_handle_failure_modify_workflow(self, recovery, mock_cm):
        contract = MagicMock()
        contract.id = uuid.uuid4()
        mock_cm.get.return_value = contract

        result = await recovery.handle_failure(
            contract_id=contract.id, error="error", strategy="modify_workflow"
        )
        assert result["action"] == "modify_workflow"

    @pytest.mark.asyncio
    async def test_auto_strategy_exhausted_retries_finds_alternative(self, recovery, mock_cm, mock_registry):
        contract = MagicMock()
        contract.id = uuid.uuid4()
        contract.executor_id = "agent-1"
        mock_cm.get.return_value = contract

        recovery._retry_counts[contract.id] = len(BACKOFF_DELAYS)

        result = await recovery.handle_failure(
            contract_id=contract.id, error="fail", strategy="auto"
        )
        assert result["action"] == "replace"

    @pytest.mark.asyncio
    async def test_find_alternative_all_busy(self, recovery, mock_registry):
        mock_registry.list_agents.return_value = [{"id": "agent-1", "status": "active"}]
        alt = await recovery._find_alternative("agent-1")
        assert alt is None

    @pytest.mark.asyncio
    async def test_handle_failure_skip_based_on_error(self, recovery, mock_cm):
        contract = MagicMock()
        contract.id = uuid.uuid4()
        contract.executor_id = "agent-1"
        mock_cm.get.return_value = contract

        recovery._retry_counts[contract.id] = len(BACKOFF_DELAYS)
        mock_registry_empty = AsyncMock()
        mock_registry_empty.list = AsyncMock(return_value=[{"id": "agent-1", "status": "active"}])
        recovery._registry = mock_registry_empty

        result = await recovery.handle_failure(
            contract_id=contract.id, error="skip this error", strategy="auto"
        )
        assert result["action"] == "skip"
