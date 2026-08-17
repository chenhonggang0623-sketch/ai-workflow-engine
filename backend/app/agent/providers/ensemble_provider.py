import asyncio
import json
import logging
from copy import deepcopy

from app.agent.providers.base import AgentProvider
from app.agent.providers.registry import AgentProviderRegistry
from app.agent.providers.reviewer import AgentReviewer

logger = logging.getLogger(__name__)

AUDIT_PROMPT_TEMPLATE = """You are a code auditor. Review the following candidate module output for defects, security issues, and correctness problems.

Candidate output:
{output}

Task:
{task}

Return a list of findings as strict JSON:
{"findings": [{"severity": "critical|major|minor", "location": "...", "issue": "...", "suggestion": "..."}]}"""


class EnsembleProvider(AgentProvider):
    """单节点多 provider 执行：候选各自出方案 → 评审选优 / 审计合并。

    config.executor_config:
        candidates: list[str]           必填，如 ["openai", "codex_cli"]
        strategy: "best" | "concatenate" 默认 "best"
        mode: "normal" | "audit"         默认 "normal"（audit 为多 provider 审计）
        max_concurrency: int             默认 2（候选并行上限）
        dedupe: bool                     默认 True（best/concatenate 去重）
        audit_context_key: str|None      审计目标（audit 模式）
    """

    name = "ensemble"

    def __init__(
        self,
        registry: AgentProviderRegistry,
        reviewer: AgentReviewer | None = None,
    ):
        self._registry = registry
        self._reviewer = reviewer or AgentReviewer()

    async def execute(self, system_prompt, input_text, context, config):
        ec = config.get("executor_config") or {}
        candidates = config.get("candidates") or ec.get("candidates") or []
        if not candidates:
            return self._fail("Ensemble node requires executor_config.candidates", config)

        strategy = ec.get("strategy", "best")
        mode = ec.get("mode", "normal")
        max_concurrency = int(ec.get("max_concurrency", 2))
        dedupe = bool(ec.get("dedupe", True))

        sem = asyncio.Semaphore(max_concurrency)
        results: list[dict] = []
        errors: list[str] = []

        async def _run_one(idx: int, provider_name: str) -> None:
            provider = self._registry.get(provider_name)
            if provider is None:
                errors.append(f"Unknown candidate provider '{provider_name}'")
                results.append({
                    "index": idx, "provider": provider_name,
                    "success": False, "error": f"unknown provider '{provider_name}'",
                    "output": "",
                })
                return
            async with sem:
                try:
                    if mode == "audit":
                        audit_target = ec.get("audit_context_key")
                        audit_input = input_text
                        if audit_target and audit_target in context:
                            audit_input = json.dumps(context[audit_target], ensure_ascii=False, default=str)
                        cand_prompt = (
                            AUDIT_PROMPT_TEMPLATE
                            .replace("{output}", audit_input[:8000])
                            .replace("{task}", input_text[:2000])
                        )
                        res = await provider.execute(cand_prompt, "", context, deepcopy(config))
                    else:
                        res = await provider.execute(system_prompt, input_text, context, deepcopy(config))
                    results.append({
                        "index": idx,
                        "provider": provider_name,
                        "success": bool(res.get("status") == "success"),
                        "output": res.get("output") or "",
                        "error": res.get("error"),
                    })
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Candidate %s failed", provider_name)
                    results.append({
                        "index": idx, "provider": provider_name,
                        "success": False, "output": "", "error": str(exc),
                    })

        await asyncio.gather(*[_run_one(i, p) for i, p in enumerate(candidates)])

        if not results:
            return self._fail("No candidates executed", config)

        if dedupe:
            results = self._dedupe(results)

        if mode == "audit":
            return self._finish_audit(results, task=input_text, config=config)

        if strategy == "concatenate":
            return self._finish_concatenate(results, config=config)

        return await self._finish_best(results, task=input_text, config=config)

    async def _finish_best(self, results: list[dict], task: str, config: dict) -> dict:
        success_results = [r for r in results if r.get("success")]
        if not success_results:
            return self._fail("全部候选失败: " + "; ".join(r.get("error", "?") for r in results), config)

        verdict = await self._reviewer.pick_best(task, results)
        winner = verdict["winner"]
        if winner is None:
            winner = success_results[0]

        winner_output = self._normalize_output(winner.get("output"))

        return {
            "status": "success",
            "output": winner_output,
            "provider": self.name,
            "error": None,
            "ensemble": {
                "mode": "best",
                "winner_index": winner.get("index"),
                "winner_provider": winner.get("provider"),
                "scores": verdict.get("scores", []),
                "rationale": verdict.get("rationale", ""),
                "candidates": [
                    {k: r.get(k) for k in ("index", "provider", "success", "error")}
                    for r in results
                ],
            },
        }

    def _finish_concatenate(self, results: list[dict], config: dict) -> dict:
        parts: list[str] = []
        for r in results:
            out = r.get("output")
            if r.get("success") and isinstance(out, str):
                parts.append(out)
        if not parts:
            return self._fail("所有候选失败，无法拼接", config)
        return {
            "status": "success",
            "output": {
                "output": "\n\n--- candidate separator ---\n\n".join(parts),
            },
            "provider": self.name,
            "error": None,
            "ensemble": {
                "mode": "concatenate",
                "candidates": [
                    {k: r.get(k) for k in ("index", "provider", "success", "error")}
                    for r in results
                ],
            },
        }

    def _finish_audit(self, results: list[dict], task: str, config: dict) -> dict:
        findings_all: list[dict] = []
        critical = 0
        for r in results:
            if not r.get("success"):
                continue
            out = r.get("output")
            if isinstance(out, str):
                try:
                    data = json.loads(out)
                except (json.JSONDecodeError, TypeError):
                    data = {"findings": [{"severity": "minor", "location": "?",
                                          "issue": out[:500], "suggestion": ""}]}
            elif isinstance(out, dict):
                data = out
            else:
                data = {}
            for f in data.get("findings", []):
                severity = f.get("severity", "minor")
                if severity == "critical":
                    critical += 1
                findings_all.append({
                    "severity": severity,
                    "location": f.get("location", ""),
                    "issue": f.get("issue", ""),
                    "suggestion": f.get("suggestion", ""),
                    "reviewer": r.get("provider", ""),
                })
        return {
            "status": "success",
            "output": {
                "findings": findings_all,
                "critical_count": critical,
                "recommend_rerun": critical > 0,
                "reviewers": [r.get("provider") for r in results if r.get("success")],
            },
            "provider": self.name,
            "error": None,
            "ensemble": {
                "mode": "audit",
                "findings": findings_all,
                "critical_count": critical,
                "recommend_rerun": critical > 0,
                "reviewers": [r.get("provider") for r in results if r.get("success")],
            },
        }

    def _dedupe(self, results: list[dict]) -> list[dict]:
        seen: set[str] = set()
        out: list[dict] = []
        for r in results:
            key = json.dumps(r.get("output", ""), ensure_ascii=False, default=str)
            if key in seen:
                continue
            seen.add(key)
            out.append(r)
        return out

    @staticmethod
    def _normalize_output(output) -> dict:
        if isinstance(output, dict):
            return output
        return {"output": str(output) if output is not None else ""}

    def _fail(self, message: str, config: dict) -> dict:
        return {
            "status": "failed",
            "output": {},
            "provider": self.name,
            "error": message,
        }
