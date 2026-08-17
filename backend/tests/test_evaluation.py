import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.supervisor.evaluation import EvaluationEngine, EvaluationResult


@pytest.fixture
def mock_db():
    session = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def mock_llm():
    gw = AsyncMock()

    async def chat(**kwargs):
        return {
            "content": json.dumps({"score": 0.85, "issues": [], "confidence": 0.9}),
            "tool_calls": [],
            "usage": {},
        }
    gw.chat = chat
    return gw


@pytest.fixture
def engine(mock_db):
    eng = EvaluationEngine(db_session=mock_db)
    eng._update_agent_performance = AsyncMock()
    return eng


@pytest.fixture
def engine_with_llm(mock_db, mock_llm):
    eng = EvaluationEngine(db_session=mock_db, llm_gateway=mock_llm)
    eng._update_agent_performance = AsyncMock()
    return eng


class TestEvaluationEngine:
    @pytest.mark.asyncio
    async def test_evaluate_no_schema(self, engine, mock_db):
        result = await engine.evaluate(
            agent_id="agent-1",
            node_execution_id=uuid.uuid4(),
            agent_output={"code": "print('hello')"},
        )
        assert result.passed is True
        assert result.scores["completeness"] == 1.0
        assert 0.0 <= result.weighted_score <= 1.0

    @pytest.mark.asyncio
    async def test_evaluate_with_schema_all_present(self, engine, mock_db):
        schema = {"code": "string", "tests": "array"}
        result = await engine.evaluate(
            agent_id="agent-1",
            node_execution_id=uuid.uuid4(),
            agent_output={"code": "print('hi')", "tests": ["test_hi"]},
            expected_schema=schema,
        )
        assert result.passed is True
        assert result.scores["completeness"] == 1.0

    @pytest.mark.asyncio
    async def test_evaluate_missing_fields(self, engine, mock_db):
        schema = {"code": "string", "tests": "array", "docs": "string"}
        result = await engine.evaluate(
            agent_id="agent-1",
            node_execution_id=uuid.uuid4(),
            agent_output={"code": "print('hi')"},
            expected_schema=schema,
        )
        assert result.scores["completeness"] < 1.0
        assert any("Missing" in w for w in result.weaknesses)

    @pytest.mark.asyncio
    async def test_evaluate_with_llm(self, engine_with_llm, mock_db):
        result = await engine_with_llm.evaluate(
            agent_id="agent-1",
            node_execution_id=uuid.uuid4(),
            agent_output={"code": "print('hello')", "tests": ["ok"]},
            expected_schema={"code": "string"},
            criteria=["code is valid Python", "tests exist"],
        )
        assert result.passed is True
        assert result.confidence is not None

    @pytest.mark.asyncio
    async def test_evaluate_contract(self, engine, mock_db):
        contract_id = uuid.uuid4()
        mock_contract = MagicMock()
        mock_contract.id = contract_id
        mock_contract.executor_id = "agent-1"
        mock_contract.output_schema = {"result": "string"}
        mock_contract.acceptance_criteria = []

        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none = MagicMock(return_value=mock_contract)

        async def execute_side(*args, **kwargs):
            return scalar_result
        engine.db.execute = AsyncMock(side_effect=execute_side)

        result = await engine.evaluate_contract(
            contract_id=contract_id,
            result={"result": "success"},
        )
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_get_agent_performance_empty(self, engine, mock_db):
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none = MagicMock(return_value=None)

        async def execute_side(*args, **kwargs):
            return scalar_result
        engine.db.execute = AsyncMock(side_effect=execute_side)

        perf = await engine.get_agent_performance("agent-unknown")
        assert perf["evaluation_count"] == 0

    @pytest.mark.asyncio
    async def test_get_agent_performance_with_data(self, engine, mock_db):
        perf = MagicMock()
        perf.agent_id = "agent-1"
        perf.evaluation_count = 5
        perf.average_scores = {"completeness": 0.9, "correctness": 0.8, "efficiency": 0.7}
        perf.score_trend = "improving"
        perf.reliability = 0.95
        perf.weakness_patterns = [{"pattern": "verbose output", "count": 2}]
        perf.last_evaluation_at = None
        scalar_result = MagicMock()
        scalar_result.scalar_one_or_none = MagicMock(return_value=perf)

        async def execute_side(*args, **kwargs):
            return scalar_result
        engine.db.execute = AsyncMock(side_effect=execute_side)

        result = await engine.get_agent_performance("agent-1")
        assert result["evaluation_count"] == 5
        assert result["reliability"] == 0.95

    @pytest.mark.asyncio
    async def test_calibrate(self, engine, mock_db):
        engine.calibrate(
            {"agent_id": "agent-1", "completeness": 0.9, "correctness": 0.8},
            {"completeness": 0.7, "correctness": 0.6},
        )
        assert "agent-1" in engine._bias_adjustment
        assert engine._bias_adjustment["agent-1"] > 0

    def test_score_completeness_no_schema(self, engine):
        result = engine._score_completeness({"a": 1}, None)
        assert result["score"] == 1.0

    def test_score_completeness_not_dict(self, engine):
        result = engine._score_completeness("not_a_dict", {"a": "string"})
        assert result["score"] == 0.0

    def test_score_efficiency_concise(self, engine):
        result = engine._score_efficiency({"a": "short"})
        assert result["score"] == 1.0

    def test_score_efficiency_verbose(self, engine):
        result = engine._score_efficiency({"data": "x" * 3000})
        assert result["score"] < 1.0


class TestEvaluationResult:
    def test_defaults(self):
        r = EvaluationResult(agent_id="a", scores={}, weighted_score=0.0, confidence=None, summary="")
        assert r.passed is False
        assert r.severity == "info"
        assert r.strengths == []
