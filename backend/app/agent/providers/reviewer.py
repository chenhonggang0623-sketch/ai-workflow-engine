import json
import logging

from app.core.app_config import config_store
from app.core.config import settings

logger = logging.getLogger(__name__)

REVIEW_PROMPT = """You are an expert reviewer. Multiple agents produced candidate outputs for the same task.
Score each candidate on: correctness, completeness, executability, and style (each 0-10).
Return ONLY valid JSON: {"winner": <index of best candidate>, "scores": [{"index": 0, "provider": "...", "correctness": 8, "completeness": 9, "executability": 7, "style": 8, "total": 32, "rationale": "..."}], "overall_rationale": "..."}

Task:
{task}

Candidates:
{candidates}"""


class AgentReviewer:
    """评审 agent：对多候选输出打分、选优。

    - 有可用 LLM 时：LLM 打分（解析失败回退确定性兜底）。
    - 无 LLM / 调用失败：确定性兜底（选文本最长者）。
    """

    def __init__(self, llm_gateway=None):
        self._llm = llm_gateway

    @property
    def available(self) -> bool:
        return self._llm is not None and config_store.has_openai_api_key()

    async def pick_best(self, task: str, candidates: list[dict]) -> dict:
        """candidates: [{"index": int, "provider": str, "output": str|dict, "success": bool}]

        返回 {"winner": candidate|None, "scores": [...], "rationale": str}
        """
        successful = [c for c in candidates if c.get("success")]
        if not successful:
            return {"winner": None, "scores": [], "rationale": "no successful candidate"}

        if self.available:
            try:
                return await self._review_with_llm(task, candidates)
            except Exception as exc:
                logger.warning("LLM review failed, falling back: %s", exc)

        return self._deterministic_pick(successful)

    async def _review_with_llm(self, task: str, candidates: list[dict]) -> dict:
        payload = []
        for c in candidates:
            out = c.get("output")
            if not isinstance(out, str):
                out = json.dumps(out, ensure_ascii=False, default=str)
            if len(out) > 4000:
                out = out[:4000] + "..."
            payload.append({
                "index": c.get("index", 0),
                "provider": c.get("provider", ""),
                "output": out,
            })

        prompt = (
            REVIEW_PROMPT
            .replace("{task}", task[:2000])
            .replace("{candidates}", json.dumps(payload, ensure_ascii=False, indent=2))
        )
        result = await self._llm.chat(
            model_config=self._model_config(),
            messages=[
                {"role": "system", "content": "You are a strict scoring reviewer. Output ONLY JSON."},
                {"role": "user", "content": prompt},
            ],
        )
        content = result.get("content", "")
        data = self._parse_json(content)

        winner_idx = data.get("winner")
        if isinstance(winner_idx, dict):
            winner_idx = winner_idx.get("index")
        if not isinstance(winner_idx, int):
            raise ValueError(f"Review winner index invalid: {winner_idx!r}")
        winner = next(
            (c for c in candidates if c.get("index") == winner_idx),
            None,
        )
        if winner is None:
            raise ValueError(f"Review winner index {winner_idx} not found in candidates")

        return {
            "winner": winner,
            "scores": data.get("scores", []),
            "rationale": data.get("overall_rationale", ""),
        }

    def _deterministic_pick(self, successful: list[dict]) -> dict:
        best = max(
            successful,
            key=lambda c: len(json.dumps(c.get("output", ""), ensure_ascii=False, default=str)),
        )
        return {
            "winner": best,
            "scores": [{"index": best.get("index"), "provider": best.get("provider"),
                        "rationale": "deterministic fallback: longest output"}],
            "rationale": "No LLM reviewer available; chose longest successful output.",
        }

    def _parse_json(self, content: str) -> dict:
        content = content.strip()
        if content.startswith("```"):
            content = content.strip("`")
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end > start:
                return json.loads(content[start : end + 1])
            raise ValueError("No valid JSON in reviewer output")

    def _model_config(self) -> dict:
        return {
            "model": config_store.get("default_llm_model", settings.default_llm_model),
            "provider": config_store.get("default_llm_provider", settings.default_llm_provider),
            "base_url": config_store.get("openai_base_url", settings.openai_base_url),
            "temperature": 0.2,
            "max_tokens": 2048,
        }
