import asyncio
import inspect
import logging
import uuid
from collections import defaultdict
from typing import Callable, Coroutine

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import AgentMessage

logger = logging.getLogger(__name__)


class AgentCommClient:
    def __init__(self, agent_id: str, execution_id: uuid.UUID, db_session: AsyncSession):
        self._agent_id = agent_id
        self._execution_id = execution_id
        self._db = db_session
        self._handlers: dict[str, list[Callable]] = defaultdict(list)
        self._running = False

    async def send(self, target_id: str, subject: str, payload: dict) -> None:
        msg = AgentMessage(
            execution_id=self._execution_id,
            message_type="send",
            sender_id=self._agent_id,
            target_id=target_id,
            subject=subject,
            payload=payload,
        )
        self._db.add(msg)
        await self._db.flush()
        logger.debug(
            "Agent %s sent message to %s: %s", self._agent_id, target_id, subject,
        )

    async def request(
        self, target_id: str, subject: str, payload: dict, timeout: int = 60
    ) -> dict:
        correlation_id = uuid.uuid4()
        msg = AgentMessage(
            execution_id=self._execution_id,
            message_type="request",
            sender_id=self._agent_id,
            target_id=target_id,
            correlation_id=correlation_id,
            subject=subject,
            payload=payload,
        )
        self._db.add(msg)
        await self._db.flush()

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            result = await self._db.execute(
                select(AgentMessage).where(
                    AgentMessage.correlation_id == correlation_id,
                    AgentMessage.message_type == "response",
                    AgentMessage.target_id == self._agent_id,
                )
            )
            response = result.scalar_one_or_none()
            if response:
                return response.payload or {}
            await asyncio.sleep(0.5)

        raise TimeoutError(
            f"Request to {target_id} timed out after {timeout}s"
        )

    async def broadcast(self, subject: str, payload: dict) -> None:
        msg = AgentMessage(
            execution_id=self._execution_id,
            message_type="broadcast",
            sender_id=self._agent_id,
            target_id="*",
            subject=subject,
            payload=payload,
        )
        self._db.add(msg)
        await self._db.flush()
        logger.debug(
            "Agent %s broadcast: %s", self._agent_id, subject,
        )

    async def reply(
        self, target_id: str, correlation_id: uuid.UUID, payload: dict
    ) -> None:
        msg = AgentMessage(
            execution_id=self._execution_id,
            message_type="response",
            sender_id=self._agent_id,
            target_id=target_id,
            correlation_id=correlation_id,
            subject="response",
            payload=payload,
        )
        self._db.add(msg)
        await self._db.flush()

    def on(self, subject: str, handler: Callable) -> None:
        self._handlers[subject].append(handler)

    async def listen(self) -> None:
        self._running = True
        logger.info("Agent %s started listening", self._agent_id)

        while self._running:
            result = await self._db.execute(
                select(AgentMessage).where(
                    AgentMessage.target_id.in_([self._agent_id, "*"]),
                    AgentMessage.message_type.in_(["send", "request", "broadcast"]),
                ).order_by(AgentMessage.created_at).limit(10)
            )
            messages = result.scalars().all()

            for msg in messages:
                handlers = self._handlers.get(msg.subject, []) + self._handlers.get("*", [])
                for handler in handlers:
                    try:
                        if inspect.iscoroutinefunction(handler):
                            await handler(msg)
                        else:
                            handler(msg)
                    except Exception as e:
                        logger.error(
                            "Handler error for subject %s: %s", msg.subject, e,
                        )

            await asyncio.sleep(1)

    def stop(self) -> None:
        self._running = False
