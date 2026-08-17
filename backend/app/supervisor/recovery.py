import asyncio
import logging
import uuid

from app.contract.contract_manager import ContractManager
from app.agent.registry import AgentRegistry

logger = logging.getLogger(__name__)

BACKOFF_DELAYS = [5, 10, 20]


class RecoveryManager:
    def __init__(self, contract_manager: ContractManager, agent_registry: AgentRegistry):
        self._cm = contract_manager
        self._registry = agent_registry
        self._retry_counts: dict[uuid.UUID, int] = {}

    async def handle_failure(self, contract_id: uuid.UUID, error: str, strategy: str = "auto") -> dict:
        contract = await self._cm.get(contract_id)
        if not contract:
            return {"action": "pause", "detail": f"Contract {contract_id} not found"}

        await self._cm.fail(contract_id, error)

        if strategy == "auto":
            strategy = await self._decide_strategy(contract, error)

        if strategy == "retry":
            return await self._do_retry(contract_id)
        elif strategy == "replace":
            alt = await self._find_alternative(contract.executor_id)
            if alt:
                return await self._do_replace(contract_id, alt)
            return await self._fallback_to_pause(contract_id, f"No alternative for {contract.executor_id}")
        elif strategy == "skip":
            return {"action": "skip", "detail": f"Skipped contract {contract_id}"}
        elif strategy == "modify_workflow":
            return {"action": "modify_workflow", "detail": "Delegated to Planner"}
        else:
            return {"action": "pause", "detail": f"Unknown strategy '{strategy}', pausing"}

    async def retry(self, contract_id: uuid.UUID) -> dict:
        return await self._do_retry(contract_id)

    async def replace_agent(self, contract_id: uuid.UUID, new_agent_id: str) -> dict:
        return await self._do_replace(contract_id, new_agent_id)

    async def _do_retry(self, contract_id: uuid.UUID) -> dict:
        count = self._retry_counts.get(contract_id, 0)
        if count >= len(BACKOFF_DELAYS):
            return {"action": "pause", "detail": "Max retries exhausted"}

        delay = BACKOFF_DELAYS[count]
        self._retry_counts[contract_id] = count + 1

        logger.info("Retrying contract %s in %ds (attempt %d)", contract_id, delay, count + 1)
        await asyncio.sleep(delay)

        contract = await self._cm.get(contract_id)
        if not contract:
            return {"action": "pause", "detail": "Contract vanished during retry wait"}

        contract.status = "pending"
        contract.result = None
        self._cm.db.add(contract)
        await self._cm.db.flush()

        return {"action": "retry", "detail": f"Re-executing contract {contract_id} (attempt {count + 1})", "delay": delay}

    async def _do_replace(self, contract_id: uuid.UUID, new_agent_id: str) -> dict:
        contract = await self._cm.get(contract_id)
        if contract:
            contract.executor_id = new_agent_id
            contract.status = "pending"
            contract.result = None
            self._cm.db.add(contract)
            await self._cm.db.flush()

        return {"action": "replace", "detail": f"Replaced with agent '{new_agent_id}'"}

    async def _decide_strategy(self, contract, error: str) -> str:
        count = self._retry_counts.get(contract.id, 0)
        if count < len(BACKOFF_DELAYS):
            return "retry"
        alt = await self._find_alternative(contract.executor_id)
        if alt:
            return "replace"
        if "skip" in error.lower():
            return "skip"
        return "pause"

    async def _find_alternative(self, agent_id: str) -> str | None:
        try:
            agents = await self._registry.list(status="active")
            candidates = [a["id"] for a in agents if a["id"] != agent_id]
            return candidates[0] if candidates else None
        except Exception as e:
            logger.warning("Failed to find alternative for %s: %s", agent_id, e)
            return None

    async def _fallback_to_pause(self, contract_id: uuid.UUID, reason: str) -> dict:
        return {"action": "pause", "detail": reason}
