from unittest.mock import AsyncMock, MagicMock
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_db
from app.core.redis import get_redis


class MockResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def all(self):
        return self._rows


class MockSession(AsyncMock):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.execute.return_value = MockResult()
        self.flush = AsyncMock()
        self.refresh = AsyncMock()
        self.add = MagicMock()
        self.delete = AsyncMock()
        self.get = AsyncMock(return_value=None)
        self.commit = AsyncMock()


@pytest.fixture(autouse=True)
def mock_deps():
    session = MockSession()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_redis] = lambda: AsyncMock()
    for key in ["llm_gateway", "planner_agent"]:
        setattr(app.state, key, MagicMock())

    from app.core import app_config as ac
    ac.config_store._overrides = {}
    yield
    ac.config_store._overrides = {}
    app.dependency_overrides.clear()


def test_get_config_masks_api_key():
    from app.core.app_config import config_store
    config_store._overrides = {
        "openai_api_key": "sk-live-abcdef123456",
        "openai_base_url": "https://api.deepseek.com/v1",
        "agent_default_provider": "claude_cli",
    }
    client = TestClient(app)
    resp = client.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["has_openai_api_key"] is True
    assert "abcdef" not in body["openai_api_key"]
    assert "*" in body["openai_api_key"]
    assert body["agent_default_provider"] == "claude_cli"
    assert body["openai_base_url"].startswith("https")


def test_update_config_persists_and_placeholder_dropped():
    from app.core.app_config import config_store
    client = TestClient(app)
    resp = client.put(
        "/api/config",
        json={
            "openai_api_key": "sk-your-key-here",
            "openai_base_url": "https://api.moonshot.cn/v1",
            "default_llm_model": "kimi-k2",
            "agent_default_provider": "claude_cli",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["openai_base_url"] == "https://api.moonshot.cn/v1"
    assert "openai_api_key" not in body["saved_keys"]
    assert "openai_base_url" in body["saved_keys"]
    assert "claude_cli" == body["agent_default_provider"]


def test_test_llm_ok():
    from app.agent.llm_gateway import LLMGateway
    reply = {
        "content": "pong",
        "tool_calls": [],
        "usage": {"prompt_tokens": 3, "completion_tokens": 1},
    }
    async def fake_chat(*args, **kwargs):
        return reply

    gateway = LLMGateway()
    gateway.chat = fake_chat
    module = "app.api.routes.config"
    import sys
    sys.modules[module].LLMGateway = lambda: gateway
    client = TestClient(app)
    resp = client.post(
        "/api/config/test-llm",
        json={
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "sk-test",
            "model": "deepseek-chat",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["reply"] == "pong"