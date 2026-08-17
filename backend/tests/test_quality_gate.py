import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.supervisor.quality_gate import QualityGate
from app.supervisor.evaluation import EvaluationEngine


@pytest.fixture
def mock_db():
    session = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def engine(mock_db):
    return EvaluationEngine(db_session=mock_db)


@pytest.fixture
def gate(engine):
    return QualityGate(engine)


class TestQualityGate:
    @pytest.mark.asyncio
    async def test_schema_validate_passed(self, gate):
        result = await gate.check(
            "schema_validate",
            {"schema": {"name": "string", "count": "number"}},
            {"name": "test", "count": 42},
            {},
        )
        assert result["passed"] is True
        assert result["score"] == 1.0

    @pytest.mark.asyncio
    async def test_schema_validate_failed(self, gate):
        result = await gate.check(
            "schema_validate",
            {"schema": {"name": "string"}},
            {"wrong_key": "value"},
            {},
        )
        assert result["passed"] is False
        assert result["score"] == 0.0

    @pytest.mark.asyncio
    async def test_schema_validate_no_schema(self, gate):
        result = await gate.check("schema_validate", {}, {"a": 1}, {})
        assert result["passed"] is True

    @pytest.mark.asyncio
    async def test_llm_review_no_llm_fallback(self, gate):
        result = await gate.check("llm_review", {}, {"code": "ok"}, {})
        assert result["passed"] is True
        assert "bypassed" in result["feedback"]

    @pytest.mark.asyncio
    async def test_llm_review_with_llm(self, gate, engine):
        mock_llm = AsyncMock()

        async def chat(**kwargs):
            return {
                "content": json.dumps({"score": 0.9, "issues": [], "verdict": "pass"}),
                "tool_calls": [],
                "usage": {},
            }
        mock_llm.chat = chat
        engine._llm = mock_llm

        result = await gate.check(
            "llm_review",
            {"criteria": ["quality"], "min_score": 0.7},
            {"code": "print('hello')"},
            {},
        )
        assert result["passed"] is True

    @pytest.mark.asyncio
    async def test_llm_review_below_min_score(self, gate, engine):
        mock_llm = AsyncMock()

        async def chat(**kwargs):
            return {
                "content": json.dumps({"score": 0.4, "issues": ["poor quality"], "verdict": "fail"}),
                "tool_calls": [],
                "usage": {},
            }
        mock_llm.chat = chat
        engine._llm = mock_llm

        result = await gate.check(
            "llm_review",
            {"criteria": ["quality"], "min_score": 0.7},
            {"code": "bad"},
            {},
        )
        assert result["passed"] is False
        assert result["score"] == 0.4

    @pytest.mark.asyncio
    async def test_human_approve(self, gate):
        result = await gate.check("human_approve", {}, {"data": "x"}, {})
        assert result["passed"] is False
        assert result.get("requires_approval") is True

    @pytest.mark.asyncio
    async def test_unknown_gate_type(self, gate):
        result = await gate.check("nonexistent", {}, {}, {})
        assert result["passed"] is False

    @pytest.mark.asyncio
    async def test_check_contract_passed(self, gate):
        contract = MagicMock()
        contract.output_schema = {"result": "string"}
        contract.acceptance_criteria = []

        result = await gate.check_contract(contract, {"result": "ok"})
        assert result["passed"] is True
        assert result["score"] == 1.0

    @pytest.mark.asyncio
    async def test_check_contract_schema_fail(self, gate):
        contract = MagicMock()
        contract.output_schema = {"required_field": "string"}
        contract.acceptance_criteria = []

        result = await gate.check_contract(contract, {"wrong": "data"})
        assert result["passed"] is False

    @pytest.mark.asyncio
    async def test_check_contract_criteria_fail(self, gate, engine):
        mock_llm = AsyncMock()

        async def chat(**kwargs):
            return {
                "content": json.dumps({"score": 0.3, "issues": ["missing criteria"], "verdict": "fail"}),
                "tool_calls": [],
                "usage": {},
            }
        mock_llm.chat = chat
        engine._llm = mock_llm

        contract = MagicMock()
        contract.output_schema = {}
        contract.acceptance_criteria = [{"field": "quality", "operator": "gte", "value": 0.8}]

        result = await gate.check_contract(contract, {"quality": 0.5})
        assert result["passed"] is False
