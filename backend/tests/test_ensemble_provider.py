from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.providers.base import AgentProvider
from app.agent.providers.registry import AgentProviderRegistry
from app.agent.providers.reviewer import AgentReviewer
from app.agent.providers.ensemble_provider import EnsembleProvider
from app.agent.executor.router import ExecutorRouter
from app.agent.executor.types import ExecutorType, ExecutionRequest


class StubProvider(AgentProvider):
    name = "stub"

    def __init__(self, output="stub output", fail=False, status="success", name=None):
        self._output = output
        self._fail = fail
        self._status = status
        if name:
            self.name = name

    async def execute(self, system_prompt, input_text, context, config, log_sink=None):
        if self._fail:
            return {
                "status": "failed",
                "output": {},
                "provider": self.name,
                "error": "stub failed",
            }
        return {
            "status": self._status,
            "output": self._output,
            "provider": self.name,
            "error": None,
        }


@pytest.fixture
def registry():
    reg = AgentProviderRegistry()
    reg.register(StubProvider("openai answer", name="openai"))
    reg.register(StubProvider("cli answer", name="opencode_cli"))
    return reg


@pytest.fixture
def provider(registry):
    return EnsembleProvider(registry)


@pytest.mark.asyncio
async def test_missing_candidates_fails(provider):
    result = await provider.execute("sp", "task", {}, {"executor_config": {}})
    assert result["status"] == "failed"
    assert "candidates" in result["error"]


@pytest.mark.asyncio
async def test_best_strategy_picks_winner(registry, provider):
    pick_best = AsyncMock(return_value={
        "winner": {"index": 1, "provider": "opencode_cli", "output": "cli answer"},
        "scores": [{"index": 0, "score": 5}, {"index": 1, "score": 9}],
        "rationale": "cli answer is more complete",
    })
    provider._reviewer.pick_best = pick_best

    result = await provider.execute(
        "sp", "task", {},
        {"provider": "ensemble", "executor_config": {"candidates": ["openai", "opencode_cli"]}},
    )
    assert result["status"] == "success"
    assert result["output"]["output"] == "cli answer"
    assert result["ensemble"]["winner_provider"] == "opencode_cli"
    assert result["ensemble"]["scores"][1]["score"] == 9
    pick_best.assert_called_once()


@pytest.mark.asyncio
async def test_concatenate_strategy(registry, provider):
    result = await provider.execute(
        "sp", "task", {},
        {"provider": "ensemble",
         "executor_config": {
             "candidates": ["openai", "opencode_cli"],
             "strategy": "concatenate",
         }},
    )
    assert result["status"] == "success"
    assert "openai answer" in result["output"]["output"]
    assert "cli answer" in result["output"]["output"]
    assert result["ensemble"]["mode"] == "concatenate"
    assert len(result["ensemble"]["candidates"]) == 2


@pytest.mark.asyncio
async def test_dedupe_removes_duplicate_outputs(registry):
    reg = AgentProviderRegistry()
    reg.register(StubProvider("same answer", name="a"))
    reg.register(StubProvider("same answer", name="b"))
    prov = EnsembleProvider(reg)

    result = await prov.execute(
        "sp", "task", {},
        {"executor_config": {
            "candidates": ["a", "b"],
            "strategy": "concatenate",
        }},
    )
    assert "candidate separator" not in result["output"]["output"]
    assert result["output"]["output"] == "same answer"


@pytest.mark.asyncio
async def test_all_candidates_failed(registry, provider):
    for name in ("openai", "opencode_cli"):
        registry._providers[name]._fail = True

    result = await provider.execute(
        "sp", "task", {},
        {"executor_config": {"candidates": ["openai", "opencode_cli"]}},
    )
    assert result["status"] == "failed"
    assert "全部候选失败" in result["error"]


@pytest.mark.asyncio
async def test_unknown_candidate_fails_node(registry, provider):
    result = await provider.execute(
        "sp", "task", {},
        {"executor_config": {"candidates": ["does_not_exist"]}},
    )
    assert result["status"] == "failed"


@pytest.mark.asyncio
async def test_audit_mode_aggregates_findings(registry, provider):
    reg = AgentProviderRegistry()
    reg.register(StubProvider(
        output='{"findings": [{"severity": "critical", "issue": "x"}]}',
        name="auditor1",
    ))
    reg.register(StubProvider(
        output='{"findings": [{"severity": "minor", "issue": "y"}]}',
        name="auditor2",
    ))
    prov = EnsembleProvider(reg)

    result = await prov.execute(
        "sp", "task", {},
        {"executor_config": {
            "candidates": ["auditor1", "auditor2"],
            "mode": "audit",
        }},
    )
    assert result["status"] == "success"
    out = result["output"]
    assert out["critical_count"] == 1
    assert out["recommend_rerun"] is True
    assert len(out["findings"]) == 2
    assert result["ensemble"]["mode"] == "audit"
    assert result["ensemble"]["recommend_rerun"] is True
    assert result["ensemble"]["critical_count"] == 1
    assert set(result["ensemble"]["reviewers"]) == {"auditor1", "auditor2"}


@pytest.mark.asyncio
async def test_deterministic_pick_used_when_no_llm(registry):
    prov = EnsembleProvider(registry, reviewer=AgentReviewer(llm_gateway=None))

    result = await prov.execute(
        "sp", "task", {},
        {"executor_config": {"candidates": ["openai", "opencode_cli"]}},
    )
    assert result["status"] == "success"
    assert result["output"]["output"] in ("openai answer", "cli answer")
    assert result["ensemble"]["winner_provider"] in ("openai", "opencode_cli")


@pytest.mark.asyncio
async def test_router_dispatch_to_ensemble_provider():
    reg = AgentProviderRegistry()
    reg.register(StubProvider("openai answer", name="openai"))
    reg.register(StubProvider("cli answer", name="opencode_cli"))
    reg.register(EnsembleProvider(reg, reviewer=AgentReviewer(llm_gateway=None)))

    router = ExecutorRouter(provider_registry=reg)
    request = ExecutionRequest(
        task={"prompt": "task"},
        context={},
        config={
            "provider": "ensemble",
            "system_prompt": "sp",
            "executor_config": {
                "candidates": ["openai", "opencode_cli"],
            },
        },
    )
    result = await router.execute(ExecutorType.LLM_API, request)
    assert result.success is True
    assert result.metadata.get("provider") == "ensemble"
    assert result.metadata.get("ensemble") is not None
    assert result.metadata["ensemble"]["winner_provider"] in ("openai", "opencode_cli")
    assert "output" in result.output
