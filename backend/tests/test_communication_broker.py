import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.contract.communication_broker import CommunicationBroker
from app.models.message import AgentMessage


@pytest.fixture
def mock_db():
    session = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def broker(mock_db):
    return CommunicationBroker(db_session=mock_db)


@pytest.fixture
def execution_id():
    return uuid.uuid4()


class TestCommunicationBroker:
    @pytest.mark.asyncio
    async def test_send_message(self, broker, mock_db, execution_id):
        msg = await broker.send_message(
            execution_id=execution_id,
            message_type="request",
            sender_id="agent-1",
            target_id="agent-2",
            subject="code_review",
            payload={"task": "review PR"},
        )

        mock_db.add.assert_called()
        mock_db.flush.assert_awaited()
        assert msg.sender_id == "agent-1"
        assert msg.target_id == "agent-2"
        assert msg.message_type == "request"
        assert msg.execution_id == execution_id

    @pytest.mark.asyncio
    async def test_send_response_triggers_event(self, broker, mock_db, execution_id):
        correlation_id = uuid.uuid4()
        event = asyncio.Event()
        broker._pending_responses[correlation_id] = event

        await broker.send_message(
            execution_id=execution_id,
            message_type="response",
            sender_id="agent-2",
            target_id="agent-1",
            subject="code_review",
            payload={"result": "approved"},
            correlation_id=correlation_id,
        )

        assert event.is_set()
        assert broker._responses[correlation_id] == {"result": "approved"}

    @pytest.mark.asyncio
    async def test_poll_messages(self, broker, mock_db, execution_id):
        msg = AgentMessage(
            id=uuid.uuid4(),
            execution_id=execution_id,
            message_type="request",
            sender_id="agent-1",
            target_id="agent-2",
            subject="hello",
            payload={},
        )
        scalars = MagicMock()
        scalars.scalars.return_value.all.return_value = [msg]
        mock_db.execute.return_value = scalars

        results = await broker.poll_messages(
            agent_id="agent-2", execution_id=execution_id
        )
        assert len(results) == 1
        assert results[0].subject == "hello"

    @pytest.mark.asyncio
    async def test_request_response_cycle(self, broker, mock_db, execution_id):
        async def fake_send(*args, **kwargs):
            msg = MagicMock(spec=AgentMessage)
            msg.id = uuid.uuid4()
            for k, v in {
                "execution_id": kwargs.get("execution_id"),
                "message_type": kwargs.get("message_type"),
                "sender_id": kwargs.get("sender_id"),
                "target_id": kwargs.get("target_id"),
                "correlation_id": kwargs.get("correlation_id"),
                "subject": kwargs.get("subject"),
                "payload": kwargs.get("payload"),
            }.items():
                setattr(msg, k, v)
            broker._responses[kwargs["correlation_id"]] = {"result": "done"}
            if kwargs["correlation_id"] in broker._pending_responses:
                broker._pending_responses[kwargs["correlation_id"]].set()
            return msg

        broker.send_message = fake_send

        response = await broker.request(
            execution_id=execution_id,
            sender_id="agent-1",
            target_id="agent-2",
            subject="execute",
            payload={"cmd": "test"},
            timeout=5,
        )
        assert response == {"result": "done"}

    @pytest.mark.asyncio
    async def test_request_timeout(self, broker, mock_db, execution_id):
        async def slow_send(*args, **kwargs):
            msg = MagicMock(spec=AgentMessage)
            msg.correlation_id = uuid.uuid4()
            return msg

        broker.send_message = slow_send

        with pytest.raises(TimeoutError, match="No response"):
            await broker.request(
                execution_id=execution_id,
                sender_id="agent-1",
                target_id="agent-2",
                subject="execute",
                payload={},
                timeout=0.01,
            )

    @pytest.mark.asyncio
    async def test_broadcast(self, broker, mock_db, execution_id):
        await broker.broadcast(
            execution_id=execution_id,
            sender_id="supervisor-1",
            subject="shutdown",
            payload={"reason": "maintenance"},
        )

        mock_db.add.assert_called_once()
        added = mock_db.add.call_args[0][0]
        assert added.message_type == "broadcast"
        assert added.target_id is None

    @pytest.mark.asyncio
    async def test_respond(self, broker, mock_db, execution_id):
        original = AgentMessage(
            id=uuid.uuid4(),
            execution_id=execution_id,
            message_type="request",
            sender_id="agent-1",
            target_id="agent-2",
            subject="status",
            payload={},
            correlation_id=uuid.uuid4(),
        )

        await broker.respond(
            execution_id=execution_id,
            sender_id="agent-2",
            original_msg=original,
            payload={"status": "ok"},
        )

        mock_db.add.assert_called()
        added = mock_db.add.call_args[0][0]
        assert added.message_type == "response"
        assert added.correlation_id == original.correlation_id
        assert added.target_id == "agent-1"

    @pytest.mark.asyncio
    async def test_register_handler(self, broker):
        async def handler(msg):
            return {"reply": "ok"}

        broker.register_handler("agent-1", "ping", handler)
        assert "agent-1" in broker._handlers
        assert broker._handlers["agent-1"]["ping"] is handler

    @pytest.mark.asyncio
    async def test_poll_messages_empty(self, broker, mock_db, execution_id):
        scalars = MagicMock()
        scalars.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = scalars

        results = await broker.poll_messages(
            agent_id="agent-99", execution_id=execution_id
        )
        assert results == []
