import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.contract.contract_manager import ContractManager
from app.models.contract import TaskContract


@pytest.fixture
def mock_db():
    session = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def manager(mock_db):
    return ContractManager(db_session=mock_db)


@pytest.fixture
def sample_contract():
    return TaskContract(
        id=uuid.uuid4(),
        execution_id=uuid.uuid4(),
        contract_type="task",
        issuer_id="supervisor-1",
        executor_id="agent-1",
        task_name="write_code",
        task_description="Write Python code",
        input_schema={},
        output_schema={"code": "string", "tests": "array"},
        acceptance_criteria=[
            {"field": "code", "operator": "exists"},
            {"field": "tests", "operator": "contains", "value": "test_hello"},
        ],
        model_config={},
        timeout_seconds=300,
        priority=0,
        status="pending",
    )


class TestContractManager:
    @pytest.mark.asyncio
    async def test_create_contract(self, manager, mock_db):
        execution_id = uuid.uuid4()
        contract = await manager.create(
            execution_id=execution_id,
            issuer_id="supervisor-1",
            executor_id="agent-1",
            task_name="write_code",
            task_description="Write some code",
            output_schema={"code": "string"},
        )

        mock_db.add.assert_called_once()
        mock_db.flush.assert_awaited_once()
        assert contract.issuer_id == "supervisor-1"
        assert contract.executor_id == "agent-1"
        assert contract.task_name == "write_code"
        assert contract.status == "pending"
        assert contract.contract_type == "task"

    @pytest.mark.asyncio
    async def test_get_contract_found(self, manager, mock_db, sample_contract):
        scalar = MagicMock()
        scalar.scalar_one_or_none = MagicMock(return_value=sample_contract)
        mock_db.execute.return_value = scalar

        result = await manager.get(sample_contract.id)

        assert result is sample_contract
        mock_db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_contract_not_found(self, manager, mock_db):
        scalar = MagicMock()
        scalar.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute.return_value = scalar

        result = await manager.get(uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_list_by_executor(self, manager, mock_db, sample_contract):
        scalars = MagicMock()
        scalars.scalars.return_value.all.return_value = [sample_contract]
        mock_db.execute.return_value = scalars

        results = await manager.list(executor_id="agent-1")
        assert len(results) == 1
        assert results[0].executor_id == "agent-1"

    @pytest.mark.asyncio
    async def test_list_by_status(self, manager, mock_db, sample_contract):
        scalars = MagicMock()
        scalars.scalars.return_value.all.return_value = [sample_contract]
        mock_db.execute.return_value = scalars

        results = await manager.list(status="pending")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_accept_contract(self, manager, mock_db, sample_contract):
        scalar = MagicMock()
        scalar.scalar_one_or_none = MagicMock(return_value=sample_contract)
        mock_db.execute.return_value = scalar

        result = await manager.accept(sample_contract.id)
        assert result.status == "active"
        assert result.accepted_at is not None
        mock_db.flush.assert_awaited()

    @pytest.mark.asyncio
    async def test_accept_from_active_raises(self, manager, mock_db, sample_contract):
        sample_contract.status = "active"
        scalar = MagicMock()
        scalar.scalar_one_or_none = MagicMock(return_value=sample_contract)
        mock_db.execute.return_value = scalar

        with pytest.raises(ValueError, match="Cannot transition"):
            await manager.accept(sample_contract.id)

    @pytest.mark.asyncio
    async def test_complete_contract(self, manager, mock_db, sample_contract):
        sample_contract.status = "active"
        scalar = MagicMock()
        scalar.scalar_one_or_none = MagicMock(return_value=sample_contract)
        mock_db.execute.return_value = scalar

        result = await manager.complete(
            sample_contract.id,
            {"code": "print('hello')", "tests": ["test_hello"]},
        )
        assert result.status == "completed"
        assert result.result == {"code": "print('hello')", "tests": ["test_hello"]}

    @pytest.mark.asyncio
    async def test_complete_missing_field(self, manager, mock_db, sample_contract):
        sample_contract.status = "active"
        scalar = MagicMock()
        scalar.scalar_one_or_none = MagicMock(return_value=sample_contract)
        mock_db.execute.return_value = scalar

        with pytest.raises(ValueError, match="Missing required field"):
            await manager.complete(sample_contract.id, {"code": "print('hello')"})

    @pytest.mark.asyncio
    async def test_complete_criterion_fails(self, manager, mock_db, sample_contract):
        sample_contract.status = "active"
        scalar = MagicMock()
        scalar.scalar_one_or_none = MagicMock(return_value=sample_contract)
        mock_db.execute.return_value = scalar

        with pytest.raises(ValueError, match="does not contain"):
            await manager.complete(
                sample_contract.id,
                {"code": "print('hello')", "tests": ["unittest"]},
            )

    @pytest.mark.asyncio
    async def test_complete_from_pending_raises(self, manager, mock_db, sample_contract):
        scalar = MagicMock()
        scalar.scalar_one_or_none = MagicMock(return_value=sample_contract)
        mock_db.execute.return_value = scalar

        with pytest.raises(ValueError, match="Cannot transition"):
            await manager.complete(sample_contract.id, {})

    @pytest.mark.asyncio
    async def test_fail_contract(self, manager, mock_db, sample_contract):
        sample_contract.status = "active"
        scalar = MagicMock()
        scalar.scalar_one_or_none = MagicMock(return_value=sample_contract)
        mock_db.execute.return_value = scalar

        result = await manager.fail(sample_contract.id, "something broke")
        assert result.status == "failed"
        assert result.result == {"error": "something broke"}

    @pytest.mark.asyncio
    async def test_cancel_contract(self, manager, mock_db, sample_contract):
        sample_contract.status = "active"
        scalar = MagicMock()
        scalar.scalar_one_or_none = MagicMock(return_value=sample_contract)
        mock_db.execute.return_value = scalar

        result = await manager.cancel(sample_contract.id)
        assert result.status == "cancelled"

    @pytest.mark.asyncio
    async def test_dispute_contract(self, manager, mock_db, sample_contract):
        sample_contract.status = "active"
        scalar = MagicMock()
        scalar.scalar_one_or_none = MagicMock(return_value=sample_contract)
        mock_db.execute.return_value = scalar

        result = await manager.dispute(sample_contract.id, "quality too low")
        assert result.status == "disputed"
        assert result.result["dispute_reason"] == "quality too low"

    @pytest.mark.asyncio
    async def test_dispute_to_active_cycle(self, manager, mock_db, sample_contract):
        sample_contract.status = "disputed"
        scalar = MagicMock()
        scalar.scalar_one_or_none = MagicMock(return_value=sample_contract)
        mock_db.execute.return_value = scalar

        result = await manager.accept(sample_contract.id)
        assert result.status == "active"

    @pytest.mark.asyncio
    async def test_create_sub_contract(self, manager, mock_db, sample_contract):
        scalar = MagicMock()
        scalar.scalar_one_or_none = MagicMock(return_value=sample_contract)
        mock_db.execute.return_value = scalar

        sub = await manager.create_sub_contract(
            parent_id=sample_contract.id,
            executor_id="agent-2",
            task_name="write_tests",
        )

        mock_db.add.assert_called_with(sub)
        mock_db.flush.assert_awaited()
        assert sub.parent_contract_id == sample_contract.id
        assert sub.executor_id == "agent-2"
        assert sub.contract_type == "subtask"
        assert sub.execution_id == sample_contract.execution_id

    @pytest.mark.asyncio
    async def test_get_not_found_raises(self, manager, mock_db):
        scalar = MagicMock()
        scalar.scalar_one_or_none = MagicMock(return_value=None)
        mock_db.execute.return_value = scalar

        with pytest.raises(ValueError, match="not found"):
            await manager.accept(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_list_no_filters(self, manager, mock_db, sample_contract):
        scalars = MagicMock()
        scalars.scalars.return_value.all.return_value = [sample_contract]
        mock_db.execute.return_value = scalars

        results = await manager.list()
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_complete_validates_output_schema_types(self, manager, mock_db):
        c = TaskContract(
            id=uuid.uuid4(),
            execution_id=uuid.uuid4(),
            contract_type="task",
            issuer_id="s",
            executor_id="a",
            task_name="t",
            output_schema={"score": "number", "name": "string", "active": "boolean"},
            acceptance_criteria=[],
            status="active",
        )
        scalar = MagicMock()
        scalar.scalar_one_or_none = MagicMock(return_value=c)
        mock_db.execute.return_value = scalar

        with pytest.raises(ValueError, match="expected number"):
            await manager.complete(c.id, {"score": "high", "name": "x", "active": True})
