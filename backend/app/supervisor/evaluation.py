import json
import logging
import uuid
from datetime import UTC, datetime
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evaluation import Evaluation, AgentPerformance

logger = logging.getLogger(__name__)

WEIGHTS = {"completeness": 0.25, "correctness": 0.40, "efficiency": 0.35}


@dataclass
class EvaluationResult:
    agent_id: str
    scores: dict[str, float]
    weighted_score: float
    confidence: float | None
    summary: str
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    passed: bool = False
    severity: str = "info"


class EvaluationEngine:
    def __init__(self, db_session: AsyncSession, llm_gateway=None):
        self.db = db_session
        self._llm = llm_gateway
        self._bias_adjustment: dict[str, float] = {}

    async def evaluate(
        self,
        agent_id: str,
        node_execution_id: uuid.UUID,
        agent_output: dict,
        expected_schema: dict | None = None,
        criteria: list[str] | None = None,
    ) -> EvaluationResult:
        scores = {}
        details = {}

        completeness = self._score_completeness(agent_output, expected_schema)
        scores["completeness"] = completeness["score"]
        details["completeness"] = completeness

        correctness = await self._score_correctness(agent_output, criteria)
        scores["correctness"] = correctness["score"]
        details["correctness"] = correctness

        efficiency = self._score_efficiency(agent_output)
        scores["efficiency"] = efficiency["score"]
        details["efficiency"] = efficiency

        weighted = sum(
            scores.get(dim, 0.0) * WEIGHTS.get(dim, 0.0) for dim in WEIGHTS
        )
        weighted = max(0.0, min(1.0, weighted))

        bias = self._bias_adjustment.get(agent_id, 0.0)
        adjusted = max(0.0, min(1.0, weighted + bias))

        passed = adjusted >= 0.6
        severity = "critical" if adjusted < 0.3 else "warning" if adjusted < 0.6 else "info"

        strengths = [
            f"{dim}: {details[dim].get('note', '')}"
            for dim in WEIGHTS
            if scores.get(dim, 0) >= 0.8 and details[dim].get("note")
        ]
        weaknesses = [
            f"{dim}: {details[dim].get('issue', '')}"
            for dim in WEIGHTS
            if scores.get(dim, 0) < 0.6 and details[dim].get("issue")
        ]
        suggestions = []
        for w in weaknesses:
            suggestions.append(f"Improve {w}")

        result = EvaluationResult(
            agent_id=agent_id,
            scores=scores,
            weighted_score=adjusted,
            confidence=correctness.get("confidence"),
            summary=f"Evaluation: completeness={scores['completeness']:.2f}, "
                    f"correctness={scores['correctness']:.2f}, "
                    f"efficiency={scores['efficiency']:.2f}",
            strengths=strengths,
            weaknesses=weaknesses,
            suggestions=suggestions,
            passed=passed,
            severity=severity,
        )

        await self._persist_evaluation(
            node_execution_id=node_execution_id,
            agent_id=agent_id,
            result=result,
        )

        return result

    async def evaluate_contract(
        self, contract_id: uuid.UUID, result: dict
    ) -> EvaluationResult:
        from app.models.contract import TaskContract

        stmt = select(TaskContract).where(TaskContract.id == contract_id)
        row = await self.db.execute(stmt)
        contract = row.scalar_one_or_none()
        if not contract:
            raise ValueError(f"Contract {contract_id} not found")

        return await self.evaluate(
            agent_id=contract.executor_id,
            node_execution_id=uuid.uuid4(),
            agent_output=result,
            expected_schema=contract.output_schema,
            criteria=contract.acceptance_criteria,
        )

    async def get_agent_performance(self, agent_id: str) -> dict:
        stmt = select(AgentPerformance).where(AgentPerformance.agent_id == agent_id)
        row = await self.db.execute(stmt)
        perf = row.scalar_one_or_none()
        if not perf:
            return {"agent_id": agent_id, "evaluation_count": 0}

        return {
            "agent_id": perf.agent_id,
            "evaluation_count": perf.evaluation_count,
            "average_scores": perf.average_scores or {},
            "score_trend": perf.score_trend or "stable",
            "reliability": perf.reliability or 1.0,
            "weakness_patterns": perf.weakness_patterns or [],
            "last_evaluation_at": perf.last_evaluation_at.isoformat() if perf.last_evaluation_at else None,
        }

    def calibrate(self, human_feedback: dict, auto_eval: dict) -> None:
        for dim in WEIGHTS:
            h = human_feedback.get(dim)
            a = auto_eval.get(dim)
            if h is not None and a is not None:
                diff = h - a
                agent_id = human_feedback.get("agent_id", "_global")
                if agent_id not in self._bias_adjustment:
                    self._bias_adjustment[agent_id] = 0.0
                self._bias_adjustment[agent_id] += diff * 0.1

    def _score_completeness(
        self, output: dict, schema: dict | None
    ) -> dict:
        if not schema:
            return {"score": 1.0, "note": "No schema to validate"}

        if not isinstance(output, dict):
            return {"score": 0.0, "issue": "Output is not a dict"}

        required = [k for k, v in schema.items() if v != "optional"]
        if not required:
            required = list(schema.keys())

        missing = [f for f in required if f not in output]
        if missing:
            return {
                "score": max(0.0, 1.0 - len(missing) / max(len(required), 1)),
                "issue": f"Missing fields: {', '.join(missing)}",
            }

        return {"score": 1.0, "note": "All required fields present"}

    async def _score_correctness(
        self, output: dict, criteria: list[str] | None
    ) -> dict:
        if self._llm is None or not criteria:
            return {"score": 1.0, "confidence": None, "note": "No LLM review (fallback)"}

        try:
            prompt = (
                "Evaluate the correctness of this output based on these criteria:\n"
                f"Criteria: {json.dumps(criteria)}\n"
                f"Output: {json.dumps(output)}\n\n"
                "Return a JSON object with: score (0.0-1.0), issues (list), confidence (0.0-1.0)"
            )
            messages = [
                {"role": "system", "content": "You are an evaluation assistant. Return only valid JSON."},
                {"role": "user", "content": prompt},
            ]
            response = await self._llm.chat(
                model_config={"model": "gpt-4o-mini", "temperature": 0.3},
                messages=messages,
            )
            content = response.get("content", "")
            parsed = json.loads(content)
            score = max(0.0, min(1.0, float(parsed.get("score", 1.0))))
            confidence = float(parsed.get("confidence", 0.8))
            issues = parsed.get("issues", [])
            return {
                "score": score,
                "confidence": confidence,
                "issue": issues[0] if issues else None,
                "note": "LLM review completed" if score >= 0.6 else "LLM found issues",
            }
        except Exception as e:
            logger.warning("LLM correctness review failed: %s", e)
            return {"score": 1.0, "confidence": None, "note": "LLM review unavailable (fallback)"}

    def _score_efficiency(self, output: dict) -> dict:
        if not isinstance(output, dict):
            return {"score": 0.5, "issue": "Output is not structured"}

        raw = json.dumps(output, default=str)
        length = len(raw)

        if length < 100:
            return {"score": 1.0, "note": "Concise output"}
        if length < 2000:
            return {"score": 0.8, "note": "Reasonable size"}
        if length < 10000:
            return {"score": 0.5, "note": "Somewhat verbose"}
        return {"score": 0.3, "issue": "Very large output, consider summarizing"}

    async def _persist_evaluation(
        self,
        node_execution_id: uuid.UUID,
        agent_id: str,
        result: EvaluationResult,
    ) -> Evaluation:
        eval_record = Evaluation(
            id=uuid.uuid4(),
            node_execution_id=node_execution_id,
            agent_id=agent_id,
            evaluator="auto",
            scores=result.scores,
            weighted_score=result.weighted_score,
            confidence=result.confidence,
            summary=result.summary,
            strengths=result.strengths,
            weaknesses=result.weaknesses,
            suggestions=result.suggestions,
            passed=result.passed,
            severity=result.severity,
        )
        self.db.add(eval_record)
        await self._update_agent_performance(agent_id, result)
        await self.db.flush()
        return eval_record

    async def _update_agent_performance(
        self, agent_id: str, result: EvaluationResult
    ) -> None:
        stmt = select(AgentPerformance).where(AgentPerformance.agent_id == agent_id)
        row = await self.db.execute(stmt)
        perf = row.scalar_one_or_none()

        if not perf:
            perf = AgentPerformance(agent_id=agent_id)
            self.db.add(perf)

        count = (perf.evaluation_count or 0) + 1
        old_avg = perf.average_scores or {}
        new_avg = {}
        for dim in WEIGHTS:
            old = old_avg.get(dim, 0.0)
            cur = result.scores.get(dim, 0.0)
            new_avg[dim] = (old * (count - 1) + cur) / count

        perf.evaluation_count = count
        perf.average_scores = new_avg
        perf.last_evaluation_at = datetime.now(UTC).replace(tzinfo=None)
        perf.reliability = min(1.0, (perf.reliability or 1.0) * (0.9 if not result.passed else 1.05))

        if result.weaknesses:
            existing = list(perf.weakness_patterns or [])
            for w in result.weaknesses:
                found = next((e for e in existing if e.get("pattern") == w), None)
                if found:
                    found["count"] = found.get("count", 0) + 1
                else:
                    existing.append({"pattern": w, "count": 1})
            perf.weakness_patterns = existing
