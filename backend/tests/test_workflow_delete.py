import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Delete

from app.main import app
from app.core.db import get_db
from app.core.redis import get_redis
from tests.test_api import MockResult, MockSession


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

    yield
    app.dependency_overrides.clear()


def test_delete_workflow_not_found():
    session = MockSession()
    app.dependency_overrides[get_db] = lambda: session
    client = TestClient(app)
    resp = client.delete(f"/api/workflows/{uuid.uuid4()}")
    assert resp.status_code == 404


def _table_of(stmt):
    """从 SQLAlchemy delete 语句提取表名。"""
    if isinstance(stmt, Delete):
        try:
            return stmt.table.name
        except Exception:
            return None
    return None


def test_delete_workflow_cascades_related_data():
    """删除项目时，该项目所有 executions 及关联表数据必须级联删除。"""
    workflow_id = uuid.uuid4()
    exec_id = uuid.uuid4()

    workflow = MagicMock(id=workflow_id)
    execution = MagicMock(id=exec_id, context={"project_path": "./generated_projects/fake_proj"})

    session = MockSession()
    calls: list = []

    async def _exec(stmt, *args, **kwargs):
        calls.append(stmt)
        if isinstance(stmt, Delete):
            return MockResult()
        if len(calls) == 1:  # select Workflow
            return MockResult([workflow])
        return MockResult([execution])  # select Execution

    session.execute = AsyncMock(side_effect=_exec)

    app.dependency_overrides[get_db] = lambda: session
    client = TestClient(app)

    resp = client.delete(f"/api/workflows/{workflow_id}")
    assert resp.status_code == 204

    delete_tables = [_table_of(c) for c in calls]
    delete_tables = [t for t in delete_tables if t]

    # workflow 和 execution 两个 select + 最终 db.delete(workflow)
    # 级联 delete 必须覆盖所有关联表
    expected = {
        "execution_logs",
        "evaluations",
        "task_contracts",
        "agent_messages",
        "execution_decisions",
        "node_executions",
        "artifacts",
        "executions",
        "blueprints",
    }
    assert expected.issubset(set(delete_tables)), (
        f"missing tables: {expected - set(delete_tables)}; got: {delete_tables}"
    )
