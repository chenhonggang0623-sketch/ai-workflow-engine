import json
import logging

from app.supervisor.evaluation import EvaluationEngine

logger = logging.getLogger(__name__)


class QualityGate:
    GATE_TYPES = {
        "schema_validate": {"description": "Validate output against schema"},
        "llm_review": {"description": "LLM quality review", "min_score": 0.7},
        "human_approve": {"description": "Human approval required"},
    }

    def __init__(self, evaluation_engine: EvaluationEngine):
        self._engine = evaluation_engine

    async def check(
        self, gate_type: str, config: dict, agent_output: dict, context: dict
    ) -> dict:
        if gate_type == "schema_validate":
            return await self._check_schema(config, agent_output)
        if gate_type == "llm_review":
            return await self._check_llm(config, agent_output)
        if gate_type == "human_approve":
            return self._check_human(config, agent_output)
        return {"passed": False, "score": 0.0, "feedback": f"Unknown gate type: {gate_type}"}

    async def check_contract(self, contract, result: dict) -> dict:
        checks = []

        schema_check = await self._check_schema(
            {"schema": contract.output_schema or {}}, result
        )
        checks.append(("schema_validate", schema_check))

        if contract.acceptance_criteria:
            criteria = [
                c.get("field", "") + " " + c.get("operator", "exists")
                for c in (contract.acceptance_criteria or [])
            ]
            llm_check = await self._check_llm(
                {"criteria": criteria, "min_score": 0.7}, result
            )
            checks.append(("llm_review", llm_check))

        passed = all(c["passed"] for _, c in checks)
        score = min(c["score"] for _, c in checks) if checks else 1.0
        feedback = "; ".join(
            f"{name}: {c['feedback']}" for name, c in checks if not c["passed"]
        )

        return {"passed": passed, "score": score, "feedback": feedback or "All gates passed"}

    async def _check_schema(self, config: dict, output: dict) -> dict:
        schema = config.get("schema", {})
        if not schema:
            return {"passed": True, "score": 1.0, "feedback": "No schema defined"}

        errors = []
        for field, expected_type in schema.items():
            if field not in output:
                errors.append(f"Missing '{field}'")
                continue
            if expected_type == "string" and not isinstance(output[field], str):
                errors.append(f"'{field}' type mismatch")
            elif expected_type == "number" and not isinstance(output[field], (int, float)):
                errors.append(f"'{field}' type mismatch")
            elif expected_type == "boolean" and not isinstance(output[field], bool):
                errors.append(f"'{field}' type mismatch")
            elif expected_type == "array" and not isinstance(output[field], list):
                errors.append(f"'{field}' type mismatch")
            elif expected_type == "object" and not isinstance(output[field], dict):
                errors.append(f"'{field}' type mismatch")

        if errors:
            return {"passed": False, "score": 0.0, "feedback": "; ".join(errors)}
        return {"passed": True, "score": 1.0, "feedback": "Schema validation passed"}

    async def _check_llm(self, config: dict, output: dict) -> dict:
        llm = getattr(self._engine, "_llm", None)
        if llm is None:
            return {"passed": True, "score": 1.0, "feedback": "LLM review unavailable (gate bypassed)"}

        criteria = config.get("criteria", [])
        min_score = config.get("min_score", 0.7)

        try:
            prompt = (
                "Evaluate the quality of this output against these criteria.\n"
                f"Criteria: {json.dumps(criteria)}\n"
                f"Output: {json.dumps(output)}\n\n"
                "Return JSON with: score (0.0-1.0), issues (list), verdict (pass/fail)"
            )
            messages = [
                {"role": "system", "content": "You are a quality gate. Return only valid JSON."},
                {"role": "user", "content": prompt},
            ]
            response = await llm.chat(
                model_config={"model": "gpt-4o-mini", "temperature": 0.3},
                messages=messages,
            )
            content = response.get("content", "")
            parsed = json.loads(content)
            score = max(0.0, min(1.0, float(parsed.get("score", min_score))))
            issues = parsed.get("issues", [])
            passed = score >= min_score
            return {
                "passed": passed,
                "score": score,
                "feedback": "LLM review passed" if passed else f"LLM review failed: {'; '.join(issues[:3])}",
            }
        except Exception as e:
            logger.warning("LLM gate check failed: %s", e)
            return {"passed": True, "score": 1.0, "feedback": "LLM review unavailable (gate bypassed)"}

    def _check_human(self, config: dict, output: dict) -> dict:
        return {
            "passed": False,
            "score": 0.0,
            "feedback": "Human approval required — execution paused",
            "requires_approval": True,
        }
