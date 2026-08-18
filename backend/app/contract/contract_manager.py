import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract import TaskContract


class ContractManager:
    VALID_TRANSITIONS = {
        "pending": ["active"],
        "active": ["completed", "failed", "cancelled", "disputed"],
        "disputed": ["active", "cancelled"],
        "completed": [],
        "failed": [],
        "cancelled": [],
    }

    def __init__(self, db_session: AsyncSession, evaluation_engine: Any = None):
        self.db = db_session
        self.evaluation_engine = evaluation_engine

    async def create(
        self,
        execution_id: uuid.UUID,
        issuer_id: str,
        executor_id: str,
        task_name: str,
        task_description: str = "",
        input_schema: dict | None = None,
        output_schema: dict | None = None,
        acceptance_criteria: list | None = None,
        model_config: dict | None = None,
        timeout_seconds: int = 300,
        priority: int = 0,
    ) -> TaskContract:
        contract = TaskContract(
            id=uuid.uuid4(),
            execution_id=execution_id,
            contract_type="task",
            issuer_id=issuer_id,
            executor_id=executor_id,
            task_name=task_name,
            task_description=task_description,
            input_schema=input_schema or {},
            output_schema=output_schema or {},
            acceptance_criteria=acceptance_criteria or [],
            model_config=model_config or {},
            timeout_seconds=timeout_seconds,
            priority=priority,
            status="pending",
        )
        self.db.add(contract)
        await self.db.flush()
        return contract

    async def get(self, contract_id: uuid.UUID) -> TaskContract | None:
        result = await self.db.execute(
            select(TaskContract).where(TaskContract.id == contract_id)
        )
        return result.scalar_one_or_none()

    async def list_contracts(
        self,
        executor_id: str | None = None,
        status: str | None = None,
    ) -> list[TaskContract]:
        stmt = select(TaskContract)
        if executor_id:
            stmt = stmt.where(TaskContract.executor_id == executor_id)
        if status:
            stmt = stmt.where(TaskContract.status == status)
        stmt = stmt.order_by(TaskContract.priority.desc(), TaskContract.issued_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def accept(self, contract_id: uuid.UUID) -> TaskContract:
        contract = await self._get_or_raise(contract_id)
        self._assert_transition(contract.status, "active")
        contract.status = "active"
        contract.accepted_at = datetime.now(UTC).replace(tzinfo=None)
        await self.db.flush()
        return contract

    async def complete(self, contract_id: uuid.UUID, result: dict) -> TaskContract:
        contract = await self._get_or_raise(contract_id)
        self._assert_transition(contract.status, "completed")
        errors = self._validate_result(contract, result)
        if errors:
            raise ValueError(f"Result validation failed: {'; '.join(errors)}")
        contract.status = "completed"
        contract.result = result
        contract.completed_at = datetime.now(UTC).replace(tzinfo=None)
        await self.db.flush()
        return contract

    async def fail(self, contract_id: uuid.UUID, error: str) -> TaskContract:
        contract = await self._get_or_raise(contract_id)
        self._assert_transition(contract.status, "failed")
        contract.status = "failed"
        contract.result = {"error": error}
        await self.db.flush()
        return contract

    async def cancel(self, contract_id: uuid.UUID) -> TaskContract:
        contract = await self._get_or_raise(contract_id)
        self._assert_transition(contract.status, "cancelled")
        contract.status = "cancelled"
        await self.db.flush()
        return contract

    async def dispute(self, contract_id: uuid.UUID, reason: str) -> TaskContract:
        contract = await self._get_or_raise(contract_id)
        self._assert_transition(contract.status, "disputed")
        contract.status = "disputed"
        if contract.result is None:
            contract.result = {}
        contract.result["dispute_reason"] = reason
        await self.db.flush()
        return contract

    async def create_sub_contract(
        self,
        parent_id: uuid.UUID,
        executor_id: str,
        task_name: str,
        **kwargs,
    ) -> TaskContract:
        parent = await self._get_or_raise(parent_id)
        sub = TaskContract(
            id=uuid.uuid4(),
            execution_id=parent.execution_id,
            parent_contract_id=parent.id,
            contract_type="subtask",
            issuer_id=parent.issuer_id,
            executor_id=executor_id,
            task_name=task_name,
            task_description=kwargs.pop("task_description", ""),
            input_schema=kwargs.pop("input_schema", parent.input_schema),
            output_schema=kwargs.pop("output_schema", parent.output_schema),
            acceptance_criteria=kwargs.pop("acceptance_criteria", parent.acceptance_criteria),
            model_config=kwargs.pop("model_config", parent.model_config),
            timeout_seconds=kwargs.pop("timeout_seconds", parent.timeout_seconds),
            priority=kwargs.pop("priority", parent.priority),
            status="pending",
        )
        self.db.add(sub)
        await self.db.flush()
        return sub

    async def _get_or_raise(self, contract_id: uuid.UUID) -> TaskContract:
        contract = await self.get(contract_id)
        if contract is None:
            raise ValueError(f"Contract {contract_id} not found")
        return contract

    def _assert_transition(self, current: str, target: str):
        allowed = self.VALID_TRANSITIONS.get(current, [])
        if target not in allowed:
            raise ValueError(
                f"Cannot transition contract from '{current}' to '{target}'. "
                f"Allowed transitions: {allowed}"
            )

    def _validate_result(self, contract: TaskContract, result: dict) -> list[str]:
        errors = []
        schema = contract.output_schema or {}
        if schema and not isinstance(result, dict):
            errors.append("Result must be a dict when output_schema is defined")
            return errors
        for field, expected_type in schema.items():
            if field not in result:
                errors.append(f"Missing required field '{field}' in result")
                continue
            if expected_type == "string" and not isinstance(result[field], str):
                errors.append(f"Field '{field}' expected string, got {type(result[field]).__name__}")
            elif expected_type == "number" and not isinstance(result[field], (int, float)):
                errors.append(f"Field '{field}' expected number, got {type(result[field]).__name__}")
            elif expected_type == "boolean" and not isinstance(result[field], bool):
                errors.append(f"Field '{field}' expected boolean, got {type(result[field]).__name__}")
            elif expected_type == "array" and not isinstance(result[field], list):
                errors.append(f"Field '{field}' expected array, got {type(result[field]).__name__}")
            elif expected_type == "object" and not isinstance(result[field], dict):
                errors.append(f"Field '{field}' expected object, got {type(result[field]).__name__}")
        for criterion in (contract.acceptance_criteria or []):
            err = self._check_criterion(criterion, result)
            if err:
                errors.append(err)
        return errors

    def _check_criterion(self, criterion: dict, result: dict) -> str | None:
        field = criterion.get("field", "")
        operator = criterion.get("operator", "exists")
        expected = criterion.get("value")
        parts = field.split(".")
        value = result
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return f"Criterion field '{field}' not found in result"
        if value is None:
            return f"Criterion field '{field}' is null"
        if operator == "exists":
            return None
        if operator == "equals":
            if value != expected:
                return f"Criterion '{field}' expected {expected!r}, got {value!r}"
            return None
        if operator == "contains":
            if expected not in value:
                return f"Criterion '{field}' does not contain {expected!r}"
            return None
        if operator == "gte":
            if not (isinstance(value, (int, float)) and value >= expected):
                return f"Criterion '{field}' expected >= {expected}, got {value}"
            return None
        if operator == "lte":
            if not (isinstance(value, (int, float)) and value <= expected):
                return f"Criterion '{field}' expected <= {expected}, got {value}"
            return None
        return f"Unknown operator '{operator}'"
