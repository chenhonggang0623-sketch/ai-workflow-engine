import asyncio
import uuid
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import AgentMessage


class CommunicationBroker:
    def __init__(self, db_session: AsyncSession, redis_client: Any = None):
        self.db = db_session
        self.redis = redis_client
        self._handlers: dict[str, dict[str, Callable]] = {}
        self._pending_responses: dict[uuid.UUID, asyncio.Event] = {}
        self._responses: dict[uuid.UUID, dict] = {}

    async def send_message(
        self,
        execution_id: uuid.UUID,
        message_type: str,
        sender_id: str,
        target_id: str | None,
        subject: str,
        payload: dict,
        correlation_id: uuid.UUID | None = None,
        priority: int = 0,
    ) -> AgentMessage:
        msg = AgentMessage(
            id=uuid.uuid4(),
            execution_id=execution_id,
            message_type=message_type,
            sender_id=sender_id,
            target_id=target_id,
            correlation_id=correlation_id,
            subject=subject,
            payload=payload,
            priority=priority,
        )
        self.db.add(msg)
        await self.db.flush()

        if message_type == "response" and correlation_id:
            self._responses[correlation_id] = payload
            if correlation_id in self._pending_responses:
                self._pending_responses[correlation_id].set()

        return msg

    async def poll_messages(
        self,
        agent_id: str,
        execution_id: uuid.UUID,
        limit: int = 50,
    ) -> list[AgentMessage]:
        stmt = (
            select(AgentMessage)
            .where(
                AgentMessage.target_id == agent_id,
                AgentMessage.execution_id == execution_id,
            )
            .order_by(AgentMessage.priority.desc(), AgentMessage.created_at.asc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def request(
        self,
        execution_id: uuid.UUID,
        sender_id: str,
        target_id: str,
        subject: str,
        payload: dict,
        timeout: int = 60,
    ) -> dict:
        correlation_id = uuid.uuid4()
        event = asyncio.Event()
        self._pending_responses[correlation_id] = event

        await self.send_message(
            execution_id=execution_id,
            message_type="request",
            sender_id=sender_id,
            target_id=target_id,
            subject=subject,
            payload=payload,
            correlation_id=correlation_id,
        )

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_responses.pop(correlation_id, None)
            self._responses.pop(correlation_id, None)
            raise TimeoutError(
                f"No response from {target_id} within {timeout}s (correlation_id={correlation_id})"
            )

        response = self._responses.pop(correlation_id, {})
        self._pending_responses.pop(correlation_id, None)
        return response

    async def broadcast(
        self,
        execution_id: uuid.UUID,
        sender_id: str,
        subject: str,
        payload: dict,
    ) -> None:
        msg = AgentMessage(
            id=uuid.uuid4(),
            execution_id=execution_id,
            message_type="broadcast",
            sender_id=sender_id,
            target_id=None,
            subject=subject,
            payload=payload,
        )
        self.db.add(msg)
        await self.db.flush()

    async def respond(
        self,
        execution_id: uuid.UUID,
        sender_id: str,
        original_msg: AgentMessage,
        payload: dict,
    ) -> None:
        await self.send_message(
            execution_id=execution_id,
            message_type="response",
            sender_id=sender_id,
            target_id=original_msg.sender_id,
            subject=original_msg.subject,
            payload=payload,
            correlation_id=original_msg.correlation_id,
        )

    def register_handler(
        self, agent_id: str, subject: str, handler: Callable
    ) -> None:
        if agent_id not in self._handlers:
            self._handlers[agent_id] = {}
        self._handlers[agent_id][subject] = handler
