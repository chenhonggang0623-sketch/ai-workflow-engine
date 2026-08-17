import json
import logging
from uuid import UUID
from collections import defaultdict

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self._execution_connections: dict[UUID, set[WebSocket]] = defaultdict(set)
        self._agent_connections: dict[UUID, set[WebSocket]] = defaultdict(set)

    async def connect_execution(self, execution_id: UUID, ws: WebSocket):
        await ws.accept()
        self._execution_connections[execution_id].add(ws)
        logger.info("WebSocket connected for execution %s", execution_id)

    async def connect_agent_messages(self, execution_id: UUID, ws: WebSocket):
        await ws.accept()
        self._agent_connections[execution_id].add(ws)
        logger.info("WebSocket connected for agent messages %s", execution_id)

    def disconnect_execution(self, execution_id: UUID, ws: WebSocket):
        self._execution_connections[execution_id].discard(ws)
        if not self._execution_connections[execution_id]:
            del self._execution_connections[execution_id]

    def disconnect_agent_messages(self, execution_id: UUID, ws: WebSocket):
        self._agent_connections[execution_id].discard(ws)
        if not self._agent_connections[execution_id]:
            del self._agent_connections[execution_id]

    async def broadcast_execution(self, execution_id: UUID, message: dict):
        dead = set()
        for ws in self._execution_connections.get(execution_id, set()):
            try:
                await ws.send_json(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._execution_connections[execution_id].discard(ws)

    async def broadcast_agent_messages(self, execution_id: UUID, message: dict):
        dead = set()
        for ws in self._agent_connections.get(execution_id, set()):
            try:
                await ws.send_json(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._agent_connections[execution_id].discard(ws)


manager = ConnectionManager()


async def execution_ws(websocket: WebSocket, execution_id: UUID):
    await manager.connect_execution(execution_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            await manager.broadcast_execution(execution_id, msg)
    except WebSocketDisconnect:
        manager.disconnect_execution(execution_id, websocket)
    except Exception as e:
        logger.error("Execution WS error: %s", e)
        manager.disconnect_execution(execution_id, websocket)


async def agent_messages_ws(websocket: WebSocket, execution_id: UUID):
    await manager.connect_agent_messages(execution_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            await manager.broadcast_agent_messages(execution_id, msg)
    except WebSocketDisconnect:
        manager.disconnect_agent_messages(execution_id, websocket)
    except Exception as e:
        logger.error("Agent messages WS error: %s", e)
        manager.disconnect_agent_messages(execution_id, websocket)
