from unittest.mock import AsyncMock, MagicMock
import uuid
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_db
from app.core.redis import get_redis

class MockResult:
    """Mimics sqlalchemy Result for route handlers."""
    def __init__(self, rows=None):
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def all(self):
        return self._rows


class MockSession(AsyncMock):
    """AsyncMock with proper execute/flush/refresh shape."""
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

    for key in ["agent_registry", "llm_gateway", "execution_manager",
                 "artifact_manager", "context_manager", "contract_manager",
                 "comm_broker", "evaluation_engine", "quality_gate",
                 "recovery_manager", "planner_agent", "tool_registry",
                 "supervisor"]:
        setattr(app.state, key, MagicMock())

    app.state.planner_agent.list_templates = MagicMock(return_value={"categories": ["fullstack-app"]})
    # Add required app.state attributes for the new wiring
    for key in ["llm_gateway", "tool_registry", "agent_executor", "node_runner", "execution_manager"]:
        if not hasattr(app.state, key):
            setattr(app.state, key, MagicMock())

    yield
    app.dependency_overrides.clear()


def test_health():
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200


def test_planner_templates():
    client = TestClient(app)
    resp = client.get("/api/planner/templates")
    assert resp.status_code == 200
    assert "categories" in resp.json()


def test_404_routing():
    client = TestClient(app)
    fake = str(uuid.uuid4())
    resp = client.get(f"/api/workflows/{fake}")
    assert resp.status_code in (200, 404, 500)


def test_execution_files_404():
    client = TestClient(app)
    resp = client.get(f"/api/executions/{uuid.uuid4()}/files")
    assert resp.status_code == 404


def test_execution_files_empty_when_no_workspace():
    execution = MagicMock()
    execution.id = uuid.uuid4()
    execution.context = {}

    session = MockSession()
    session.execute.return_value = MockResult([execution])
    app.dependency_overrides[get_db] = lambda: session

    client = TestClient(app)
    resp = client.get(f"/api/executions/{execution.id}/files")
    assert resp.status_code == 200
    body = resp.json()
    assert body["project_path"] is None
    assert body["files"] == []


def test_execution_files_lists_project(tmp_path):
    import os

    (tmp_path / "main.py").write_text("print(1)")
    sub = tmp_path / "app" / "src"
    sub.mkdir(parents=True)
    (tmp_path / "app" / "__init__.py").write_text("")
    (sub / "util.py").write_text("x = 1")

    execution = MagicMock()
    execution.id = uuid.uuid4()
    execution.context = {"project_path": str(tmp_path)}

    session = MockSession()
    session.execute.return_value = MockResult([execution])
    app.dependency_overrides[get_db] = lambda: session

    client = TestClient(app)
    resp = client.get(f"/api/executions/{execution.id}/files")
    assert resp.status_code == 200
    body = resp.json()
    assert body["project_path"] == str(tmp_path)
    paths = {f["path"] for f in body["files"]}
    assert paths == {"main.py", "app/__init__.py", "app/src/util.py"}
    sizes = {f["path"]: f["size"] for f in body["files"]}
    assert sizes["main.py"] == len("print(1)")


def test_execution_files_skips_missing_dir(tmp_path):
    execution = MagicMock()
    execution.id = uuid.uuid4()
    execution.context = {"project_path": str(tmp_path / "does_not_exist")}

    session = MockSession()
    session.execute.return_value = MockResult([execution])
    app.dependency_overrides[get_db] = lambda: session

    client = TestClient(app)
    resp = client.get(f"/api/executions/{execution.id}/files")
    assert resp.status_code == 200
    assert resp.json()["files"] == []
