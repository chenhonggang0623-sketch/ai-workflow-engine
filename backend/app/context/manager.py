import json
from copy import deepcopy
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.engine.types import InputMapping, OutputMapping
from app.models.workflow import Execution


def _resolve_path(data: dict, path: str) -> tuple[dict, str]:
    keys = path.strip("$.").split(".")
    current = data
    for key in keys[:-1]:
        if key not in current or not isinstance(current[key], dict):
            current[key] = {}
        current = current[key]
    return current, keys[-1]


def _get_jsonpath(data: dict, path: str) -> Any:
    keys = path.strip("$.").split(".")
    current = data
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return None
    return current


REDIS_KEY_PREFIX = "ctx"


class ContextManager:
    def __init__(self, db_session: AsyncSession, redis_client):
        self.db = db_session
        self.redis = redis_client

    def _redis_key(self, execution_id: UUID) -> str:
        return f"{REDIS_KEY_PREFIX}:{execution_id}"

    async def init(self, execution_id: UUID, initial_data: dict) -> None:
        data = deepcopy(initial_data)
        await self.redis.set(self._redis_key(execution_id), json.dumps(data))

    async def get(self, execution_id: UUID) -> dict:
        raw = await self.redis.get(self._redis_key(execution_id))
        if raw is None:
            result = await self.db.execute(
                select(Execution).where(Execution.id == execution_id)
            )
            execution = result.scalar_one_or_none()
            if execution is None:
                return {}
            data = deepcopy(execution.context) if execution.context else {}
            await self.redis.set(self._redis_key(execution_id), json.dumps(data))
            return data
        return json.loads(raw)

    async def set_value(self, execution_id: UUID, path: str, value: Any) -> None:
        data = await self.get(execution_id)
        parent, last_key = _resolve_path(data, path)
        parent[last_key] = deepcopy(value)
        await self.redis.set(self._redis_key(execution_id), json.dumps(data))

    async def get_value(self, execution_id: UUID, path: str) -> Any:
        data = await self.get(execution_id)
        return _get_jsonpath(data, path)

    async def snapshot(self, execution_id: UUID) -> None:
        data = await self.get(execution_id)
        result = await self.db.execute(
            select(Execution).where(Execution.id == execution_id)
        )
        execution = result.scalar_one_or_none()
        if execution:
            execution.context = data
            await self.db.flush()

    async def apply_input_mapping(
        self, execution_id: UUID, mappings: list[InputMapping]
    ) -> dict:
        data = await self.get(execution_id)
        result = {}
        for mapping in mappings:
            value = _get_jsonpath(data, mapping.source)
            result[mapping.target] = value
        return result

    async def apply_output_mapping(
        self, execution_id: UUID, mappings: list[OutputMapping], output: dict
    ) -> None:
        data = await self.get(execution_id)
        for mapping in mappings:
            value = deepcopy(output.get(mapping.source))
            parent, last_key = _resolve_path(data, mapping.target)
            parent[last_key] = value
        await self.redis.set(self._redis_key(execution_id), json.dumps(data))

    async def commit(self, execution_id: UUID) -> None:
        await self.snapshot(execution_id)
